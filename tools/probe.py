#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Find which panel inputs the running DJS-1000 app reacts to.

Sends each command to the djsdev panel pipe, takes a screenshot after it,
and reports the commands that changed the screen; those screenshots are
saved as PNGs in the given folder.

    probe.py <out-folder> [command ...]

Without commands: every button bit (bytes 1-6), then each encoder +4/-4.
"""
import hashlib
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shot  # noqa: E402


def grab():
    if os.path.exists(shot.RAW):
        os.remove(shot.RAW)
    shot.send("shot")
    for _ in range(100):
        if os.path.exists(shot.RAW):
            time.sleep(0.05)
            return open(shot.RAW, "rb").read()
        time.sleep(0.1)
    sys.exit("no screenshot: is the app running?")


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    cmds = sys.argv[2:] or (["tap %d %d" % (by, bi) for by in range(1, 7) for bi in range(8)]
                            + ["enc %d %d" % (n, d) for n in range(7) for d in (4, -4)])
    import struct
    # PROBE_RESET: a command sent after every change to get back to a known
    # screen (e.g. "tap 5 5" = HOME), so each input is tried from there.
    reset = os.environ.get("PROBE_RESET")
    prev = hashlib.md5(grab()).hexdigest()
    for cmd in cmds:
        shot.send(cmd)
        time.sleep(1.2)
        d = grab()
        h = hashlib.md5(d).hexdigest()
        if h != prev:
            w, hh = struct.unpack_from("<II", d, 4)
            name = os.path.join(out, cmd.replace(" ", "_").replace("-", "m") + ".png")
            shot.png(name, w, hh, d[12:])
            print("CHANGED  %-12s -> %s" % (cmd, os.path.basename(name)), flush=True)
            if reset:
                shot.send(reset)
                time.sleep(1.5)
                h = hashlib.md5(grab()).hexdigest()
            prev = h
        else:
            print("same     %s" % cmd, flush=True)


if __name__ == "__main__":
    main()
