# Changelog

Newest first. A release is a tagged commit.

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
