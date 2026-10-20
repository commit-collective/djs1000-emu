#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Makes the demonstration video of the emulator: a script plays the unit and the virtual deck records it.

    demo.py [--patch autoexec.bin] [--out demo/demo.mp4] [--gif] [--height 880]

Starts an emulator of its own on a fresh unit with the test kit, then the deck with --record (window as video, master
output as sound, see app/capture.py), and drives the app through its scenes: the pads, the touch strip and an effect, a
pattern, the mods (with --patch, the djs1000-mods autoexec.bin: the list of mods, one switched off and on) and Pro DJ
Link (with deckbench beside this repository: a simulated deck, on, playing and the master). Captions come from the
scenes, burned in by ffmpeg, which also joins the sound. The video is real time: the app and the deck run as they would.

Run on the host, like start.py. Needs ffmpeg on PATH and Pillow and pygame-ce for the deck. Nothing here is committed:
the video shows the firmware's screen.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "app"))

import regress  # noqa: E402
import start  # noqa: E402
from session import Session  # noqa: E402

ENV = 'DJS_USB="${DJS_HOME:-$HOME/djs}/demo/usb" DJS_DATA="${DJS_HOME:-$HOME/djs}/demo/data"'
FONTS = ["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]


class Script:
    """The scenes' clock: captions are marked as the scenes begin, against the time the first frame was taken."""

    def __init__(self, s, began):
        self.s, self.began, self.marks, self.commands = s, began, [], None

    def now(self):
        return time.time() - self.began

    def caption(self, text):
        self.marks.append((self.now(), text))

    def wait(self, seconds):
        self.s.pump(seconds)

    def say(self, line):
        """A line for the deck (see app/capture.py)."""
        with open(self.commands, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def prepare(emu, patch):
    cmd = '''
D="${DJS_HOME:-$HOME/djs}/demo"
rm -rf "$D"; mkdir -p "$D/usb" "$D/data"
python3 '%s/tools/make_test_kit.py' "$D/usb/PIONEER DJ SAMPLER/Samples/Test Kit"
''' % emu.repo()
    if patch:
        cmd += '''P='%s'; command -v wslpath > /dev/null && P=$(wslpath -a "$P")
cp "$P" "$D/usb/autoexec.bin"
''' % os.path.abspath(patch).replace(chr(92), "/")
    code, text = emu.sh(cmd)
    if code:
        sys.exit("could not prepare the unit:\n" + text)


def load_kit(s):
    """Off camera: a new project with five samples on the first five tracks."""
    s.push()
    s.touch(*regress.OK)                 # CREATE NEW
    regress.load(s, 0, 3, first=True)    # Kick
    regress.load(s, 1, 1)                # Snare
    regress.load(s, 2, -2)               # Hat
    regress.load(s, 3, -1)               # Clap
    regress.load(s, 4, 4)                # Tone
    s.touch(*regress.TRACK[0])
    s.press(regress.HOME)
    s.settle()


def scene_pads(sc):
    s = sc.s
    sc.caption("Every pad, knob and key works")
    for n in (0, 1, 2, 0, 3, 4, 2, 1):
        s.pad(n, hold=0.2)
        sc.wait(0.45)
    sc.wait(0.5)


def scene_strip_and_fx(sc):
    s = sc.s
    sc.caption("The touch strip bends the pitch")
    s.send("strip 127")
    sc.wait(0.4)
    s.pad(0, hold=0.3)
    sc.wait(1.2)
    s.send("strip 20")
    sc.wait(0.4)
    s.pad(0, hold=0.3)
    sc.wait(1.2)
    s.send("strip -1")
    sc.wait(0.4)
    sc.caption("And the effects sound like the unit")
    s.send("word 0x5a 1023")
    s.press(regress.FX)
    sc.wait(0.5)
    s.touch(*regress.HPF)
    sc.wait(0.8)
    s.press(regress.HOME)
    s.press(regress.FX_ON)
    sc.wait(0.3)
    s.pad(0, hold=0.3)
    sc.wait(1.4)
    s.press(regress.FX_ON)
    sc.wait(0.4)


def scene_pattern(sc):
    s = sc.s
    sc.caption("Build a pattern and play it")
    for track, steps in ((0, (0, 4, 8, 12)), (1, (4, 12)), (2, (2, 6, 10, 14)), (3, (7, 15))):
        s.touch(*regress.TRACK[track])
        s.press(regress.HOME)
        for n in steps:
            s.press(regress.STEP[n])
            sc.wait(0.12)
    s.tap(regress.PLAY)
    sc.wait(8.0)
    s.tap(regress.STOP)
    sc.wait(0.6)


def scene_mods(sc):
    sc.caption("Mods, switched on and off while it runs")
    for mod in ("rec-quantize", "fx-chain", "tempo-ducker"):
        sc.say("hover " + mod)
        sc.wait(1.6)
    sc.say("toggle tempo-ducker")
    sc.wait(1.2)
    sc.say("toggle tempo-ducker")
    sc.wait(1.2)


def scene_prolink(sc, bench):
    def deck(what, n=2):
        req = urllib.request.Request("%sapi/deck/%d/%s" % (bench, n, what), method="POST")
        urllib.request.urlopen(req, timeout=5).read()

    sc.caption("Pro DJ Link, with simulated decks")
    for what in ("on", "play", "sync"):
        deck(what)
        sc.wait(1.4)
    deck("master")
    sc.wait(3.0)
    for what in ("master", "sync", "play", "on"):
        try:
            deck(what)
        except OSError:
            pass
    sc.wait(1.0)


def find_font():
    for path in FONTS:
        if os.path.exists(path):
            return path
    sys.exit("no bold font found for the captions: name one in FONTS")


def finish(video, final, marks, length, gif, work):
    """Captions burned in, the sound joined: the video file and, with --gif, a GIF of it."""
    font = os.path.join(work, "font.ttf")
    shutil.copyfile(find_font(), font)
    chain = []
    for i, (t, text) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else length
        name = "caption%d.txt" % i
        with open(os.path.join(work, name), "w", encoding="utf-8") as f:
            f.write(text)
        chain.append("drawtext=fontfile=font.ttf:textfile=%s:x=(w-text_w)/2:y=h-86:fontsize=34:fontcolor=white:"
                     "box=1:boxcolor=black@0.65:boxborderw=16:enable='between(t,%.2f,%.2f)'" % (name, t + 0.2, end - 0.2))
    video = os.path.abspath(video)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-f", "f32le", "-ar", "44100", "-ac", "2", "-i",
           video + ".f32", "-vf", ",".join(["scale=1920:-2"] + chain), "-af", "alimiter=limit=0.89:level=0", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart",
           os.path.abspath(final)]
    subprocess.check_call(cmd, cwd=work)
    if gif:
        out = os.path.splitext(os.path.abspath(final))[0] + ".gif"
        subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", "-i", os.path.abspath(final), "-vf",
                               "fps=12,scale=900:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];[b][p]paletteuse=dither=bayer",
                               out])
        print("wrote", out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--patch", help="the djs1000-mods autoexec.bin: the mods' list and its scene")
    ap.add_argument("--out", default=os.path.join(REPO, "demo", "demo.mp4"))
    ap.add_argument("--height", type=int, default=1100)
    ap.add_argument("--fps", type=int, default=25)
    ap.add_argument("--gif", action="store_true")
    ap.add_argument("--scenes", default="pads,strip,pattern,mods,prolink", help="the scenes to play, in order")
    args = ap.parse_args()
    out = os.path.abspath(args.out)
    work = os.path.join(os.path.dirname(out), "work")
    os.makedirs(work, exist_ok=True)
    raw = os.path.join(work, "raw.mp4")

    emu = start.Emulator(os.environ.get("DJS_WSL_DISTRO"), 7310, env=ENV)
    if emu.running():
        sys.exit("An emulator is running: stop it first (start.py stop).")
    prepare(emu, args.patch)
    emu.start()
    deck = None
    try:
        if not emu.wait():
            sys.exit("the emulator did not answer:\n" + emu.log_tail())
        bench = emu.deckbench() if "prolink" in args.scenes else None
        if "prolink" in args.scenes and not bench:
            print("No Pro DJ Link decks: %s" % emu.bench_why)
        s = Session()
        if not s.wait_screen(quiet=1.5, timeout=120):
            sys.exit("the app never drew its first screen")
        s.wait_usb()
        if args.patch:
            regress.wait_patch(emu, s)
        load_kit(s)

        cmd = [sys.executable, os.path.join(REPO, "app", "virtual_djs.py"), "--port", str(emu.port), "--no-audio",
               "--no-input", "--height", str(args.height), "--record", raw, "--fps", str(args.fps)]
        usb, modlist = emu.usb(), emu.modlist()
        if usb and args.patch:
            cmd += ["--usb", usb]
        if modlist and args.patch:
            cmd += ["--modlist", modlist]
        for suffix in (".start", ".stop", ".cmd", ".f32"):      # the files of an earlier take are not this one
            if os.path.exists(raw + suffix):
                os.remove(raw + suffix)
        env = dict(os.environ, SDL_VIDEODRIVER="dummy", PYGAME_HIDE_SUPPORT_PROMPT="1")
        deck = subprocess.Popen(cmd, env=env)
        end = time.time() + 40
        while not os.path.exists(raw + ".start") and time.time() < end:
            s.pump(0.2)
        if not os.path.exists(raw + ".start"):
            sys.exit("the deck did not start recording")
        time.sleep(0.3)
        sc = Script(s, float(open(raw + ".start").read()))
        sc.commands = raw + ".cmd"
        sc.caption("The DJS-1000's own app, on your computer")
        sc.wait(3.0)
        names = args.scenes.split(",")
        for name in names:
            if name == "pads":
                scene_pads(sc)
            elif name == "strip":
                scene_strip_and_fx(sc)
            elif name == "pattern":
                scene_pattern(sc)
            elif name == "mods" and args.patch:
                scene_mods(sc)
            elif name == "prolink" and bench:
                scene_prolink(sc, bench)
        sc.caption("djs1000-emu: bring your own firmware")
        sc.wait(3.0)
        length = sc.now()
        open(raw + ".stop", "w").close()
        deck.wait(timeout=60)
        deck = None
        finish(raw, out, sc.marks, length, args.gif, work)
        print("wrote", out, "(%.0f s)" % length)
    finally:
        if deck:
            deck.kill()
        emu.stop()


if __name__ == "__main__":
    main()
