# Running the emulator

## Your firmware and key

Supply your own firmware 1.22 update and the key needed to open it.
The unit stores its key on its own system. Obtain it only by means you are
entitled to use, for example from a unit you own. Do not share
it in issues or commits. This project does not distribute it.

Setup keeps a private-readable copy at `$DJS_HOME/aes256.key`.
`DJS_HOME` defaults to `~/djs`. The firmware root and working data stay there,
outside the checkout. Use a Linux filesystem, not a Windows shared folder.

## Linux and Windows

The backend needs Linux, QEMU ARM user-mode, a cross compiler and X11.
Install Xvfb for off-screen rendering. Without it the app needs a visible
X display. Follow the commands in the [README](../README.md#quick-start).

On Windows, setup and the backend run inside WSL2. The Python virtual deck
runs on Windows and uses its audio devices. From Windows the default USB
folder is `\\wsl.localhost\Ubuntu\home\<you>\djs\usb`. Substitute your
distribution name. On Linux, both parts run on the same machine.

The backend uses an unprivileged user namespace and chroot. If the kernel
disallows that, install `proot` for the slower fallback. `DJS_PROOT=1` forces
it. Running as root should not be necessary.

## macOS, untested

The backend is Linux-specific, but QEMU user-mode can run the ARM application
inside an ARM64 or x86-64 Linux VM. Ubuntu in Lima or OrbStack is a plausible
route on either Apple Silicon or Intel. No Mac setup has been validated here.

For the first attempt, run setup, the backend and Python tools **inside the
Linux VM**, on its native filesystem. With Xvfb, no VM desktop is needed.
Run `python start.py --no-deck` there and confirm scripted screenshots and
audio before attempting a native Mac frontend.

The current launcher treats non-Windows hosts as local Linux. It does not
automatically start or manage a Mac VM. A deck running on macOS needs the
backend's TCP port forwarded to it and the matching connection options.
Check forwarding, audio devices and VM filesystem permissions separately.
Pro DJ Link tests should run inside the same VM as the emulator because
native macOS loopback broadcasts differ from Linux.

This is an untested route, not evidence of incompatibility. Report the VM,
guest architecture, package versions and what worked if you try it.

## Rebuilding

Setup refuses a nonempty destination unless `--rebuild` is explicit and the
folder is a recognised installation. It rejects home and repository roots.
It extracts into a temporary workspace first. Unexpected archive errors stop
setup before replacing the current root.

```sh
scripts/setup.sh --rebuild /path/to/DJS1000.UPD
```

Successful replacement keeps the previous `root`, `iso` and `update.iso` under
a printed `previous.*` folder. Settings inside the old root stay in that
backup, they are not automatically merged into the new root. USB and eMMC
folders remain in place. Failed extraction leaves its workspace for diagnosis.
Inspect backups before removing any of them.

## Manual launch

`scripts/run.sh 3600` runs the backend for an hour. Use 0 for no time limit.
`python app/virtual_djs.py` opens a frontend separately.

`python start.py --window` also shows the firmware's X window. Its keyboard
shortcuts and the TCP control protocol are in [virtual-deck.md](virtual-deck.md)
and [tools.md](tools.md). Stop through the launcher rather than closing the
firmware's own window.
