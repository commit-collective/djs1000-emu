#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Starts the DJS-1000: the emulator, then the virtual deck; closing the deck
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

Anything else goes to the deck (app/virtual_djs.py): --audio NAME,
--headphones NAME, --input NAME, --no-input, --listen phones, --list-audio ...

On Windows the emulator runs in WSL (scripts/run.sh, set up once with
scripts/setup.sh) and the deck here; on Linux both run here. An emulator that
is already running is used as it is, and then left running. Its output goes
to $DJS_HOME/run/emulator.log (default ~/djs/run, in WSL on Windows).
"""
import os
import socket
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.abspath(__file__))
WINDOWS = os.name == "nt"
RUNNING = "pgrep -f 'qemu-arm-static.*EP113_Main_R' > /dev/null"
# The app, or the start-up before it (a stick's autoexec runs first).
STARTING = "pgrep -f 'qemu-arm-static.*(EP113_Main_R|/opt/djsemu/init.sh)' > /dev/null"


class Emulator:
    def __init__(self, distro, port, window=False, env=""):
        self.distro = distro
        self.port = port
        self.window = window
        self.env = env                   # more environment for run.sh: "NAME=value ..."
        self._repo = None

    def sh(self, script):
        """Runs a bash script where the emulator lives; (exit code, output)."""
        if WINDOWS:
            cmd = ["wsl.exe"] + (["-d", self.distro] if self.distro else []) + ["--", "bash", "-l", "-s"]
        else:
            cmd = ["bash", "-s"]
        try:
            p = subprocess.run(cmd, input=script.encode(), stdout=subprocess.PIPE,
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
        running or is older than its source, and gives the address of its page;
        None if there is no deckbench. The decks are off until the page
        switches them on."""
        here = os.environ.get("DECKBENCH") or os.path.join(os.path.dirname(REPO), "deckbench")
        if not os.path.isfile(os.path.join(here, "deckbench", "cli.py")):
            return None
        if WINDOWS:
            code, out = self.sh("wslpath -a '%s'" % here.replace("\\", "/"))
            if code or not out.startswith("/"):
                return None
            there = out.splitlines()[-1]
        else:
            there = here
        code, out = self.sh("""
RUN="${DJS_HOME:-$HOME/djs}/run"
mkdir -p "$RUN"
B='%s'
# A bench older than its source (it was changed since) is a stale one: replaced.
PID=$(pgrep -f '[d]eckbench --numbers' | head -1)
if [ -n "$PID" ] && [ -n "$(find "$B/deckbench" -name '*.py' -newer "/proc/$PID" | head -1)" ]; then
    pkill -f '[d]eckbench --numbers'
    sleep 0.5
fi
if ! pgrep -f '[d]eckbench --numbers' > /dev/null; then
    cd "$B" && setsid nohup python3 -m deckbench --numbers 1,2,3,4 > "$RUN/deckbench.log" 2>&1 < /dev/null &
    sleep 1
fi
pgrep -f '[d]eckbench --numbers' > /dev/null && echo http://localhost:8750/
""" % there)
        return out.splitlines()[-1] if not code and out.startswith("http") else None

    def running(self):
        return self.sh(RUNNING)[0] == 0

    def stale(self):
        """Whether the running emulator started before the shim's source (or
        the script that builds it) last changed: it still has the old shim."""
        return self.sh("""
PID=$(pgrep -f 'qemu-arm-static.*EP113_Main_R' | head -1)
[ -n "$PID" ] && { [ '%s/shim/djsdev.c' -nt "/proc/$PID" ] || [ '%s/scripts/run.sh' -nt "/proc/$PID" ]; }
""" % (self.repo(), self.repo()))[0] == 0

    def start(self):
        code, out = self.sh("""
RUN="${DJS_HOME:-$HOME/djs}/run"
mkdir -p "$RUN"
DJSDEV_PORT=%d DJS_WINDOW=%s %s setsid nohup bash '%s/scripts/run.sh' 0 > "$RUN/emulator.log" 2>&1 < /dev/null &
for i in $(seq 1 30); do sleep 0.5; %s && exit 0; done
tail -n 15 "$RUN/emulator.log"; exit 1
""" % (self.port, "1" if self.window else "", self.env, self.repo(), RUNNING))
        if code:
            sys.exit("the emulator did not start:\n" + out)

    def stop(self):
        self.sh("""
pkill -f '[d]eckbench --numbers'
pkill -f 'qemu-arm-static.*EP113_Main_R'; pkill -f 'qemu-arm-static.*/opt/djsemu/init.sh'
for i in 1 2 3 4 5 6 7 8 9 10; do %s || break; sleep 0.3; done
pkill -9 -f 'qemu-arm-static.*EP113_Main_R'; pkill -f 'proot -q qemu-arm-static.*djsemu'
# Whatever else runs in the guest (a stick's autoexec may leave something).
pkill -9 -f 'qemu-arm-static.*libdjsdev.so'; true
""" % RUNNING)

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
                if self.sh(STARTING)[0]:
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


def main():
    args = sys.argv[1:]
    if "-h" in args or "--help" in args:
        print(__doc__)
        return 0
    emu = Emulator(take(args, "--distro", os.environ.get("DJS_WSL_DISTRO")),
                   int(take(args, "--port", "7310")), flag(args, "--window"))
    keep, no_deck = flag(args, "--keep"), flag(args, "--no-deck")
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
    if not no_deck:
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        try:
            import PIL  # noqa: F401
            import pygame  # noqa: F401
        except ImportError as e:
            sys.exit(f"the deck needs pygame-ce and Pillow ({e}):\n"
                     f"  {os.path.basename(sys.executable)} -m pip install -r requirements.txt")

    def say(text, end="\n"):
        print(text, end=end, flush=True)

    ours = not emu.running()
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
        usb, bench, modlist = emu.usb(), emu.deckbench(), emu.modlist()
        if bench:
            say("Pro DJ Link decks (deckbench): %s" % bench)
        code = subprocess.call([sys.executable, os.path.join(REPO, "app", "virtual_djs.py"),
                                "--port", str(emu.port)] + (["--usb", usb] if usb else [])
                                + (["--modlist", modlist] if modlist else []) + args)
    except KeyboardInterrupt:
        code = 130
    if ours and not keep:
        emu.stop()
        say("Emulator stopped.")
    else:
        say("Emulator left running. Stop it with: start.py stop")
    return code


if __name__ == "__main__":
    sys.exit(main())
