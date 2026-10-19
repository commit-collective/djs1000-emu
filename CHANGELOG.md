# Changelog

Newest first. A release is a tagged commit.

## Not yet released

## v0.1.0

First release.

- The DJS-1000's own app (firmware 1.22) runs unmodified under `qemu-arm` user mode, in the unit's root filesystem,
  with stand-ins for its devices: the panel, the touch strip, the backlight, the sound card.
- A virtual deck draws the machine: the screen, every lamp, every control (buttons, pads, step keys, knobs, rotary
  selector, tempo slider, touch strip), with the master and headphone outputs and a recording device as the input.
- A USB drive is a host folder: samples load from it, and projects are saved, opened, deleted and rendered there.
- An `autoexec.bin` on that folder runs as it does on a stick, which is how the mods are tried before a real unit.
- Several emulators can run side by side. The guest runs in a chroot inside a user namespace (no root; `proot` is the
  fallback and is about three times slower to start the app), and each emulator's processes are told apart by their
  mount namespace.
- `tools/regress.py` records a fixed session and compares it with a reference; `tools/session.py` scripts the app.
- The deck lists the mods of the patch on the drive, grouped as the mods' website groups them, with a switch for each; the
  mouse on a row shows the mod's text.
- Settings of the mods are read from `djs1000-mods.txt` on the drive.

Tried on Windows 11 with WSL2 and Ubuntu 24.04. Not yet: MIDI, Pro DJ Link, the network. macOS is not supported.
