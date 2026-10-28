# djs1000-emu

[![release](https://img.shields.io/github/v/release/commit-collective/djs1000-emu?display_name=tag)](https://github.com/commit-collective/djs1000-emu/releases)

Run the Pioneer DJ DJS-1000's own application on your computer to develop
mods, automate regression checks and debug its UI without hardware.

<img src="https://commitcollective.cc/djs1000/emulator/hero.png" alt="The virtual deck, application screen and installed mod controls" width="1000">

A lightweight Linux backend runs the real ARM application under QEMU user
mode, with a shim for the missing hardware. Its screen is rendered off-screen
by default. The virtual deck is an optional frontend, not a requirement for
scripted use. Mods use the same USB `autoexec.bin` workflow as the unit.

## Requirements

- Your own **DJS1000.UPD, firmware 1.22**, and the device key.
  Neither is included. See [key and platform notes](docs/running.md).
- Linux, or Windows with WSL2 and Ubuntu 24.04.
- Python 3. The visible deck also needs pygame-ce and Pillow.

A Linux VM on a Mac is plausible but untested. This is not a native macOS
backend. See [the proposed Mac setup](docs/running.md#macos-untested).

## Quick start

Clone this repository or extract a [release](https://github.com/commit-collective/djs1000-emu/releases).
On Windows, run these first commands inside WSL Ubuntu. On Linux, use a terminal:

```sh
sudo apt install qemu-user-static binfmt-support squashfs-tools \
    p7zip-full gcc-arm-linux-gnueabihf gdb-multiarch python3 openssl xvfb
scripts/setup.sh /path/to/DJS1000.UPD /path/to/aes256.key
```

Setup writes to `~/djs`, outside the repository and on a Linux filesystem.
An existing installation requires `--rebuild`. Extraction is staged before
replacement, with old firmware files and settings retained in a backup folder.
USB and eMMC folders are not replaced. See [rebuild details](docs/running.md#rebuilding).

Then, on the computer where you want the visible deck, Windows itself or Linux:

```sh
python -m pip install -r requirements.txt
python start.py
```

The app reaches its project menu in about half a minute. Closing the virtual
deck stops the emulator. `start.cmd` and `start.sh` are shortcuts.
Use `python start.py --help` for options.

## Headless and agent-driven use

```sh
python start.py --no-deck
python start.py status
python start.py stop
```

The backend still renders the firmware UI, but no visible window is required
when Xvfb is installed. Scripts can press controls, inspect lamps, capture the
screen and record audio through the local TCP link.

```python
import sys
sys.path.insert(0, "tools")
from session import Session

s = Session()
s.wait_screen()
s.press((1, 3))  # HOME
s.shot("home.png")
```

See [scripted tools](docs/tools.md) and the [frontend protocol](docs/virtual-deck.md).
The protocol can change between versions.

## Try mods

1. Download a patch from the [mods installer](https://commitcollective.cc/djs1000/mods/).
2. Put `autoexec.bin` at the root of `~/djs/usb`, beside
   `PIONEER DJ SAMPLER`, not inside it. This folder is in WSL on Windows.
3. Restart the emulator. The startup script loads the patch as on the unit,
   including its application restart. Save your work first.

The deck displays installed mods from the package manifest.
Settings and logs remain in the USB folder. `DJS_USB` selects another folder.
Remove the patch and restart to run stock. Projects and saved settings remain.

## Scope and limits

The application supports project save/load, sample browsing, sequencing,
effects, LIVE SAMPLING, audio input and master/headphone output.
Pro DJ Link can be exercised with [deckbench](https://github.com/commit-collective/deckbench)
in the same Linux environment.

This is application emulation, not a full board or bootloader emulator.
Hardware audio timing, pressure-sensitive pads and MIDI are not reproduced.
Real decks require appropriate host networking, not WSL's default NAT.
Use hardware to validate what the emulator cannot establish.

## Documentation

- [Running, key, platform and rebuild notes](docs/running.md)
- [Emulation architecture](docs/emulation.md)
- [Virtual deck and controls](docs/virtual-deck.md)
- [Tools and regression workflow](docs/tools.md)
- [Panel protocol](docs/panel-protocol.md)
- [Reels](docs/reels.md), [releasing](docs/releasing.md)

## Support

[Report an emulator issue](https://github.com/commit-collective/djs1000-emu/issues/new?template=emulator.yml)
or [a mods issue](https://github.com/commit-collective/djs1000-emu/issues/new?template=mods.yml).
Include the version, OS, steps and relevant log. Do not attach firmware, keys,
dumps or vendor assets. Follow [Commit Collective](https://commitcollective.cc)
or watch releases here for updates.

## Credits and licence

Built on earlier reverse-engineering notes shared privately and Pioneer's
published GPL panel driver. The virtual deck's structure follows cdj-nxs2-qemu.

Independent project, not affiliated with Pioneer DJ or AlphaTheta. The deck
face is drawn by this project. The illustration includes the supplied
firmware's interface. Product names belong to their owners.

GPL-2.0-or-later. See [LICENSE](LICENSE).
