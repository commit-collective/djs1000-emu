#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Starts the DJS-1000: the emulator, then the virtual deck. Closing the deck
stops the emulator.

    python start.py [options] [deck options]      (start.cmd / start.sh do the same)
    python start.py stop                          stop a running emulator
    python start.py status                        say whether one is running

  --keep          leave the emulator running when the deck is closed
  --no-deck       start the emulator only (and leave it running)
  --window        show the app's own window too (it is hidden when Xvfb is
                  installed: the deck shows its screen)
  --distro NAME   the WSL distribution to run it in (default: $DJS_WSL_DISTRO,
                  else WSL's default one)
  --port N        the deck link's port (default 7310)
  --no-bench      do not start or attach to Deckbench (with a DJ adapter,
                  the one that watches it is left out too)
  --bench-url URL use an existing bench without starting or stopping it
  --network-picker choose a backend network adapter before starting
  --network NAME@IPv4 select an adapter/address, or default for local testing

Anything else goes to the deck (app/virtual_djs.py), whose options are listed
below (--help here prints them too).

On Windows the emulator runs in WSL (scripts/run.sh, set up once with
scripts/setup.sh) and the deck here. On Linux both run here. An emulator that
is already running is used as it is, and then left running. Its output goes
to $DJS_HOME/run/emulator.log (default ~/djs/run, in WSL on Windows).
"""
import os
import json
import shlex
import socket
import subprocess
import sys
import time
from app.bench import request as bench_request
from app.network_picker import query as network_query

REPO = os.path.dirname(os.path.abspath(__file__))
AUDIO_PORT = 7320                       # where deckbench serves its decks' sound (the deck's --input-tcp takes it)
WINDOWS = os.name == "nt"
# Several emulators can run at once, each in a slot (DJS_SLOT=N in the environment of whatever starts them, as the
# tests' runner does): the slot has a home of its own, ~/djs-sN (made from ~/djs the first time), a deck link port of
# its own (DJS_PORT, 7310 + N) and a tag, DJSDEV_TAG=sN, among the arguments of every one of its processes, by which
# it finds and ends its own and no other's. Without a slot there is one emulator, in ~/djs, on 7310.


# A shell function: the ids of the processes whose command line matches the pattern, and, for a slot, which carry its tag.
PIDS = r'''
pids_of() {
    for p in $(pgrep -f "$1"); do
        [ "$p" = "$$" ] && continue
        if [ -z "${DJSDEV_TAG:-}" ] || grep -qaP "DJSDEV_TAG=$DJSDEV_TAG\x00" "/proc/$p/environ" 2> /dev/null; then echo "$p"; fi
    done
}
'''


def bench_address(rows, environment):
    """An address of this computer on the chosen DJ adapter's network other than the emulator's, for its bench: a row
    of network_backend's list, the same adapter's first, or None. A bench on the emulator's own address would take
    what players send to that address (master hand-off, sync, status): a socket bound to the address gets it before
    the emulator's, bound to any."""
    import ipaddress
    try:
        network = ipaddress.IPv4Interface('%s/%s' % (environment['DJSDEV_ADDRESS'], environment['DJSDEV_NETMASK'])).network
    except (KeyError, ValueError):
        return None
    others = [row for row in rows if row.get('address') != environment['DJSDEV_ADDRESS']
              and row.get('broadcast') and ipaddress.IPv4Address(row['address']) in network]
    others.sort(key=lambda row: row.get('interface') != environment.get('DJSDEV_INTERFACE'))
    return others[0] if others else None


class Emulator:
    def __init__(self, distro, port, window=False, env=""):
        self.distro = distro
        self.port = port
        self.window = window
        self.manage_bench = True
        self.network = {}                # the chosen DJ adapter (DJSDEV_* values), empty for local testing
        self.bench_row = None            # another address of that network, for a bench that watches it (see bench_address)
        self.env = env                   # more environment for run.sh: "NAME=value ..."
        slot = os.environ.get("DJS_SLOT", "")
        self.tag = "s" + slot if slot != "" else ""
        if os.environ.get("DJS_PORT"):
            self.port = int(os.environ["DJS_PORT"])
        # What runs the guest (proot, or a chroot, see scripts/run.sh) shows the program in its command line. A slot's
        # processes are told from the others' by DJSDEV_TAG in their environment (every process of the guest has it).
        self.prelude = ('export DJS_HOME="$HOME/djs-%s" DJSDEV_TAG=%s\n' % (self.tag, self.tag)) if self.tag else ""
        self.prelude += PIDS
        self.running_cmd = '[ -n "$(pids_of EP113_Main_R)" ]'
        # The app, or the start-up before it (a stick's autoexec runs first).
        self.starting_cmd = '[ -n "$(pids_of "EP113_Main_R|/opt/djsemu/init.sh")" ]'
        if os.environ.get("DJS_PROOT"):
            self.env += " DJS_PROOT=1"       # proot in place of a chroot, see scripts/run.sh
        if os.environ.get("DJS_FAST_BOOT"):
            self.env += " DJSDEV_DIRECT=1"   # see scripts/guest/init.sh
        if os.environ.get("DJS_EMMC"):
            self.env += ' DJS_EMMC="%s"' % os.environ["DJS_EMMC"]   # the unit's internal storage: a folder in WSL, see scripts/run.sh
        self._repo = None

    def sh(self, script):
        """Runs a bash script where the emulator lives. (exit code, output)."""
        if WINDOWS:
            cmd = ["wsl.exe"] + (["-d", self.distro] if self.distro else []) + ["--", "bash", "-l", "-s"]
        else:
            cmd = ["bash", "-s"]
        try:
            p = subprocess.run(cmd, input=(self.prelude + script).encode(), stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT)
        except FileNotFoundError:
            sys.exit("wsl.exe not found: the emulator needs WSL2 (see README.md)" if WINDOWS
                     else "bash not found")
        return p.returncode, p.stdout.decode("utf-8", "replace").replace("\x00", "").strip()

    def repo(self):
        """This repository's path as the emulator's side sees it."""
        if self._repo is None:
            if WINDOWS:
                code, out = self.sh("wslpath -a '%s'" % REPO.replace("\\", "/"))
                if code or not out.startswith("/"):
                    sys.exit("WSL did not answer (%s). Is a distribution installed?" % (out or code))
                self._repo = out.splitlines()[-1]
            else:
                self._repo = REPO
        return self._repo

    def usb(self):
        """The USB folder as this side can open it (on Windows, a path into
        WSL), or None."""
        code, out = self.sh("""
%s
D="${DJS_USB:-${DJS_HOME:-$HOME/djs}/usb}"
[ -d "$D" ] || exit 1
%s
""" % ("export " + self.env if self.env else "", 'wslpath -w "$D"' if WINDOWS else 'echo "$D"'))
        return out.splitlines()[-1] if not code and out else None

    def modlist(self):
        """The list of mods of the patch on the USB drive (modlist.txt, in the folder the emulator opened the patch
        in) as this side can open it, or None if the patch has none."""
        code, out = self.sh("""
%s
F="${DJS_HOME:-$HOME/djs}/run/autoexec/modlist.txt"
[ -f "$F" ] || exit 1
%s
""" % ("export " + self.env if self.env else "", 'wslpath -w "$F"' if WINDOWS else 'echo "$F"'))
        return out.splitlines()[-1] if not code and out else None

    def deckbench(self):
        """Starts deckbench (Pro DJ Link decks: its repo is $DECKBENCH, else
        ../deckbench beside this one) in the emulator's network, if it is not
        running or is older than its source, and gives the address of its page.
        None if there is no deckbench, and `bench_why` then says why. The decks
        are off until the page switches them on."""
        here = os.environ.get("DECKBENCH") or os.path.join(os.path.dirname(REPO), "deckbench")
        self.bench_why = ""
        if not os.path.isfile(os.path.join(here, "deckbench", "cli.py")):
            self.bench_why = ("deckbench was not found at %s. Clone it beside this repository or set DECKBENCH to its "
                              "folder, and the unit will see simulated Pro DJ Link decks." % here)
            return None
        if WINDOWS:
            code, out = self.sh("wslpath -a '%s'" % here.replace("\\", "/"))
            if code or not out.startswith("/"):
                self.bench_why = "WSL could not find deckbench's folder (%s)." % (out or code)
                return None
            there = out.splitlines()[-1]
        else:
            there = here
        observe = ''
        if self.network.get('DJSDEV_INTERFACE'):         # a real link: a bench that only watches it, no simulated decks
            row = self.bench_row
            if not row:
                self.bench_why = ("a bench on the emulator's own address would take the players' messages to the DJS "
                                  "(master, sync, their status). Give the DJ adapter a second address on the same network "
                                  "for it (docs/running.md), or run one on another computer and add --bench-url.")
                return None
            observe = ' --observe ' + ' '.join(shlex.quote(str(row[key])) for key in ('address', 'netmask', 'broadcast'))
        code, out = self.sh('python3 %s ensure --repo %s --run "${DJS_HOME:-$HOME/djs}/run" --audio-port %d%s' %
                            (shlex.quote(self.repo() + '/tools/bench_process.py'), shlex.quote(there), AUDIO_PORT,
                             observe))
        if code or not out.startswith("http"):
            self.bench_why = out or "deckbench did not start (see deckbench.log in the emulator's run folder)."
            return None
        return out.splitlines()[-1]

    def network_command(self):
        code, home = self.sh('printf "%s\\n" "${DJS_HOME:-$HOME/djs}"')
        if code or not home.startswith('/'):
            raise ValueError('Could not locate the backend home for network settings')
        command = ['python3', self.repo() + '/tools/network_backend.py', '--home', home.splitlines()[-1]]
        return (['wsl.exe'] + (['-d', self.distro] if self.distro else []) + ['--'] + command) if WINDOWS else command

    def configure_network(self, command):
        environment = network_query(command, 'environment')        # every name, empty when none is chosen
        self.network = dict(environment)
        self.bench_row = None
        if environment.get('DJSDEV_INTERFACE'):
            try:
                self.bench_row = bench_address(network_query(command, 'list').get('interfaces', []), environment)
            except (OSError, ValueError, subprocess.SubprocessError):
                self.bench_row = None                                # no bench then, the emulator still starts
        self.env += ''.join(' %s=%s' % (key, shlex.quote(value)) for key, value in environment.items())
        return bool(environment.get('DJSDEV_INTERFACE'))

    def network_matches(self, command):
        code, pid = self.sh('pids_of EP113_Main_R | head -1')
        return not code and pid.isdecimal() and network_query(command, 'matches', pid)

    def running(self):
        return self.sh(self.running_cmd)[0] == 0

    def ensure_home(self):
        """The slot's home, made from ~/djs the first time (the unit's root file system and the key: 250 MB)."""
        if self.tag:
            self.sh("""
[ -x "$DJS_HOME/root/root/pdj/EP113_Main_R" ] && exit 0
mkdir -p "$DJS_HOME"
cp -a "$HOME/djs/aes256.key" "$DJS_HOME/" 2> /dev/null
if command -v rsync > /dev/null; then rsync -a "$HOME/djs/root/" "$DJS_HOME/root/"; else cp -a "$HOME/djs/root" "$DJS_HOME/"; fi
""")

    def stale(self):
        """Whether the running emulator started before the shim's source (or
        the script that builds it) last changed: it still has the old shim."""
        return self.sh("""
PID=$(pids_of EP113_Main_R | head -1)
[ -n "$PID" ] && { [ '%s/shim/djsdev.c' -nt "/proc/$PID" ] || [ '%s/shim/network.h' -nt "/proc/$PID" ] || [ '%s/scripts/run.sh' -nt "/proc/$PID" ]; }
""" % (self.repo(), self.repo(), self.repo()))[0] == 0

    def start(self):
        code, out = self.sh("""
RUN="${DJS_HOME:-$HOME/djs}/run"
mkdir -p "$RUN"
DJSDEV_PORT=%d DJS_WINDOW=%s %s setsid nohup bash '%s/scripts/run.sh' 0 > "$RUN/emulator.log" 2>&1 < /dev/null &
for i in $(seq 1 30); do sleep 0.5; %s && exit 0; done
tail -n 15 "$RUN/emulator.log"; exit 1
""" % (self.port, "1" if self.window else "", self.env, self.repo(), self.running_cmd))
        if code:
            sys.exit("the emulator did not start:\n" + out)

    def stop_bench(self):
        """Stops the bench this launcher started, if it runs (only that one)."""
        self.sh('python3 %s stop --run "${DJS_HOME:-$HOME/djs}/run"' % shlex.quote(self.repo() + '/tools/bench_process.py'))

    def stop(self):
        # A slot ends its own processes only (they carry its tag). The bench is the network tests', started by the
        # one that needs it.
        # A slot ends what carries its tag (everything of its guest, and what runs it). Without a slot, the app and
        # the guest's processes as before (the bench too).
        if self.manage_bench:
            self.sh('python3 %s stop --run "${DJS_HOME:-$HOME/djs}/run"' %
                    shlex.quote(self.repo() + '/tools/bench_process.py'))
        self.sh("""
if [ -n "${DJSDEV_TAG:-}" ]; then
    for i in 1 2 3; do
        for f in $(grep -laP "DJSDEV_TAG=$DJSDEV_TAG\\x00" /proc/[0-9]*/environ 2> /dev/null); do
            p=${f#/proc/}; p=${p%%/environ}
            [ "$p" = "$$" ] || kill -9 "$p" 2> /dev/null
        done
        sleep 0.3
    done
else
    kill $(pids_of EP113_Main_R) $(pids_of /opt/djsemu/init.sh) 2> /dev/null
    for i in 1 2 3 4 5 6 7 8 9 10; do %s || break; sleep 0.3; done
    kill -9 $(pids_of EP113_Main_R) 2> /dev/null
    pkill -9 -f 'qemu-arm-static.*libdjsdev.so'; pkill -9 -f 'qemu-binfmt/arm-binfmt'
fi
true
""" % self.running_cmd)

    def alive(self, seconds=6):
        """Whether the app is really running: its sound arrives on the deck
        link all the time, even when silent. A process can be there and the
        app be stuck (its own window was closed, say)."""
        try:
            sock = socket.create_connection(("127.0.0.1", self.port), timeout=2)
        except OSError:
            return False
        end = time.time() + seconds
        buf = b""
        try:
            while time.time() < end:
                sock.settimeout(max(0.1, end - time.time()))
                part = sock.recv(65536)
                if not part:
                    return False
                buf += part
                # Walk the messages: 'S' rows of the screen, 'L' lamps, 'A' sound.
                while len(buf) >= 8:
                    kind, rows, width = buf[0], buf[4] | buf[5] << 8, buf[6] | buf[7] << 8
                    frames = buf[2] | buf[3] << 8
                    if kind == ord("A"):
                        return True
                    need = 8 + (rows * width * 4 if kind == ord("S") else 128 if kind == ord("L")
                                else frames * 8)
                    if kind not in (ord("S"), ord("L")):
                        return False
                    if len(buf) < need:
                        break
                    buf = buf[need:]
        except OSError:
            pass
        finally:
            sock.close()
        return False

    def log_tail(self):
        return self.sh('tail -n 15 "${DJS_HOME:-$HOME/djs}/run/emulator.log"')[1]

    def wait(self, seconds=120):
        """Waits for the deck link to answer."""
        end = time.time() + seconds
        while time.time() < end:
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=1).close()
                return True
            except OSError:
                time.sleep(1)
                if self.sh(self.starting_cmd)[0]:
                    break
        return False


