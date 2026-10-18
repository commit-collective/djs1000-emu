#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""A fixed session with the app, recorded, to see what a change changed.

    regress.py reference        run the session and keep it as the reference
    regress.py                  run it again and compare with the reference
    regress.py --patch FILE     the same, with FILE on the USB drive as
                                autoexec.bin: a patch, run as the unit runs it
    regress.py compare A B      compare two recorded sessions

The session starts an emulator of its own on a fresh unit (no settings, a USB
drive holding only the test kit), then: makes a project, loads three samples,
hits their pads, bends one with the strip, filters one with an effect, plays
a two-bar sequence, moves the tempo slider and saves the project. Along the
way it keeps screens (PNG) and sounds (WAV) in regress/<name>/, with
session.json listing them. Nothing of it is committed: the screens are the
firmware's.

A comparison passes a screen when under 0.02 % of its pixels differ (two
runs of one firmware come out identical; a changed number on the screen is
about 0.1 %), and a
sound when, lined up on their first loud sample, the two differ by less than
1 % RMS and end within 20 ms of each other. An emulator that is already
running is in the way: stop it first.

Run it on the host, like start.py. Needs Pillow.
"""
import json
import os
import struct
import sys
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)

import start  # noqa: E402
from session import RATE, Session, save_wav  # noqa: E402

BASE = os.path.join(REPO, "regress")
ENV = 'DJS_USB="$HOME/djs/regress/usb" DJS_DATA="$HOME/djs/regress/data"'

# Where things are on the app's screen and in the panel's frame.
OK = (487, 333)                          # the OK of a confirmation
TRACK = [(170 + 175 * (n % 4), 285 - 70 * (n // 4)) for n in range(16)]
HOME, PROJECT, FX, FX_ON, PLAY, STOP = (1, 3), (5, 5), (5, 7), (6, 7), (2, 3), (2, 2)
STEP = [(3 + n // 8, n % 8) for n in range(16)]
KEYS = {c: (67 + 66 * i, 351) for i, c in enumerate("qwertyuiop")}
KEYS.update({c: (99 + 66 * i, 395) for i, c in enumerate("asdfghjkl")})
SAVE_BUTTON = (487, 267)
HPF = (208, 125)


class Recorder:
    def __init__(self, s, out):
        self.s, self.out, self.items = s, out, []

    def screen(self, name):
        self.s.settle()
        self.s.shot(os.path.join(self.out, name + ".png"))
        self.items.append({"kind": "screen", "name": name})
        print("  screen", name)

    def sound(self, name, seconds, action):
        floats = self.s.record(seconds, action)
        save_wav(os.path.join(self.out, name + ".wav"), floats)
        peak = max((abs(v) for v in floats), default=0.0)
        self.items.append({"kind": "sound", "name": name, "peak": round(peak, 4)})
        print("  sound  %-14s peak %.2f" % (name, peak))

    def note(self, name, value):
        self.items.append({"kind": "note", "name": name, "value": value})
        print("  note   %-14s %s" % (name, value))


def load(s, track, turns, first=False):
    """Loads the sample `turns` rows from where the browser's cursor is on
    `track`. The first time, the cursor has to go down into the kit."""
    s.touch(*TRACK[track])               # selects the track (or opens its menu)
    s.press(HOME)
    s.push()                             # TRACK MENU, on BROWSE
    s.push()                             # BROWSE
    if first:
        s.turn(1)                        # Samples [USB]
        s.push()
        s.turn(1)                        # Test Kit
        s.push()
    s.turn(turns)
    s.push()
    s.pump(2.0)
    s.settle()
    s.press(HOME)


def scenario(s, r, emu):
    r.screen("01-project-menu")
    s.push()                             # CREATE NEW
    s.touch(*OK)
    r.screen("02-home-empty")
    load(s, 0, 3, first=True)            # Clap, Hat, Kick <- 3 down from the kit
    load(s, 1, 1)                        # Snare
    load(s, 2, -2)                       # Hat
    r.screen("03-home-kit")

    r.sound("pad-kick", 1.2, lambda: s.pad(0))
    r.sound("pad-snare", 1.0, lambda: s.pad(1))
    r.sound("pad-hat", 0.8, lambda: s.pad(2))

    s.send("strip 127")                  # PITCH mode: the top of the strip
    s.pump(0.3)
    r.sound("kick-pitch-up", 1.2, lambda: s.pad(0))
    s.send("strip -1")
    s.pump(0.3)

    s.send("word 0x5a 1023")             # FX LEVEL/DEPTH at MAX
    s.press(FX)
    s.touch(*HPF)
    r.screen("04-fx-hpf")
    s.press(HOME)
    s.press(FX_ON)
    r.sound("kick-hpf", 1.2, lambda: s.pad(0))
    s.press(FX_ON)

    # Kick on steps 1, 5, 9, snare on 5, hat on 9, nothing in the last
    # quarter of the bar: STOP, which cuts whatever still plays, comes close
    # to 400 ms after the last sound has ended and 500 ms before the next bar
    # would begin. The app's sound runs up to a few hundred ms ahead of the
    # clock STOP is sent by, differently from run to run.
    for track, steps in ((0, (0, 4, 8)), (1, (4,)), (2, (8,))):
        s.touch(*TRACK[track])
        s.press(HOME)
        for n in steps:
            s.press(STEP[n])
    r.screen("05-home-steps")

    def two_bars():                      # 4 s at 120 BPM; the last hat ends at 3.12 s
        s.tap(PLAY)                      # (not press(): the screen moves while it plays)
        s.pump(3.5)
        s.tap(STOP)

    r.sound("sequence", 5.5, two_bars)
    r.screen("06-home-stopped")

    s.send("word 0x58 1023")             # the tempo slider at its + end
    r.screen("07-tempo-plus")
    s.send("word 0x58 512")
    s.settle()

    s.press(PROJECT)
    s.turn(2)                            # SAVE
    s.push()
    for c in "reg":
        s.touch(*KEYS[c])
    r.screen("08-save-as")
    s.touch(*SAVE_BUTTON)
    s.pump(3.0)
    r.screen("09-saved")
    code, out = emu.sh('ls "$HOME/djs/regress/usb/PIONEER DJ SAMPLER/Projects/"')
    r.note("projects", out.split())


def wait_patch(emu, s, timeout=150):
    """A patch restarts the app once (the unit's own app is stopped, then started with the mods): the
    session begins on the app that has them."""
    end = time.time() + timeout
    while time.time() < end:
        code, out = emu.sh('grep -c "the app started with the mods" "${DJS_HOME:-$HOME/djs}/run/console.log"')
        if out.strip().splitlines()[-1:] not in (["0"], []):
            break
        s.pump(2.0)
    s.pump(3.0)
    s.wait_screen(quiet=1.5, timeout=60)
    s.wait_usb(timeout=60)


def run(name, patch=None):
    out = os.path.join(BASE, name)
    os.makedirs(out, exist_ok=True)
    for f in os.listdir(out):
        os.remove(os.path.join(out, f))
    emu = start.Emulator(os.environ.get("DJS_WSL_DISTRO"), 7310, env=ENV)
    if emu.running():
        sys.exit("An emulator is running: stop it first (start.py stop).")
    code, text = emu.sh('''
rm -rf "$HOME/djs/regress"; mkdir -p "$HOME/djs/regress/usb" "$HOME/djs/regress/data"
python3 '%s/tools/make_test_kit.py' "$HOME/djs/regress/usb/PIONEER DJ SAMPLER/Samples/Test Kit"
''' % emu.repo())
    if code:
        sys.exit("could not prepare the fresh unit:\n" + text)
    if patch:
        # The path is the host's; where the emulator lives it may read otherwise.
        code, text = emu.sh('''
P='%s'; command -v wslpath > /dev/null && P=$(wslpath -a "$P")
cp "$P" "$HOME/djs/regress/usb/autoexec.bin"
''' % os.path.abspath(patch).replace("\\", "/"))
        if code:
            sys.exit("could not put the patch on the drive:\n" + text)
    print("Recording the session '%s' on a fresh unit%s ..."
          % (name, " with the patch" if patch else ""))
    began = time.time()
    emu.start()
    try:
        if not emu.wait():
            sys.exit("the emulator did not answer:\n" + emu.log_tail())
        s = Session()
        if not s.wait_screen(quiet=1.5, timeout=120):
            sys.exit("the app never drew its first screen:\n" + emu.log_tail())
        if not s.wait_usb():
            sys.exit("the app never took the USB drive:\n" + emu.log_tail())
        if patch:
            wait_patch(emu, s)
        r = Recorder(s, out)
        scenario(s, r, emu)
        s.close()
    finally:
        emu.stop()
    with open(os.path.join(out, "session.json"), "w") as f:
        json.dump({"items": r.items, "seconds": round(time.time() - began)}, f, indent=1)
    print("Recorded in %s (%.0f s)." % (out, time.time() - began))
    return out


# ---- comparing -------------------------------------------------------------

def read_wav(path):
    with wave.open(path) as w:
        data = w.readframes(w.getnframes())
    v = struct.unpack("<%dh" % (len(data) // 2), data)
    return [(v[i] + v[i + 1]) / 65536.0 for i in range(0, len(v) - 1, 2)]   # mono


def bounds(v, level=0.01):
    """The first and the last sample louder than `level`, or None."""
    first = next((i for i, x in enumerate(v) if abs(x) > level), None)
    if first is None:
        return None
    last = next(i for i in range(len(v) - 1, -1, -1) if abs(v[i]) > level)
    return first, last


def compare_sound(a, b):
    """(passed, what was found) for two recordings of the same thing."""
    va, vb = read_wav(a), read_wav(b)
    ba, bb = bounds(va), bounds(vb)
    if ba is None or bb is None:
        return ba is None and bb is None, "both silent" if ba == bb else "one is silent"
    n = min(ba[1] - ba[0], bb[1] - bb[0]) + 1
    xa, xb = va[ba[0]:ba[0] + n], vb[bb[0]:bb[0] + n]
    rms = (sum(x * x for x in xa) / n) ** 0.5 or 1e-9
    diff = (sum((x - y) ** 2 for x, y in zip(xa, xb)) / n) ** 0.5 / rms
    ends = abs((ba[1] - ba[0]) - (bb[1] - bb[0])) / RATE
    ok = diff < 0.01 and ends < 0.02
    return ok, "differs by %.2f %% RMS, lengths %.0f ms apart" % (diff * 100, ends * 1000)


def compare_screen(a, b):
    from PIL import Image, ImageChops
    ia, ib = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
    if ia.size != ib.size:
        return False, "sizes differ"
    diff = ImageChops.difference(ia, ib).convert("L").point(lambda v: 255 if v > 16 else 0)
    share = sum(1 for v in diff.getdata() if v) / (ia.size[0] * ia.size[1])
    return share < 0.0002, "%.3f %% of the pixels differ" % (share * 100)


def compare(a, b):
    """Prints the comparison of two recorded sessions; True when all passed."""
    ja = json.load(open(os.path.join(a, "session.json")))["items"]
    jb = {i["name"]: i for i in json.load(open(os.path.join(b, "session.json")))["items"]}
    failed = 0
    print("Comparing %s with %s" % (os.path.basename(a), os.path.basename(b)))
    for item in ja:
        name, kind = item["name"], item["kind"]
        if name not in jb:
            ok, what = False, "missing from the second"
        elif kind == "screen":
            ok, what = compare_screen(os.path.join(a, name + ".png"), os.path.join(b, name + ".png"))
        elif kind == "sound":
            ok, what = compare_sound(os.path.join(a, name + ".wav"), os.path.join(b, name + ".wav"))
        else:
            ok = item["value"] == jb[name]["value"]
            what = "%s" % jb[name]["value"] if ok else "%s, was %s" % (jb[name]["value"], item["value"])
        failed += not ok
        print("  %-4s %-6s %-16s %s" % ("ok" if ok else "FAIL", kind, name, what))
    print("%d of %d differ." % (failed, len(ja)) if failed else "All %d the same." % len(ja))
    return not failed


def main():
    args = sys.argv[1:]
    if args[:1] == ["compare"] and len(args) == 3:
        return 0 if compare(args[1], args[2]) else 1
    if args[:1] == ["reference"]:
        run("reference")
        return 0
    patch = None
    if args[:1] == ["--patch"] and len(args) == 2:
        patch = args[1]
        if not os.path.isfile(patch):
            sys.exit("no such patch: " + patch)
    elif args:
        print(__doc__)
        return 2
    if not os.path.exists(os.path.join(BASE, "reference", "session.json")):
        sys.exit("There is no reference yet: regress.py reference")
    name = "patched" if patch else "latest"
    run(name, patch)
    return 0 if compare(os.path.join(BASE, "reference"), os.path.join(BASE, name)) else 1


if __name__ == "__main__":
    sys.exit(main())
