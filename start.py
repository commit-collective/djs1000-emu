#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Starts the DJS-1000: the emulator, then the virtual deck; closing the deck
stops the emulator.

    python start.py [options] [deck options]      (start.cmd / start.sh do the same)
    python start.py stop                          stop a running emulator
    python start.py status                        say whether one is running

  --keep          leave the emulator running when the deck is closed
  --no-deck       start the emulator only (and leave it running)
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


class Emulator:
    def __init__(self, distro, port):
        self.distro = distro
        self.port = port
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

    def running(self):
        return self.sh(RUNNING)[0] == 0

    def start(self):
        code, out = self.sh("""
RUN="${DJS_HOME:-$HOME/djs}/run"
mkdir -p "$RUN"
DJSDEV_PORT=%d setsid nohup bash '%s/scripts/run.sh' 0 > "$RUN/emulator.log" 2>&1 < /dev/null &
sleep 2
%s || { tail -n 15 "$RUN/emulator.log"; exit 1; }
""" % (self.port, self.repo(), RUNNING))
        if code:
            sys.exit("the emulator did not start:\n" + out)

    def stop(self):
        self.sh("pkill -f 'qemu-arm-static.*EP113_Main_R'; pkill -f 'proot.*EP113_Main_R'; true")

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
                print(".", end="", flush=True)
                if not self.running():
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
                   int(take(args, "--port", "7310")))
    keep, no_deck = flag(args, "--keep"), flag(args, "--no-deck")
    if args[:1] == ["stop"]:
        emu.stop()
        print("stopped")
        return 0
    if args[:1] == ["status"]:
        print("running" if emu.running() else "not running")
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

    ours = not emu.running()
    if ours:
        print("starting the emulator ", end="", flush=True)
        emu.start()
    else:
        print("the emulator is already running ", end="", flush=True)
    if not emu.wait():
        print()
        tail = emu.log_tail()
        if ours:
            emu.stop()
        sys.exit("the emulator's deck link did not come up on port %d:\n%s" % (emu.port, tail))
    print(" up")
    if no_deck:
        return 0
    try:
        code = subprocess.call([sys.executable, os.path.join(REPO, "app", "virtual_djs.py"),
                                "--port", str(emu.port)] + args)
    except KeyboardInterrupt:
        code = 130
    if ours and not keep:
        emu.stop()
        print("emulator stopped")
    else:
        print("the emulator is left running (python start.py stop)")
    return code


if __name__ == "__main__":
    sys.exit(main())