def take(args, name, default=None):
    """Removes `name VALUE` from args and returns VALUE."""
    if name in args:
        i = args.index(name)
        if i + 1 >= len(args):
            sys.exit(f"{name} needs a value")
        value = args[i + 1]
        del args[i:i + 2]
        return value
    return default


def flag(args, name):
    if name in args:
        args.remove(name)
        return True
    return False


def deck_help():
    """The deck's own help, after this one: what it takes is what start.py passes on."""
    deck = os.path.join(REPO, "app", "virtual_djs.py")
    run = subprocess.run([sys.executable, deck, "--help"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         env=dict(os.environ, PYGAME_HIDE_SUPPORT_PROMPT="1"))
    print("Deck options (python app/virtual_djs.py --help, the same):\n")
    if run.returncode:
        print("  (the deck needs pygame-ce and Pillow to say: %s -m pip install -r requirements.txt)" % os.path.basename(sys.executable))
    else:
        print(run.stdout.rstrip())


def main():
    args = sys.argv[1:]
    if "-h" in args or "--help" in args:
        print(__doc__)
        deck_help()
        return 0
    emu = Emulator(take(args, "--distro", os.environ.get("DJS_WSL_DISTRO")),
                   int(take(args, "--port", "7310")), flag(args, "--window"))
    keep, no_deck = flag(args, "--keep"), flag(args, "--no-deck")
    network_picker = flag(args, '--network-picker')
    network_choice = take(args, '--network')
    no_bench = flag(args, "--no-bench")
    bench_url = take(args, "--bench-url")
    if no_bench and bench_url is not None:
        sys.exit('--no-bench and --bench-url cannot be combined')
    legacy_bench = take(args, '--bench')
    if legacy_bench is not None:
        if no_bench or bench_url is not None:
            sys.exit('--bench cannot be combined with --no-bench or --bench-url')
        bench_url = legacy_bench
    if bench_url:
        try:
            bench_request(bench_url, 'api/state')
        except ValueError as error:
            sys.exit(str(error))
    if args[:1] == ["stop"]:
        was = emu.running()
        emu.stop()
        print("Emulator stopped." if was else "No emulator was running.")
        return 0
    if args[:1] == ["status"]:
        if not emu.running():
            print("The emulator is not running.")
        elif emu.alive():
            print("The emulator is running.")
        else:
            print("The emulator is running but not answering (start.py will restart it).")
        return 0
    if "--list-audio" in args:
        return subprocess.call([sys.executable, os.path.join(REPO, "app", "virtual_djs.py")] + args)
    emu.manage_bench = not no_bench and bench_url is None
    if not no_deck or network_picker:
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        try:
            import PIL  # noqa: F401
            import pygame  # noqa: F401
        except ImportError as e:
            sys.exit(f"the deck needs pygame-ce and Pillow ({e}):\n"
                     f"  {os.path.basename(sys.executable)} -m pip install -r requirements.txt")

    def say(text, end="\n"):
        print(text, end=end, flush=True)

    try:
        network_command = emu.network_command()
        if network_choice is not None:
            if network_choice == 'default':
                network_query(network_command, 'select')
            else:
                name, separator, address = network_choice.rpartition('@')
                if not separator:
                    sys.exit('--network needs NAME@IPv4 or default')
                network_query(network_command, 'select', name, address)
        if network_picker:
            from app.network_picker import choose
            if not choose(network_command):
                return 0
        physical_network = emu.configure_network(network_command)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        sys.exit(str(error))
    said = False
    if physical_network and emu.manage_bench:
        if emu.bench_row:
            say('DJ adapter chosen: the emulator joins your players. Its Deckbench only watches that network, from %s '
                '(a second address of the adapter), with no simulated decks. --no-bench leaves it out.'
                % emu.bench_row['address'])
        else:
            # A bench on the emulator's own address takes the players' messages meant for the DJS: none is started, and
            # one an earlier start left there is stopped
            emu.stop_bench()
            no_bench, emu.manage_bench, said = True, False, True
            say("DJ adapter chosen: the emulator joins your players, with no Deckbench of its own. On the emulator's "
                "address it would take the players' messages to the DJS (master, sync). Give the adapter a second address "
                'on the same network and the launcher starts one there (docs/running.md), or use --bench-url.')
    ours = not emu.running()
    if not ours and not emu.network_matches(network_command):
        sys.exit('Network selection changed. Save your project, run start.py stop, then start again.')
    if not ours and not emu.alive():
        say("An emulator is running but not answering. Restarting it.")
        emu.stop()
        ours = True
    elif not ours and emu.stale():
        say("The running emulator is older than its shim (shim/djsdev.c changed). Restarting it.")
        emu.stop()
        ours = True
    if ours:
        say("Starting the emulator...", end=" ")
        began = time.time()
        emu.start()
        if not emu.wait():
            print("failed")
            tail = emu.log_tail()
            emu.stop()
            sys.exit("The emulator did not answer on port %d. The end of its log:\n%s"
                     % (emu.port, tail))
        print("ready (%.0fs)." % (time.time() - began))
    else:
        say("Using the emulator that is already running.")
    if no_deck:
        say("Emulator left running. Stop it with: start.py stop")
        return 0
    say("Deck open. The app takes about half a minute to start. Close the deck to quit.")
    try:
        usb, modlist = emu.usb(), emu.modlist()
        bench = '' if no_bench else bench_url if bench_url is not None else emu.deckbench()
        if bench:
            say("Pro DJ Link decks (deckbench): %s" % bench)
        elif not said:                              # (why there is none with a DJ adapter was said above)
            say("No Deckbench, as asked: only real players on the network are seen." if no_bench or bench_url == '' else
                "No Deckbench: %s" % emu.bench_why)
        code = subprocess.call([sys.executable, os.path.join(REPO, "app", "virtual_djs.py"),
                                "--port", str(emu.port), "--bench", bench or '',
                                '--network-command', json.dumps(network_command)] + (["--usb", usb] if usb else [])
                                + (["--modlist", modlist] if modlist else []) + args)
    except KeyboardInterrupt:
        code = 130
    if ours and not keep:
        emu.stop()
        say("Deck closed. Emulator stopped.")
    else:
        say("Emulator left running. Stop it with: start.py stop")
    return code


if __name__ == "__main__":
    sys.exit(main())
