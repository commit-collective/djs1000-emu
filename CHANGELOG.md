# Changelog

Newest first. A release is a tagged commit.

## v0.2.0

Tried on WSL2 with Ubuntu 24.04. The regression session comes out identical to the reference, and the deck's self-test passes.

- The virtual deck draws the face as the unit looks (`--face real`, now the default): black gloss plastic with raised rails down the sides, a
  bevelled screen housing with framed PROJECT, SAMPLING and FX buttons and a knurled encoder in a chrome ring, a chrome frame
  round the pads, transport keys of brushed metal right through with their lamp shining in the middle, a grained FX strip, dull
  translucent grey pads (rubber) and step keys (hard plastic, flat) while their lamps are off, shade under the
  controls. It costs nothing per frame. `--face flat` is the first look, and stays available.
- The virtual deck no longer shows the app's bright last column and row along the right and bottom of its screen (the bezel is black there).
- `--mute` plays nothing but shows the MASTER / PHONES switch as if a sound device were there, for a recording.
- The README says where `autoexec.bin` goes to try the mods: the top of the USB folder, then start the emulator again.
- `tools/reel.py` makes short videos of the emulator from an episode, a script of scenes: 1080x1920 for Reels and Shorts, or 1920x1080,
  in the look of the website's picture, or the deck's window as it opens (`--shape`). `tools/reels/example.py` is the one to start from,
  your own episodes go in `demo/episodes` (git ignores it) and `--check` looks at an episode without a unit. `tools/reels/hero.py` makes
  the website's picture itself, playing.
- A reel can record from the simulated decks (`INPUT = True`) for live sampling: `start.py` starts deckbench with its audio port, and the
  headphones, which carry what the input monitor plays, are mixed into the reel's sound.
- A recording script can move the tempo slider and hold a key down (`slider`, `key`). Its commands could run again, or late, on Windows:
  the file of commands has two bytes at the end of a line there and the deck counted one. It reads the file in bytes now.

## v0.1.0

First release.

- The DJS-1000's own app (firmware 1.22) runs unmodified under `qemu-arm` user mode, in the unit's root filesystem,
  with stand-ins for its devices: the panel, the touch strip, the backlight, the sound card.
- A virtual deck draws the machine: the screen, every lamp, every control (buttons, pads, step keys, knobs, rotary
  selector, tempo slider, touch strip), with the master and headphone outputs and a recording device as the input.
- A USB drive is a host folder: samples load from it, and projects are saved, opened, deleted and rendered there.
- An `autoexec.bin` on that folder runs as it does on a stick, which is how the mods are tried before a real unit.
- Several emulators can run side by side. The guest runs in a chroot inside a user namespace (it needs no root, and `proot` is the
  fallback, about three times slower to start the app), and each emulator's processes are told apart by their
  mount namespace.
- `tools/regress.py` records a fixed session and compares it with a reference. `tools/session.py` scripts the app.
- The deck lists the mods of the patch on the drive, grouped as the mods' website groups them, with a switch for each. The
  mouse on a row shows the mod's text.
- Pro DJ Link works with simulated decks. The unit announces itself as player 1 and sees the decks, so SYNC and MASTER work
  and so do the mods that read the decks. The decks are deckbench's, a separate project that `start.py` runs.
- Settings of the mods are read from `djs1000-mods.txt` on the drive.

Tried on Windows 11 with WSL2 and Ubuntu 24.04. Not yet: MIDI, and real decks on a physical network (WSL2's default networking does not see them). macOS is not supported.
