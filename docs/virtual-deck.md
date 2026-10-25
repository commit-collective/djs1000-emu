# The virtual deck

`app/virtual_djs.py` draws the DJS-1000's top panel in a window and drives
the running app through it: the app's screen sits in the face (and at full
size beside it), the lamps are the ones the app lights, and the controls go
to the app as the panel's would. It runs on the host (Windows, or Linux),
not in the rootfs:

```sh
python -m pip install -r requirements.txt     # pygame-ce, Pillow
python app/virtual_djs.py                     # on Windows: py -3 app/virtual_djs.py
```

`start.py` runs the emulator and the deck together. By hand, start
`scripts/run.sh` first or after. The window connects when the app is there,
and again after a restart. Until the app has drawn, which takes about half a
minute from a cold start, its screen says so with a progress bar.

Beside the face is the app's screen at full size, the easier one to touch,
and under it the list of installed mods and a reminder of what the mouse and the keys do, each in a box closed by a thin line (`--no-outline`
leaves the lines out, and a recording leaves them out too, as the reels frame their cards themselves). For a screen recording that is keyed on
its brightness, the window is black only where nothing is, round the unit and between the boxes, and every pixel of the unit and of the
boxes is at least 4 of 255 bright (the way the black reels are made), so a luma key of a few points takes out the background alone. That is
how it starts (`--key 6` for a lift of 6, `--no-key` for the blacks as they are, and a `--record` is made without it). The status line at the
foot is not kept off black: crop it, or hide it (F9). F10 hides that
panel and narrows the window to the face (`--compact` starts that way). F12
swaps the reminder for the lamp diagnostics: every two-level lamp by id, as
the app sets it. The face is drawn as the unit looks (`--face real`, the default): black gloss plastic with a lit rim and raised
rails down the sides, a bevelled housing for the screen with framed PROJECT, SAMPLING and FX buttons and a knurled encoder in a chrome ring, a chrome
frame round the pads, transport keys of brushed metal right through with their lamp shining in the middle, a grained FX strip, dull translucent grey pads (rubber) and step keys (hard plastic, flat) while their lamps are
off, and a little shade under the controls. It costs a third of a second once at the start and nothing per frame, because the face
and the keys are made once and kept. `--face flat` (or `$DJS_FACE=flat`) is the first look: dark grey plastic and flat controls. Hold the mouse on keys and pads (a pad
plays harder the lower you press it), turn knobs with the wheel or by
dragging, click the selector to push it, and use the mouse as a finger on
the screen. The status line names the control under the mouse and its
keyboard key.

The right of the status line has some readings, and a TOOLS button (F8) with a menu. The readings are the master's level (a bar with a
held peak, and a red mark for a sample at full scale), how fast the sound arrives (`×1.00` is real time: the emulator runs a little
fast or slow, and below about 0.97 it is not keeping up, which is when the sound drops out), and how much sound waits to be played
against how much is asked (`waits 118 of 150 ms`, see `--audio-buffer`). With the mouse over nothing, the line shows the last thing
you did as a line for a script (`ctx.touch(487, 333)`, `ctx.press((2, 3))  # play`) and a click on it copies it. The menu has: the
keyable background (`--key`), the side panel outline, the status line (F9), always on top, the velocity of a pad hit by the mouse, a larger or smaller window, unplugging
and plugging in the USB stick, where the app's sound input comes from (this computer's recording device, deckbench's decks or nothing:
the same as `--input` and `--input-tcp 127.0.0.1:7320`, changed as it runs), the time the sound waits (50 ms at a time, while it plays) and
a way to deckbench's page. With the status line hidden, the TOOLS button comes up when the mouse goes to the foot of the window, so that
the line and the menu can always be reached.

**REC** (the first row of the menu, or F7) records the window to `demo/captures` (`--captures DIR`, 30 frames a second, `--fps`): a video of the
window as it is, with the keyable background, but without its status line or the menu, so that nothing has to be cropped, and the sound as
you hear it: the output the MASTER / PHONES switch has chosen (not the two added, which would thin it: the headphones carry a quieter, partly
inverted copy of the program). When it ends (REC again, or closing the window) the picture is retimed by a
percent or two to follow the sound (the emulator's sound runs a little fast or slow against the clock, and the sound keeps its pitch), and three files are made: `deck-DATE-TIME.mp4`, `deck-DATE-TIME.steps` (every command the deck sent, with its second, and the project the app had open, which
`python tools/reel.py demo/captures/deck-DATE-TIME.steps` plays again on a fresh unit to make a reel of it) and `deck-DATE-TIME.wav` (the
sound alone, 24 bits). It needs `ffmpeg` on the path. The status line shows a red REC and the time. A window that is resized while it
records is scaled to the size it began with. `--record` is the scripted capture of the reels and has no REC.

