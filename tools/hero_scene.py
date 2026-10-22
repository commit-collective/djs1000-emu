#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Takes the picture of the deck that the hero picture is made from: a fresh unit with the test kit loaded, the first track's
kick on the beats, and the deck's window saved as a PNG.

    hero_scene.py [--patch autoexec.bin] [--out demo/hero/deck.png] [--hover MOD]

Starts an emulator of its own, like tools/demo.py (stop a running one first). The window is 2196x1800, so that the app's screen
is 800x480 in it. tools/hero.py cuts the picture up. Run on the host, like start.py. Nothing here is committed: the picture shows
the firmware's screen.
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "app"))

import demo  # noqa: E402
import regress  # noqa: E402
import start  # noqa: E402
from session import Session  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--patch", help="the djs1000-mods autoexec.bin: the list of mods")
    ap.add_argument("--out", default=os.path.join(REPO, "demo", "hero", "deck.png"))
    ap.add_argument("--hover", default="rec-length", help="the mod whose text shows under the list")
    args = ap.parse_args()
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    emu = start.Emulator(os.environ.get("DJS_WSL_DISTRO"), 7310, env=demo.ENV)
    if emu.running():
        sys.exit("An emulator is running: stop it first (start.py stop).")
    demo.prepare(emu, args.patch)
    emu.start()
    try:
        if not emu.wait():
            sys.exit("the emulator did not answer:\n" + emu.log_tail())
        s = Session()
        if not s.wait_screen(quiet=1.5, timeout=120):
            sys.exit("the app never drew its first screen")
        s.wait_usb()
        if args.patch:
            regress.wait_patch(emu, s)
        demo.load_kit(s)
        s.touch(*regress.TRACK[0])
        s.press(regress.HOME)
        for n in (0, 4, 8, 12):                      # the kick on the beats
            s.press(regress.STEP[n])
        s.settle()
        cmd = [sys.executable, os.path.join(REPO, "app", "virtual_djs.py"), "--port", str(emu.port), "--no-audio", "--no-input",
               "--width", "2196", "--height", "1800", "--snapshot", out, "--hover", args.hover]
        usb, modlist = emu.usb(), emu.modlist()
        if usb and args.patch:
            cmd += ["--usb", usb]
        if modlist and args.patch:
            cmd += ["--modlist", modlist]
        env = dict(os.environ, SDL_VIDEODRIVER="dummy", PYGAME_HIDE_SUPPORT_PROMPT="1")
        deck = subprocess.Popen(cmd, env=env)
        while deck.poll() is None:
            s.pump(0.2)
        print("wrote", out)
    finally:
        emu.stop()


if __name__ == "__main__":
    main()
