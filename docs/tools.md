# Tools

- Driving the running app: write commands to `~/djs/root/tmp/djspanel`
  (`tap <byte> <bit>`, `bit <byte> <bit> <0|1>`, `enc <0-6> <delta>`,
  `pad <n> <a> <b>`, `word <offset> <value>`, `click <x> <y> [button]`,
  `usb <0|1>`, `strip <0-127|-1>`, `byte <offset> <value>`, `shot`,
  `key <keysym>`: a keyboard key pressed and released, which the app takes
  as one of its own shortcuts, a real BackSpace being BACK, even in a text
  field). Keys in the window: Enter = encoder push, `,` `.` = turn it,
  F1–F6 (Shift = back) = knobs 1–6, Escape/Backspace = BACK, H = HOME, Space/B/N = PLAY/STOP/REC,
  1–8 and Q–I = step keys 1–16, P = PROJECT, L/X/-/S = LIVE SAMPLING / FX /
  TEMPO RANGE / SYNC.
- `tools/shot.py out.png [command ...]`: send commands, then save a
  screenshot (the shim copies what the app draws with `XPutImage`).
- `tools/probe.py <folder> [command ...]`: try inputs one by one and keep a
  screenshot of each one that changes the screen (`PROBE_RESET="tap 5 5"`
  returns to HOME after each change).
- `start.py`: the emulator and the deck in one command. `start.py stop` and
  `start.py status` for an emulator left running (`--keep`, `--no-deck`).
- `tools/make_test_kit.py`: writes Kick, Snare, Hat, Clap and Tone to
  `Samples/Test Kit` on the USB folder (run it in WSL).
- `tools/regress.py`: a fixed session with the app on a fresh unit, recorded
  as screens and sounds, and compared with a reference. See below.
- `tools/session.py`: what `regress.py` is written with: connect to the
  running app, press, turn, touch, hit pads, wait for the screen to hold
  still, take the screen and record the sound. Works beside an open deck.
- `tools/deck_selftest.py`: presses, drags and releases the mouse on every
  control of the virtual deck with no app running. Run it after changing
  `app/`.
- Pro DJ Link decks: deckbench (its own repository, beside this one or named by `DECKBENCH`). `start.py` runs it in the emulator's network. Its page is at <http://localhost:8750/>.
- `tools/xref.py <binary> "<string>"`: where a string is used, with the code
  leading up to it and the branches to it.
- gdb: `scripts/run.sh 300 -g 1234`, then `gdb-multiarch` with `set sysroot
  ~/djs/root` and `target remote :1234`. Child processes the app starts also
  try to open the gdb port and fail. Harmless. Interrupting from outside
  hangs: stop on a breakpoint instead (e.g. `break read if $r0 == 6` with
  `ignore` for "after a while").

## The regression session

`python tools/regress.py reference` records the session on the firmware as
it is. `python tools/regress.py` records it again and compares. `python
tools/regress.py --patch FILE` does so with FILE on the drive as
`autoexec.bin`, to see what a patch changes. It takes
under three minutes, starts and stops an emulator of its own (stop yours
first), and runs without windows when `xvfb` is installed. The unit is fresh
each time: `DJS_DATA` and `DJS_USB` point `run.sh` at an empty settings
folder and a USB folder that holds only the test kit, under
`~/djs/regress/`.

What it does, and keeps in `regress/<name>/` (not committed: the screens are
the firmware's): CREATE NEW. Load Kick, Snare and Hat on tracks 1 to 3. Each
pad's sound. The kick with the strip at the top in PITCH mode. The kick
through the HPF effect at full depth. A two-bar sequence. The tempo slider
at its + end. SAVE AS, and the project file on the drive. Sixteen items.

Two runs of the same firmware come out identical: every screen pixel for
pixel, every sound sample for sample once lined up on its first loud sample.
So a difference is the firmware's (or the emulator's) doing. A screen fails
when 0.02 % of its pixels differ, a sound when it differs by 1 % RMS or ends
20 ms apart.

Two things learnt writing it: a button that starts something moving on the
screen (PLAY) must be sent with `tap()`, since `press()` waits for the screen
to hold still. And STOP cuts whatever is sounding, so the sequence is laid
out to have gone quiet before it.

## Next

- The lamps not matched to a control (SYNC, MASTER, HOME).
- Tried and working: CREATE NEW, OPEN, SAVE, SAVE AS, DELETE, SAVE AS
  PACKAGE (`Projects/<name>.tpkg`), RENDER AUDIO (`RenderedAudio/<project>/
  Pattern/S01P01_Master.wav`, 24-bit), loading samples in BROWSE, UTILITY
  (hold HOME, and a changed setting is still there after a restart, in
  `PadPlayer.dat` on the data partition), PATTERN + a step key to change
  pattern, SCENE + a step key to change scene.
- LIVE SAMPLING has an input now (the IN meter moves) but has not been
  gone through.
- "Samples [INTERNAL]" in BROWSE is empty: the factory samples are on the
  unit's eMMC (`/mnt/emmc`), not in the update.