A right click on a pad or a step key holds it down until it is clicked again (left or right click, or its keyboard key for a step key): it
is drawn pressed, with an amber ring round it. A pad is hit as hard as where on it the mouse is (harder towards the bottom) unless the menu's
**Pad velocity** says a share of full velocity (10 to 100 %: a click on the left half of the row is less and on the right half more, and
past 100 it goes back to by position), which a held pad uses too.

When deckbench's page answers (`--bench URL`, `http://127.0.0.1:8750/` by default, where `start.py` starts it) the status line says how
many of its decks are on and playing, which is the master and how many play a file of their own (deckbench's `--track`), and a click on it
opens the page.

When the patch on the USB folder carries mods (`autoexec.bin` from the
djs1000-mods project), the panel lists them above the reminder, grouped as the
mods' website groups them, each with an ON / OFF switch, its title and its key.
The mouse on a row shows the mod's text (the website's own words, then what it
needs) under the list. A click on a switch rewrites the mod's line in `djs1000-mods.txt` on the
USB folder, which the mods read again as the app runs: no restart. The list
of mods is the patch's own (`modlist.txt` in it, which the emulator opens at
each start: a name, a title, a group, the page text, what it needs and a status
for each. The deck does not know any mod by name. A patch from before the
titles has only a short line on each, shown in their place). A mod that is work in progress is off
until its line says on. `start.py` tells the deck where the folder and the list
are (`--usb DIR`, `--modlist FILE`).

SYNC and MASTER light as the unit's own lamps do (lamps 0x1B and 0x1C: the app
writes "dim" for off, drawn as unlit. MASTER backlit orange, SYNC white).

