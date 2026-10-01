# djs1000-emu

The Pioneer DJ DJS-1000's own application, running on a PC.

The DJS-1000 is an embedded Linux machine (Freescale i.MX6). Its sampler is
one program, `EP113_Main_R`, a JUCE application that draws through X11. This
project runs that program unmodified under `qemu-arm` user mode, inside the
unit's own root filesystem, with a small preloaded library standing in for
the board's devices: the panel microcontroller, the codec link, GPIO, the
backlight, the sound card.

<p align="center">
<img src="docs/img/home.png" alt="The DJS-1000 main screen: 16 tracks, scene and pattern, BPM" width="400">
<img src="docs/img/track-menu.png" alt="The TRACK MENU screen of track 10" width="400">
</p>

## Nothing from Pioneer DJ is included

This repository holds no firmware, nothing unpacked from it, and no manuals.
You supply your own copy of the public update file (`DJS1000.UPD`, v1.22);
`scripts/setup.sh` unpacks it on your machine, outside the repository. The
screenshots show the firmware's own interface, for illustration. This project
is not affiliated with Pioneer DJ or AlphaTheta.

## State

Working:

- the app starts in about half a minute and runs for as long as you leave
  it, in a window
- its screen, touch (mouse), the main encoder and its push, the six knobs,
  the 16 step keys and the buttons found so far, from the keyboard
- projects: CREATE NEW, OPEN and SAVE on a USB drive, which is the folder
  `~/djs/usb`; samples load from `PIONEER DJ SAMPLER/Samples` there
- the pads play, and the master output sounds through the virtual deck
- a virtual deck: the machine's face in a window, with the app's screen and
  lamps and its controls under the mouse, see
  [docs/virtual-deck.md](docs/virtual-deck.md)
- screenshots and scripted input, for exploring it without watching

Not yet:

- the headphone output is not played, and the inputs read silence
- the analogue controls (tempo slider, touch strip, levels)
- MIDI, Pro DJ Link, the network

## Quick start

On Windows, in WSL2 (Ubuntu 24.04, with WSLg for the window); on Linux, any
X display.

```sh
sudo apt install qemu-user-static binfmt-support proot squashfs-tools \
    p7zip-full gcc-arm-linux-gnueabihf gdb-multiarch python3 openssl
scripts/setup.sh /path/to/DJS1000.UPD    # once: builds ~/djs/root
scripts/run.sh 3600                      # seconds; the window takes half a minute
```

The app starts on its PROJECT menu (P closes it). Then either run the
virtual deck on the host,

```sh
python -m pip install -r requirements.txt
python app/virtual_djs.py
```

or use the keyboard in the app's own window:

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

## Layout

| | |
|---|---|
| `shim/djsdev.c` | the stand-ins for the board's devices, and the keyboard, screenshot and command hooks |
| `app/` | the virtual deck |
| `scripts/setup.sh`, `scripts/run.sh` | update file → root filesystem; run the app |
| `tools/` | `decrypt_upd.py`, `shot.py` (screenshot), `probe.py` (find what an input does), `xref.py` (where a string is used) |
| `docs/` | what has been worked out: [the update file](docs/update-format.md), [hardware and software](docs/hardware.md), [the emulation](docs/emulation.md), [the panel protocol](docs/panel-protocol.md), [the virtual deck](docs/virtual-deck.md), [power and standby](docs/power-standby.md), [tools](docs/tools.md) |

## Credits

Earlier notes, shared privately, worked out the update file's encryption and the unit's debug
connectors ; this builds on them. The panel
link follows Pioneer's own driver, `subucom_spi.c`, from the GPL sources
Pioneer DJ publishes for the DJS-1000.

## Licence

GPL-2.0-or-later, see [LICENSE](LICENSE).
