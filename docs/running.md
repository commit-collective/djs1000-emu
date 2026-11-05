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

### Real players and an existing Deckbench

The default launcher starts a local Deckbench with its simulated players off.
For a real DJ setup, choose explicitly:

```sh
python start.py --no-bench
python start.py --bench-url http://127.0.0.1:8750/
```

The first runs without a bench connection in the frontend. The second attaches
its status button and browser link to a bench you manage separately, without
starting or stopping it. Neither command bridges a network or changes adapters.
For a token-protected bench, use its backend URL with `#token=...`, inside
quotes. The frontend sends that token as an authorization header to the API.
An already-running launcher-owned local bench is not stopped by these flags.
Stop that local session first if you no longer need it.

The emulator and Deckbench must both reach the players' Ethernet segment.
On Windows, the emulator's backend lives in WSL, even though its window is on
Windows. A Windows Deckbench seeing the CDJs does not prove that WSL can see
them. Default WSL NAT does not carry the necessary LAN broadcasts. Configure
and verify a suitable mirrored or bridged network before hardware testing.
Open **Tools > Network adapter (restart required)** in the virtual deck, or
run `python start.py --network-picker` before starting. The picker lists
active IPv4 addresses visible to the Linux backend, including separate aliases.
It needs Linux `iproute2` (`sudo apt install iproute2`). It does not list native
Windows adapters unless WSL exposes them. Picking an adapter is not a WSL bridge.

Save the choice, save your project and stop/restart the emulator to apply it.
The launcher refuses to reuse a running backend with a different selection.
For scripted use, run `python start.py --network eth1@169.254.10.5`, substituting
an existing backend interface and address. `--network default` restores the
previous local-test networking. Choices live in `$DJS_HOME/network.json`, not
the repository. A missing saved adapter must be replaced or reset explicitly.

Explicit selection maps the app's Ethernet identity to that adapter, sends
Link UDP from its selected IP and uses its subnet broadcast address. The
packet-socket stand-in ignores sources outside that subnet. This is not an
OS-level network sandbox. No interface addressing, routes or firewall rules
are changed. A selected physical adapter disables automatic loopback Deckbench
startup. Use `--bench-url` to attach to a separately managed bench on that
network. An older local bench already running is left alone.

These paths have firmware-free Linux identity and UDP source-routing checks.
Real-player discovery and timing through a selected Linux/WSL adapter still
need hardware validation. Do not assume Windows adapter visibility or VM
broadcast reachability merely because the frontend can open the picker.

Give every player, real or simulated, an unused player number. Avoid running
two benches on the same ports, and keep all simulated players off until needed.
The emulator also needs an IP identity distinct from each real or simulated
player. On a shared host, configure separate existing IPv4 aliases before
selecting them. The picker does not create aliases for you.
Deckbench's adapter selection applies only to its own process, not the emulator.
Real players can provide discovery, tempo and beat messages, but Pro DJ Link
does not provide their audio to the emulator. Feed a physical audio interface
to the frontend's input separately if testing live sampling or audio effects.

The launcher stops only the local bench it recorded as its own. It does not
adopt or terminate a separately launched bench occupying port 8750. Stop a
legacy local bench manually after checking its identity if upgrading from a
launcher that did not record ownership.

`scripts/run.sh 3600` runs the backend for an hour. Use 0 for no time limit.
`python app/virtual_djs.py` opens a frontend separately.

`python start.py --window` also shows the firmware's X window. Its keyboard
shortcuts and the TCP control protocol are in [virtual-deck.md](virtual-deck.md)
and [tools.md](tools.md). Stop through the launcher rather than closing the
firmware's own window.
