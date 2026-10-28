# Changelog

Newest first. A release is a tagged commit.

## v0.3.0

Tested on WSL2 with Ubuntu 24.04. The regression session comes out identical to the reference, the deck's self-test passes, and
setup was run from scratch into a new folder.

### The virtual deck

- REC (the first row of the TOOLS menu, or F7) records the window and its sound to `demo/captures`. It writes the video, the sound
  alone, and a script of every command the deck sent, which `tools/reel.py` plays again on a fresh unit to make a reel. It needs
  `ffmpeg`.
- A TOOLS menu (F8) and a status line with readings: the master's level, how fast the sound arrives, and how much sound waits to be
  played. With the mouse over nothing the line shows your last action as a line for a script, and a click copies it.
- A right click on a pad or a step key holds it down until it is clicked again. The pad velocity can be set from the menu.
- The sound is buffered more and its cuts are counted (`--audio-buffer MS`, default 150). `--audio-block FRAMES` is the block given to
  the sound card, and a bigger one rides out a busy deck.
- The deck has a window icon (the CC mark) and a layout centred in the window. The status line's buttons light up under the mouse
  and show a hand cursor. A right-click-held key's ring is smoother. Held pads and step keys show only the unit's lamps, so a pad flashes only when the app flashes it.
- A DECKBENCH button in the status line, beside TOOLS. With deckbench running, its actions are recorded beside a REC and played
  back, and the INPUT SOURCE knob of LIVE SAMPLING picks which deckbench deck the app hears.
- The unit's internal storage is bound in from `$DJS_EMMC`, or from `~/djs/emmc` when that holds a `PIONEER DJ SAMPLER` folder.

### Videos

- Resolutions (`--res hd`, `2k`, `4k`), keyable backgrounds (`--bg black`, `green`, `transparent`) and a clean video without text.
  A reel is made as the website's hero shape at 2K unless the episode says another. The clean hero panels fill the height and line up
  with the unit's case.
- The video is H.264 at a higher quality for editing. The sound is written whole beside it at 48 kHz with the pitch kept, as 320k AAC
  inside the video.
- A reel can replay a REC with its project and moving knobs and show the mods panel. `--status` shows the deck's status line, and
  REC videos keep it. A step can take `# before:` setup lines.

### Setup

- Setup extracts into a staging folder before replacing an installation. An existing installation needs `--rebuild`,
  which backs up its previous firmware files and settings. Unsafe or unrecognised destinations are rejected.
- Unexpected archive extraction errors stop setup instead of leaving an incomplete installation marked ready.
- Setup's rejection and staging paths have firmware-free tests (`tools/test_setup.py`), and a GitHub Action runs them.

### Fixes

- The deck gives deckbench's address as 127.0.0.1, because from Windows to WSL `localhost` waited 2 seconds on every new connection.

### Docs

- The README focuses on first use. `docs/running.md` covers off-screen interaction, scripting and platform details.
- Linux virtual machines on macOS are described as untested, not unsupported. The launcher does not manage the VM.
- The README says why the emulator is lightweight and how the app runs in user mode.

## v0.2.0

Tested on WSL2 with Ubuntu 24.04. The regression session comes out identical to the reference, and the deck's self-test passes.

### The virtual deck

- The face now looks like the unit (`--face real`, the default): black gloss plastic, a bevelled screen housing, a chrome frame round the pads, brushed metal transport keys with their lamps shining through, grey rubber pads and flat step keys. `--face flat` is the first look.
- The bright last column and row along the right and bottom of the screen are gone. The bezel is black there.
- `--mute` plays nothing but still shows the MASTER / PHONES switch, for recordings.

### Docs

- The README says where `autoexec.bin` goes to try the mods: the top of the USB folder, then start the emulator again.
- The README describes scripted use.

### Videos

- `tools/reel.py` makes short videos of the emulator from an episode, a script of scenes. Shapes (`--shape`): 1080x1920 for Reels and Shorts, 1920x1080, the website's picture, or the deck's window as it opens.
- `tools/reels/example.py` is the one to start from. `tools/reels/hero.py` makes the website's picture, playing. Your own episodes go in `demo/episodes`, which git ignores.
- `--check` looks at an episode without a unit.
- A reel can record from the simulated decks (`INPUT = True`) for live sampling. The headphones, which carry the input monitor, are mixed into the reel's sound.
- A recording script can move the tempo slider and hold a key down (`slider`, `key`).

### Fixes

- On Windows, commands in a recording script could run again or late. The deck read the file's two-byte line ends as one. It now reads the file in bytes.

## v0.1.0

First release. Tested on Windows 11 with WSL2 and Ubuntu 24.04.

### The emulator

- The DJS-1000's own app (firmware 1.22) runs unmodified under `qemu-arm` user mode, in the unit's root filesystem. Its devices are stand-ins: the panel, the touch strip, the backlight and the sound card.
- Several emulators can run side by side.
- The guest runs in a chroot inside a user namespace, so it needs no root. `proot` is the fallback, about three times slower to start the app.

### The virtual deck

- Draws the machine: the screen, every lamp, and every control (buttons, pads, step keys, knobs, rotary selector, tempo slider, touch strip).
- Master and headphone outputs, and a recording device as the input.
- Lists the mods of the patch on the drive, grouped as on the mods' website, with a switch for each. Hover a row to read the mod's text.

### USB drive and mods

- A USB drive is a host folder. Samples load from it, and projects are saved, opened, deleted and rendered there.
- An `autoexec.bin` in that folder runs as it does on a stick, which is how the mods are tried before a real unit.
- The mods' settings are read from `djs1000-mods.txt` on the drive.

### Pro DJ Link

- Works with simulated decks. The unit announces itself as player 1 and sees the decks, so SYNC, MASTER and the mods that read the decks all work.
- The decks are deckbench's, a separate project that `start.py` runs.

### Tools

- `tools/regress.py` records a fixed session and compares it with a reference.
- `tools/session.py` scripts the app.

### Not yet

- MIDI.
- Real decks on a physical network. WSL2's default networking does not see them.
- macOS.
