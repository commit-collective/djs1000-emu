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

The backend is Linux-specific. On a Mac it runs inside a Linux VM, where QEMU
user mode runs the ARM application as on any Linux. No Mac setup has been
validated here.

### Lima

[Lima](https://lima-vm.io) is the suggested VM. `scripts/lima/djs1000.yaml`
makes an Ubuntu 24.04 VM on the Mac's own architecture, with the packages setup
needs. It forwards the deck link (port 7310), Deckbench's audio (7320) and
Deckbench's page (8750) to the Mac's localhost. The template is not tried on a
Mac yet.

```sh
brew install lima
limactl start scripts/lima/djs1000.yaml
limactl copy /path/to/DJS1000.UPD djs1000:DJS1000.UPD
limactl copy /path/to/aes256.key djs1000:aes256.key
limactl shell djs1000
```

Then, inside the VM, from its home folder:

```sh
cd ~
git clone https://github.com/commit-collective/djs1000-emu.git
cd djs1000-emu
scripts/setup.sh ~/DJS1000.UPD ~/aes256.key && rm ~/aes256.key
python3 start.py --no-deck
python3 tools/shot.py home.png
```

Setup keeps its own copy of the key, so the one copied in can go. The emulator
and its files stay on the VM's own disk. The template shares no Mac folder.

On Apple Silicon, the VM cannot run 32-bit ARM code natively, and Ubuntu's arm64
packages leave out the handler that sends such programs to QEMU. The template
installs it. Without it, the programs the app launches would fail to start.

For the visible deck on the Mac, run it on its own rather than through the
launcher. The launcher would try to start a backend on the Mac itself.

```sh
python3 -m pip install -r requirements.txt
python3 app/virtual_djs.py
```

It connects to `127.0.0.1:7310`, which Lima forwards into the VM, and plays the
sound on the Mac's audio devices.

### OrbStack

An OrbStack Ubuntu machine should work the same way. Install the packages from
the template's provision script, the ARM handler included on Apple Silicon.
OrbStack forwards the VM's ports to the Mac's localhost by itself.

### Real players

By default both VMs sit behind NAT, which does not carry Pro DJ Link broadcasts
to the players. Lima can bridge the VM onto the Mac's network with
`socket_vmnet`, as its networking guide describes. Then uncomment the
`networks` lines at the end of the template. Run Deckbench and any Pro DJ Link
tests inside the VM, next to the emulator. Native macOS loopback broadcasts
differ from Linux.

### Reporting a try

This is an untested route, not evidence of incompatibility. If you try it,
open an issue with:

- the Mac's chip and macOS version, Lima or OrbStack and its version
- whether setup finished, and `python3 start.py status` inside the VM
- whether `tools/shot.py` gave a screenshot of the app
- whether the deck on the Mac connected, and whether its sound played
- with real players, how the VM was networked and whether they were seen

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

To give WSL the Windows adapters (mirrored networking):

1. Create or edit `%UserProfile%\.wslconfig` with:
   ```ini
   [wsl2]
   networkingMode=mirrored
   ```
2. Run `wsl --shutdown` in PowerShell. It stops everything running in WSL, so
   save your project first.
3. Allow inbound connections to WSL, in an administrator PowerShell. The ID is
   the one Windows' Hyper-V firewall gives WSL:
   ```powershell
   Set-NetFirewallHyperVVMSetting -Name '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' -DefaultInboundAction Allow
   ```
4. Start the emulator again. **Tools > Network adapter** now lists the Windows
   adapters, the DJ one included.

Mirrored mode lists the adapters. Pro DJ Link through it is not validated yet:
check that the players are seen. WSL and Windows then share their ports, so a
Windows program cannot listen on a port a WSL program already uses (Deckbench
on 8750 in both, for example). See Microsoft's
[WSL networking guide](https://learn.microsoft.com/en-us/windows/wsl/networking).

With a DJ adapter chosen, the launcher starts no Deckbench of its own: its
simulated decks live on the loopback, which the emulator no longer listens to,
and an extra device on the real link could change what is being tested. To
watch the network as well, run a Deckbench yourself in watching mode and point
the launcher at it:

```powershell
python -m deckbench --observe --dj-interface "Ethernet 2"
start.cmd --bench-url http://127.0.0.1:8750/
```

With mirrored networking, that Deckbench shares the emulated DJS's address on
the DJ network. Whether the players accept two devices at one address is not
checked yet.

Open **Tools > Network adapter** in the virtual deck and select a row, or
run `python start.py --network-picker` before starting. The picker lists
active IPv4 addresses visible to the Linux backend, including separate aliases.
It needs Linux `iproute2` (`sudo apt install iproute2`). It does not list native
Windows adapters unless WSL exposes them. Picking an adapter is not a WSL bridge.

The submenu saves on selection and marks the saved choice. Save your project
and stop/restart the emulator to apply it.
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