Pro DJ Link. The fake decks are not in this window: they are
deckbench's (a repository of its own, `deckbench`, beside this one or named
by `DECKBENCH`), which `start.py` runs in the emulator's network when
it finds it, four decks, players 1 to 4, off until its page switches them on
(the emulated unit is player 1: deck 1 is there to show it in the list, and
stays off, a deck with the unit's number being a clash). The page
is at <http://localhost:8750/> (it prints the address when it starts): a row
for each deck with ON, PLAY, SYNC and MASTER, the deck's four beat squares and
its BPM. See deckbench's own README and `docs/prolink.md` for what the decks
send and for what a DJS-1000 was found to need from them.

What the emulated unit then does, with an ON deck: it sees it as a linked
player (SYNC and MASTER on the unit work), and a mod that reads Pro DJ Link
(the djs1000-mods project's `sample-names`, whose deck is the input picked with
the 5th knob of LIVE SAMPLING) has decks to ask. A deck switched off is gone to
it after a few seconds.

The unit follows a deck that is the master and plays: its SYNC lights, its
display says "MASTER PLAYER 2" with the master's beat in its four squares, and
its BPM is the master's (128.0). The unit's own MASTER while a deck is master
is a hand-off: the unit asks, the deck yields, and the unit is the master (its
MASTER lamp lights). A deck's MASTER while the unit is the master asks the unit
as a CDJ does: the unit hands over, and its MASTER goes off.

The start script restarts what is stale: a bench older than deckbench's
source, and an emulator older than `shim/djsdev.c`.

Sound, all at 44.1 kHz stereo:

- the main device (the system's default, or `--audio NAME`: the device whose
  name contains NAME) plays the master output or the headphone output. The
  MASTER / PHONES switch in the status line, or Tab, chooses (`--listen
  phones` starts on the headphones). `--no-audio` plays nothing
  and shows no switch, `--mute` plays nothing too but shows the switch as if a sound device were there (for a recording)
- `--headphones NAME` names a second device that plays the headphone output
  all the time
- `--audio-buffer MS` (default 150) is how much sound waits before playing starts. The app is emulated and gives its sound
  in bursts: when it is late, the deck runs dry and the sound cuts for a moment while it fills up again. More is steadier and later.
  The status line counts the times: `dry` is the app being late with its sound, `late` is the deck being busy when the sound card asked
  for it. `--audio-block FRAMES` (default 2048) is the block the sound card is given at a time: a bigger one (8192) rides out the deck
  being busy, at as much more delay.
- the app's input (LIVE SAMPLING, and whatever monitors the input) is fed
  from the system's default recording device, or `--input NAME`,
  `--no-input` feeds silence. With a microphone and speakers, monitoring the
  input in the app will feed back
- `--input-tcp HOST:PORT` feeds the input from a TCP stream of raw stereo 16-bit 44.1 kHz samples
  instead of a device: deckbench's `--audio-port`, a drum loop in time with each playing simulated deck
  (it connects again if the stream goes away, and INPUT LEVEL works). A take in LIVE SAMPLING then records something that
  is on the deck's beat, with no sound card or microphone
- `--list-audio` prints the playback and recording devices

## How it is made

| | |
|---|---|
| `app/layout.py` | where each control is, its bit in the panel's frame, its lamp |
| `app/art.py` | draws the face and the lit/pressed sprites with Pillow. No photo or artwork is used, and the logo and model name are left off |
| `app/link.py` | the TCP link to the shim |
| `app/audio.py` | plays the outputs and records the input (SDL, through pygame) |
| `app/virtual_djs.py` | the window (pygame-ce) |

The shim listens on `127.0.0.1:7310` (`DJSDEV_PORT`, 0 turns it off) and
serves up to four clients at once, each sent everything: a script can watch
and drive the app beside the deck. The deck sends the same command lines as the pipe takes
(`docs/tools.md`), plus `touch <1|2|0> <x> <y>` for press, move, release.
The shim sends, each with an 8-byte header: `'S' 0, y, rows, width` (LE16)
and `rows*width*4` bytes of BGRX for the rows of the screen that changed,
`'L'` and the 128-byte frame the app sends the panel when it changes, and
`'A' n, frames, position` (position: LE32, where the first frame is in
the output, counted from the start. The same moment on both outputs) and
`frames*8` bytes of output n (0 master, 1 headphones, stereo float32,
44.1 kHz) every 5 ms. The deck sends the input's sound as
the line `in <frames>` followed by `frames*4` bytes (stereo 16-bit).
Under WSL2 the port is reachable from Windows as `127.0.0.1` (localhost
forwarding).

## What is known and what is not

Every button is bound, and so are the pads, the step keys, the rotary
selector and its push, the six knobs, the screen, the tempo slider (drag it,
right-click puts it back at the centre), FX LEVEL/DEPTH and the touch strip
(hold the mouse on it and slide, and the app lights its lamps). A right-click on
the strip leaves a finger there, so that the mouse is free to hit a pad
while the strip is touched. Another right-click lifts it. The deck sends
where its slider and pots stand when it connects.

Two knobs are not as on the unit. PHONES LEVEL is the knob on the unit's
front, drawn under INPUT LEVEL: the headphone output is silent at MIN.
INPUT LEVEL is not in the panel's data (it seems to be an analogue gain), so
the deck applies it to the sound it sends to the app's input: silent at MIN,
unchanged at MAX.

Lamps: the 32 colour lamps are the pads (0–15) then the step keys (16–31).
Each two-level lamp was matched to its control by pressing the control. A
few are not matched yet (SYNC, MASTER and HOME have none). The lamp
diagnostics (F12) show every one by id.


Keyboard: Space PLAY/PAUSE, B STOP, N REC, Left Shift SHIFT, M MODE, H HOME,
Esc or Backspace BACK, P PROJECT, L SAMPLING, X FX, S SYNC, `-` TEMPO range,
1–8 and Q–I the step keys, F1–F6 the knobs (with Right Shift the other
way), Tab MASTER / PHONES. The selector: Up and Down (or `,` `.`) turn it,
Page Up and Page Down by five, Enter or Right push it, Left is BACK.

## Recording

`python app/virtual_djs.py --record demo.mp4` records the window as video (25 frames a second by default, `--fps`) and the master
output as `demo.mp4.f32` (raw stereo float32) until a file `demo.mp4.stop` exists. A frame is repeated when the drawing was late, so
the video keeps the real time. The window is the full layout whatever the size of the desktop, so it can run with
`SDL_VIDEODRIVER=dummy`, and the controls' reminder is folded to leave the room to the list of mods. While it records, the deck also
runs the lines that a script appends to `demo.mp4.cmd` (`hover MOD`, `toggle MOD`, `page mods|off`, `knob NAME DELTA`, `slider POS`,
`key NAME 1|0`) and writes the time it began to
`demo.mp4.start`. `tools/demo.py` uses all of this to make a demonstration video (see [tools.md](tools.md)).

The deck sends a pad's two readings as the same value, 460–860 by where
the pad is pressed (lower is harder), and 0 on release. See "Pads" in
[panel-protocol.md](panel-protocol.md). The six knobs under the screen are
encoders and carry no mark. The two level knobs are pots with a 270° travel.
