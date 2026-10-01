# Power button and standby

- Button id 0 (byte 5 bit 4) is the power/standby key. `PowerManager`
  (a thread of that name, with a handler of its own
  for the buttons) listens to every control and
  runs a 20-minute auto-standby timer. On press of id 0 it calls each
  `IStandbyReqReciever`'s first method (abort). On release it calls the
  second with 0 — `goStandbyMode(bool)` on `ProjectManager`,
  `MySettingsFile`, `UsbStorageManager` — and once they are done the app's
  frame to the panel carries "transition Standby!" (tx `0x6C` bit 1).
- In standby the UI and panel still work, but `ProjectManager` no longer
  does anything (CREATE NEW returns to the menu and changes nothing, no log).
- `DJSDEV_POWER_PULSE=1` makes `djsdev.c` hold the key from the start and
  release it five seconds after the first draw, to look at standby. It used
  to be always on, as a workaround: see below.
- The app checks `/tmp/nand_mount`, which `apl_start`
  writes after mounting `/root/data`. Creating it changed nothing visible.
- Thread names are visible on the host: `cat /proc/<qemu pid>/task/*/comm`.

## The dead panel at startup (solved)

Without the power pulse the app used to ignore the panel altogether. The
cause was the audio device, not the panel: the app's ALSA device never
opened, so nothing was given a sample rate (`PlayerUnit::prepareToPlay -
isEqualFloatValue (sampleRate, 44100.0)`, `AutoBpmDetector prepareToPlay
Error`) and the startup sequence did not complete.

The app's ALSA code is JUCE's, changed to drive three PCMs as one device
(its own scan, open, thread and write routines): outputs `hw:ak4452audio,1` (master) and `hw:ak4452audio,0`
(headphones), input `hw:ak4452audio,0`.

- If any of the three fails to open, the whole device fails. The shim used
  to refuse the input, hence the above.
- The app asks for 4 output channels in all and hands each output device
  `clamp(4, its min, its max)` of them, in order, out of one 5-channel
  buffer. On the board each device is stereo, so 2 + 2. ALSA's `null`
  reports 1–32, so the first device took all 4 and the second was given
  channel pointers past the end of the buffer (null): the thread crashed in
  the buffer copy in the audio thread. That was the "capture on null crashes" seen
  earlier. Capture had nothing to do with it.
- The interleaved input path reads 2 channels of 24-bit-in-32 integers.

So `djsdev.c` now opens all three on `null` (or `$DJSDEV_PCM`) and narrows
the channel range they report to exactly 2
(`snd_pcm_hw_params_get_channels_min/max`). With that the app starts on the
PROJECT menu with a live panel, no standby. CREATE NEW gives an empty
project and SAVE opens its dialog ("Save To: ---": no storage yet).
