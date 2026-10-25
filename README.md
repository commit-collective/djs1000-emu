# djs1000-emu

[![release](https://img.shields.io/github/v/release/commit-collective/djs1000-emu?display_name=tag)](https://github.com/commit-collective/djs1000-emu/releases)

The Pioneer DJ DJS-1000's own application, running on your computer.

<p align="center">
<img src="https://commitcollective.cc/djs1000/emulator/hero.png" alt="The virtual deck: the DJS-1000's face with five samples loaded, their pads lit and a pattern on the step keys, beside the app's screen at full size and the list of installed mods with a switch on each" width="1000">
</p>

Follow development: [commitcollective.cc](https://commitcollective.cc), [Instagram](https://www.instagram.com/commit.collective), [YouTube](https://www.youtube.com/@CommitCollective). On GitHub, Watch, then Releases.

## What it is

The DJS-1000 is Pioneer DJ's standalone performance sampler. This project runs the sampler's own software on your
computer and draws the machine around it in a window, the **virtual deck**: the screen, the lamps as the software lights
them, and every control under the mouse (pads, step keys, knobs, the rotary selector, the tempo slider, the touch
strip), with sound in and out.

It is for people who own a DJS-1000: to study how it works, to write and try modifications (such as
[the mods](https://commitcollective.cc/djs1000/mods/)) before putting them on the unit, and to test software that talks to
it. It is kept lightweight on purpose, to match the way mods reach the unit: it runs the same `autoexec.bin` from a USB folder as the unit does from a stick, so what you try here is what you put on the stick. How it does this is under [How it works](#how-it-works).

> [!CAUTION]
>
> ## What it is **not**
>
> - **It does not ship Pioneer DJ's firmware.** This repository holds no
>   firmware, nothing unpacked from it, no manuals and no key. You supply
>   your own copy of the public update file (`DJS1000.UPD`, v1.22) and of
>   the key that opens it. `scripts/setup.sh` unpacks the update on your
>   machine, outside the repository.
> - Not endorsed by, affiliated with, or sponsored by AlphaTheta Corporation
>   or Pioneer DJ. DJS-1000, Pioneer DJ, Pro DJ Link and rekordbox are
>   trademarks of their respective owners. The deck's face is drawn by this
>   project, without the maker's logo. The picture above shows the
>   firmware's own interface inside it, for illustration.
> - **Not a replacement for a DJS-1000.** It has no pressure-sensitive pads,
>   no real audio timing and no hardware.

## What you need

- **The update file**, `DJS1000.UPD` (version 1.22), the public update from the maker.
- **The key that opens it** (the update is encrypted): see [About the key](#about-the-key).
- **Linux, or Windows with WSL2** (Windows Subsystem for Linux) and Ubuntu 24.04 installed in it. macOS is not supported.
- **Python 3** on the computer you sit at (Windows itself, or the Linux machine), to run the deck.

## About the key

Pioneer DJ ships the update as an encrypted `.UPD` file. The key that
opens it is the text file `/usr/local/pdj/aes256.key` in the unit's own
root filesystem. It is Pioneer DJ's material, so it is not in this
repository, and no one here has the right to pass it on. Getting a copy
is up to you, by whatever means you are yourself entitled to, for
example from a unit you own. `setup.sh` keeps it as `~/djs/aes256.key`,
readable by you alone, for the tools that need it later.

## Quick start

The emulator itself runs in Linux. On Windows that is the Ubuntu terminal of WSL2: steps 2 and 3 go there, and the deck
(steps 4 and 5) is started from Windows itself. On Linux everything runs in one place. macOS is not supported: the
emulator needs Linux's `qemu-arm` user mode and Linux's chroot and namespaces, which a Mac would have to get from a
Linux virtual machine (a patch that does that is welcome).

1. **Get the code**: clone this repository (or download a [release](https://github.com/commit-collective/djs1000-emu/releases)).
   The commands below are run from its folder.

2. **Install what it runs on**, in Ubuntu 24.04 (`xvfb` is optional: without it the app's window opens on the X
   display, WSLg's on Windows):

   ```sh
   sudo apt install qemu-user-static binfmt-support squashfs-tools \
       p7zip-full gcc-arm-linux-gnueabihf gdb-multiarch python3 openssl xvfb
   ```

3. **Build the unit's root filesystem** from your update file and key, once. It goes in `~/djs/root`, on your machine,
   outside the repository:

   ```sh
   scripts/setup.sh /path/to/DJS1000.UPD /path/to/aes256.key
   ```

4. **Install the deck's two libraries** (pygame-ce and Pillow), once, on the computer you sit at (Windows itself, or the
   Linux machine):

   ```sh
   python -m pip install -r requirements.txt
   ```

5. **Run it**:

   ```sh
   python start.py
   ```

   (`start.cmd` on Windows and `./start.sh` on Linux do the same.)

That starts the emulator (in WSL on Windows), opens the virtual deck when it answers, and stops the emulator when the
deck is closed. The app is ready on its PROJECT menu about half a minute later. `python start.py --help` lists the
options. Anything it does not know goes to the deck (`--audio NAME`, `--headphones NAME`, `--no-input` ...).

The app runs in a chroot inside a user namespace of its own (`unshare -rm`), which needs no root. Where the
system does not allow user namespaces (some hardened kernels and containers), the launcher falls back to `proot`
(install it with `sudo apt install proot`), which is about three times slower to start the app. `DJS_PROOT=1` forces it.

## Trying the mods

The emulator treats a folder on your computer as the USB stick, and runs the `autoexec.bin` it finds in it the way the unit
does. So to try [the mods](https://commitcollective.cc/djs1000/mods/):

1. **Get an `autoexec.bin`**: download one from the mods page, or build one from the djs1000-mods project's source. It is
   encrypted with the unit's key, which the emulator already has: `setup.sh` kept it as `~/djs/aes256.key`.
2. **Put it at the top of the USB folder**, `~/djs/usb` (in WSL on Windows). It goes beside the `PIONEER DJ SAMPLER` folder
   and not inside it. From Windows that folder is `\\wsl.localhost\Ubuntu\home\<you>\djs\usb` (use your distribution's name),
   and `DJS_USB=/some/folder` points the emulator at another one. The folder is made the first time the emulator starts.
3. **Start the emulator again** (`python start.py stop`, then `python start.py`). The patch is opened when the emulator
   starts, as on a unit switched on with the stick in. The mods load about half a minute after the app does, and the app
   restarts once when they do.

The virtual deck then shows an "Installed mods (USB)" list beside the unit, with a switch for each mod, and a
`djs1000-mods.txt` appears in the USB folder with a line for each. A click on a switch rewrites its line, and the mods read the
file again as the app runs. `djs1000-mods.log` in the same folder says what the patch did, and a patch built for another
firmware than 1.22 leaves the app alone. To go back to the stock unit, take `autoexec.bin` out of the folder and start again.

## Scripted use

The emulator does not need the deck. `python start.py --no-deck` starts it alone and leaves it running, `python start.py status`
says whether it is, and `python start.py stop` ends it. A script then drives it and watches it, with no window:

- **Over TCP.** The emulator listens on `127.0.0.1:7310` (`--port`, or `DJSDEV_PORT`) and serves up to four clients at once, each
  sent everything: the screen, the lamps and the sound of the master and headphone outputs. A client sends one-line commands
  (`tap`, `bit`, `pad`, `enc`, `touch`, `word`, `strip`, `usb` ...) as the deck does. It is the protocol the virtual deck speaks, written down
  in [docs/virtual-deck.md](docs/virtual-deck.md) and [docs/tools.md](docs/tools.md). It is not a stable API, and it can change between versions.
- **From Python.** `tools/session.py` is a small client for it: press a button, hit a pad, touch the screen, wait for the screen to settle,
  take a screenshot, record what the outputs play.

  ```python
  import sys
  sys.path.insert(0, "tools")
  from session import Session

  s = Session()            # connects to 127.0.0.1:7310
  s.wait_screen()          # the app has drawn its first screen
  s.press((1, 3))          # HOME
  s.shot("home.png")
  ```

- **From a shell.** `python tools/shot.py home.png "tap 1 3"` sends commands to the emulator's panel pipe and saves a screenshot.

`tools/regress.py` (a fixed session compared with a reference), `tools/demo.py` and `tools/reel.py` (videos) are written this way.
The deck can run with no window too: with `SDL_VIDEODRIVER=dummy` and `--record` it records the video, as the Recording
section of [docs/virtual-deck.md](docs/virtual-deck.md) describes.

## What works

- the app starts in about half a minute and runs for as long as you leave it
- the virtual deck ([docs/virtual-deck.md](docs/virtual-deck.md)): every
  control of the panel (buttons, pads, step keys, knobs, the rotary selector,
  the tempo slider, the touch strip), every lamp, and the touch screen
- sound: the master and headphone outputs play on the computer's devices, and
  the input is fed from a recording device (LIVE SAMPLING works)
- a USB drive, which is the folder `~/djs/usb` (in WSL, on Windows): samples load from
  `PIONEER DJ SAMPLER/Samples` there, and projects are created, saved,
  opened, deleted, saved as packages and rendered to audio
- settings are kept from one run to the next
- `autoexec.bin` on the USB folder is run as the unit runs one from a stick,
  which is how modifications are tried here before a real unit
  ([docs/emulation.md](docs/emulation.md))
- Pro DJ Link: the unit announces itself as player 1 and sees the decks on its network, so SYNC and MASTER work and so do
  the mods that read the decks. The decks are simulated ones from deckbench, a separate project that `start.py` runs
  ([docs/virtual-deck.md](docs/virtual-deck.md))
- screenshots and scripted input, for exploring it without watching, and a
  recorded regression session (`tools/regress.py`) that comes out identical
  from one run to the next

**Not yet:** MIDI. Real decks on a physical network are not seen under WSL2's default networking (it needs mirrored
networking or a bridge). macOS.

## Other ways to run it

By hand, the two halves of `start.py` are `scripts/run.sh 3600` (the emulator, in WSL on Windows, and the number is the
seconds, 0 for no limit) and `python app/virtual_djs.py` (the deck, on the computer you sit at).

The app's own window is not shown: with `xvfb` installed the app draws on a display nobody sees, and the deck shows its
screen. `python start.py --window` (or `DJS_WINDOW=1 scripts/run.sh ...`) shows the app's window as well, and it takes
the keyboard without the deck:

| key | control |
|---|---|
| Escape / Backspace, H | BACK, HOME |
| Space, B, N | PLAY/PAUSE, STOP, REC |
| Enter, `,` / `.` | main encoder push / turn |
| F1–F6 (Shift: other direction) | the six knobs under the screen |
| P | PROJECT |
| 1–8, Q W E R T Y U I | step keys 1–16 |
| L, X, S, `-` | LIVE SAMPLING, FX, SYNC, TEMPO RANGE |
| mouse | touchscreen |

## How it works

The DJS-1000 is an embedded Linux machine (Freescale i.MX6). Its sampler is one program, `EP113_Main_R`, a JUCE
application that draws through X11. This project runs that program unmodified under `qemu-arm` user mode, inside the
unit's own root filesystem, with a small preloaded library standing in for the board's devices: the panel
microcontroller, the touch strip, GPIO, the backlight, the sound card. The virtual deck talks to that library. What has
been worked out is in [docs/](docs).

## Layout

| | |
|---|---|
| `shim/djsdev.c` | the stand-ins for the board's devices, and the keyboard, screenshot and command hooks |
| `start.py` (`start.cmd`, `start.sh`) | starts the emulator and the deck together |
| `app/` | the virtual deck |
| `scripts/setup.sh`, `scripts/run.sh` | builds the root filesystem from the update file, and runs the app |
| `scripts/guest/` | what runs inside the root filesystem in place of the unit's start-up |
| `tools/` | `decrypt_upd.py`, `shot.py` (screenshot), `probe.py` (find what an input does), `xref.py` (where a string is used), `make_test_kit.py` (a few synthetic drum samples on the USB folder), `session.py` and `regress.py` (a scripted, recorded session to compare firmware changes against), `deck_selftest.py` |
| `docs/` | what has been worked out: [the update file](docs/update-format.md), [hardware and software](docs/hardware.md), [the emulation](docs/emulation.md), [the panel protocol](docs/panel-protocol.md), [the virtual deck](docs/virtual-deck.md), [power and standby](docs/power-standby.md), [tools](docs/tools.md), [releasing](docs/releasing.md) |

## Reporting a problem

Bugs of the emulator and of the DJS-1000 mods are both reported in
[this repository's issues](https://github.com/commit-collective/djs1000-emu/issues/new/choose), with a form for each:
[an emulator bug](https://github.com/commit-collective/djs1000-emu/issues/new?template=emulator.yml) or [a mods bug](https://github.com/commit-collective/djs1000-emu/issues/new?template=mods.yml). Say what you did, what you saw, the version and where it
runs, and add the log if you can. Please attach nothing from Pioneer DJ: no firmware, no update file, no key.

## Credits

This builds on earlier reverse-engineering notes on the update file and the
unit's debug connectors, shared privately. The panel link follows Pioneer's
own driver, `subucom_spi.c`, from the GPL sources Pioneer DJ publishes for
the DJS-1000. The virtual deck's structure follows the one in
cdj-nxs2-qemu.

## Licence

GPL-2.0-or-later, see [LICENSE](LICENSE).
