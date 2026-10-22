#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Makes a short vertical video (a reel) of the emulator: a script plays the unit and the virtual deck records it.

    reel.py EPISODE [--patch autoexec.bin] [--out DIR] [--fps 30] [--top screen|device] [--no-link]

EPISODE is a file in tools/reels (emulator_intro for tools/reels/emulator_intro.py): its scenes, the text of each and what is played
in it. The unit starts on a fresh set of internal storage (a copy of the factory one made of hard links, see DJS_EMMC_SRC), the
episode's project is opened, and the deck records (as tools/demo.py does: the window as video, the master output as sound). The
window is then cut up and stacked into 1080x1920, a layout for each scene (the screen of the app above, the panel below, or the
list of mods), and written in DIR/NAME/ (DIR is --out, else demo/reels in this repository, which git ignores like the rest of demo/):

    reel-clean-LOOK.mp4   the picture and the sound, no text: for editing (LOOK is the top of the picture, screen or device)
    reel-LOOK.mp4         the same with the text of the scenes burned in
    reel.srt              the text of the scenes, for a subtitle track
    thumb-LOOK.png        a frame, for a cover

Run on the host, like start.py. Needs ffmpeg on PATH, Pillow and pygame-ce for the deck, and a copy of the unit's internal storage
in WSL (default ~/djs/emmc-src, with PIONEER DJ SAMPLER in it, see docs/emulation.md). Nothing here is committed: the video shows
the firmware's screen and the unit's factory content.
"""
import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "app"))

import demo  # noqa: E402
import regress  # noqa: E402
import start  # noqa: E402
from session import ORIGIN, Session  # noqa: E402

ENV = ('DJS_USB="${DJS_HOME:-$HOME/djs}/reel/usb" DJS_DATA="${DJS_HOME:-$HOME/djs}/reel/data" '
       'DJS_EMMC="${DJS_HOME:-$HOME/djs}/reel/emmc"')
W, H = 1080, 1920
DECK_W, DECK_H = 2196, 1800       # the deck's window: the regions below are measured on it (the app's screen is 800x480 in it)
TOP, FOOT = 190, 96               # the band for the caption above the picture and the one for the small text below it

# Regions of the deck's window (x, y, w, h) and where they go on the 1080x1920 picture.
SCREEN = (1380, 16, 798, 478)                # the app's screen (the big one beside the face, inside its border): 800x480 less its last
#                                              column and row, which the frame has in light grey (210) and no other edge does (and
#                                              less one more, for the crop is an even number of pixels)
PANEL = (0, 486, 1360, 1270)                 # the face below the bezel of its small screen: knobs, pads, strip, fader, step buttons
DEVICE = (0, 20, 1360, 1740)                 # the whole face, the bezel of the small screen at its top
LINE = "0x3a3c42"                            # the thin line around a card
MARGIN, GAP = 24, 22                         # the picture's side margin, and the space between the two cards
CARD = 1080 - 2 * MARGIN                     # a card's width
SCREEN_H = int(round(SCREEN[3] * CARD / float(SCREEN[2])))
PANEL_H = int(round(PANEL[3] * CARD / float(PANEL[2])))
SCREEN_AT = (MARGIN, TOP, CARD, SCREEN_H)
PANEL_AT = (MARGIN, TOP + SCREEN_H + GAP, CARD, PANEL_H)
# The top of the picture is a setting (--top, or TOP in the episode). In both, the unit does not move when the list of mods comes
# up: the two kinds of scene have one layout, and the deck itself shows the list as a page of the unit (the `page mods` command of
# the recording, see app/virtual_djs.py).
#   screen  two framed cards: the app's big screen, and the face under its bezel. The page of mods is in the big screen.
#   device  the unit as it is, its top and its small screen kept. The page of mods is in its small screen.
LAYOUTS = {
    "play": [(SCREEN, SCREEN_AT), ("box", SCREEN_AT), (PANEL, PANEL_AT), ("box", PANEL_AT)],
    "play-device": [(DEVICE, (0, TOP + 126, 1080, 1382))],
    "end": [],
}


def layout_named(name, top):
    """The layout a scene asks for, in the setting for the top of the picture. Every scene but the end card has the one layout of
    the setting (a scene's name, play or mods, is for the episode's own use): the unit does not move between them."""
    if name == "end":
        return "end"
    return "play" if top == "screen" else "play-device"


class Timeline:
    """What the scenes say as they play: the layout from a time on, and the text (a caption above, a line below)."""

    def __init__(self, script):
        self.script = script
        self.layouts = []            # (t, name)
        self.cues = []               # (t, caption, sub)

    def now(self):
        return self.script.now()

    def layout(self, name):
        self.layouts.append((self.now(), name))

    def text(self, caption="", sub=""):
        self.cues.append((self.now(), caption, sub))

    def wait(self, seconds):
        self.script.wait(seconds)

    def say(self, line):
        self.script.say(line)


class Context:
    """What an episode's scenes work with."""

    def __init__(self, s, tl, bench):
        self.s, self.tl, self.bench = s, tl, bench

    # The panel, without waiting for the screen to hold still afterwards (Session.press and touch do, and a project that plays
    # never lets it: each call would take 10 seconds).
    def press(self, bit, hold=0.15):
        self.s.tap(bit, hold)

    def touch(self, x, y):
        self.s.send("touch 1 %d %d" % (x + ORIGIN, y + ORIGIN))
        self.wait(0.2)
        self.s.send("touch 0 %d %d" % (x + ORIGIN, y + ORIGIN))

    def wait(self, seconds):
        self.tl.wait(seconds)

    def say(self, line):
        self.tl.say(line)


def load_episode(name):
    path = os.path.join(HERE, "reels", name + ".py")
    if not os.path.exists(path):
        sys.exit("no episode %s: it would be %s" % (name, path))
    spec = importlib.util.spec_from_file_location("episode_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare(emu, patch):
    """A fresh unit: empty stick and settings, and the internal storage as hard links to the copy of the factory one (instant, and
    the app's writes go to the folders that are copies: projects, scenes and system)."""
    cmd = '''
D="${DJS_HOME:-$HOME/djs}/reel"
SRC="${DJS_EMMC_SRC:-$HOME/djs/emmc-src}"
[ -d "$SRC/PIONEER DJ SAMPLER" ] || { echo "no copy of the unit's internal storage in $SRC (see docs/emulation.md)"; exit 1; }
rm -rf "$D"; mkdir -p "$D/usb" "$D/data"
cp -al "$SRC" "$D/emmc" || exit 1
for f in Projects Scenes System; do
    rm -rf "$D/emmc/PIONEER DJ SAMPLER/$f"
    cp -a "$SRC/PIONEER DJ SAMPLER/$f" "$D/emmc/PIONEER DJ SAMPLER/$f" || exit 1
done
'''
    if patch:
        cmd += '''P='%s'; command -v wslpath > /dev/null && P=$(wslpath -a "$P")
cp "$P" "$D/usb/autoexec.bin"
''' % os.path.abspath(patch).replace(chr(92), "/")
    code, text = emu.sh(cmd)
    if code:
        sys.exit("could not prepare the unit:\n" + text)


def project_index(emu, name):
    """The row of the project in the app's list (alphabetical)."""
    code, text = emu.sh('ls "${DJS_HOME:-$HOME/djs}/reel/emmc/PIONEER DJ SAMPLER/Projects"')
    names = sorted((n for n in text.split("\n") if n.endswith(".prj")), key=str.lower)
    if name + ".prj" not in names:
        sys.exit("no project %s in the internal storage: %s" % (name, ", ".join(names)))
    return names.index(name + ".prj")


def open_internal_project(s, row):
    """From the Project menu: OPEN, Internal, the project, OK."""
    s.turn(1)
    s.settle()
    s.push()                               # OPEN
    s.settle()
    s.turn(2)
    s.settle()
    s.push()                               # Internal
    s.settle(quiet=1.5, timeout=25)
    s.turn(row)
    s.settle()
    s.push()                               # the project: any unsaved progress will be lost
    s.settle()
    s.touch(*regress.OK)
    s.settle(quiet=1.5, timeout=60)
    s.pump(5.0)
    s.settle(quiet=1.5, timeout=60)


# ---- the picture ----

def probe(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                                   "-of", "csv=p=0", path], text=True).strip()
    w, h = out.split(",")
    return int(w), int(h)


def even(v):
    return int(round(v / 2.0)) * 2


def layout_segments(tl, length):
    """[(start, end, layout)]: the layout in force from each change to the next."""
    marks = sorted(tl.layouts)
    return [(t, marks[i + 1][0] if i + 1 < len(marks) else length, name) for i, (t, name) in enumerate(marks)]


def composite(raw, work, tl, length, fps, out, top="screen"):
    """The window of the deck, cut up and stacked into 1080x1920 as each scene's layout says. No text."""
    raw_w, raw_h = probe(raw)
    k = raw_h / float(DECK_H)
    lines, labels = [], []
    for i, (t0, t1, name) in enumerate(layout_segments(tl, length)):
        regions = LAYOUTS[layout_named(name, top)]
        dur = t1 - t0
        lines.append("color=c=black:s=%dx%d:r=%d:d=%.3f,format=yuv420p[b%d_0];" % (W, H, fps, dur, i))
        # A region is (source, where): a rectangle of the window, or None for a black box, or "box" for a thin line around where.
        cut = [j for j, (src, _) in enumerate(regions) if isinstance(src, tuple)]
        if cut:
            outs = "".join("[s%d_%d]" % (i, j) for j in cut)
            lines.append("[0:v]trim=start=%.3f:end=%.3f,setpts=PTS-STARTPTS,split=%d%s;" % (t0, t1, len(cut), outs))
        for j, (src, (dx, dy, dw, dh)) in enumerate(regions):
            if src == "box":
                lines.append("[b%d_%d]drawbox=x=%d:y=%d:w=%d:h=%d:color=%s:t=1[b%d_%d];" % (i, j, dx - 1, dy - 1, dw + 2, dh + 2, LINE, i, j + 1))
                continue
            if src is None:
                lines.append("color=c=black:s=%dx%d:r=%d:d=%.3f,format=yuv420p[c%d_%d];" % (dw, dh, fps, dur, i, j))
            else:
                sx, sy, sw, sh = src
                lines.append("[s%d_%d]crop=%d:%d:%d:%d,scale=%d:%d:flags=lanczos,setsar=1[c%d_%d];" % (
                    i, j, even(sw * k), even(sh * k), even(sx * k), even(sy * k), dw, dh, i, j))
            lines.append("[b%d_%d][c%d_%d]overlay=%d:%d[b%d_%d];" % (i, j, i, j, dx, dy, i, j + 1))
        lines.append("[b%d_%d]fps=%d,setsar=1[seg%d];" % (i, len(regions), fps, i))
        labels.append("[seg%d]" % i)
    lines.append("%sconcat=n=%d:v=1:a=0[outv]" % ("".join(labels), len(labels)))
    script = os.path.join(work, "composite.txt")
    with open(script, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", "-i", os.path.abspath(raw), "-filter_complex_script", "composite.txt",
                           "-map", "[outv]", "-c:v", "libx264", "-preset", "medium", "-crf", "14", "-pix_fmt", "yuv420p", "-r", str(fps),
                           os.path.abspath(out)], cwd=work)


def cue_list(tl):
    """The text cues in order, a cue that another replaces at once (the same moment) left out."""
    cues = sorted(tl.cues, key=lambda c: c[0])
    return [c for i, c in enumerate(cues) if i + 1 == len(cues) or cues[i + 1][0] - c[0] > 0.05]


def captions(tl, length, episode, work):
    """The drawtext filters of the text: the caption above the picture, the small line below, and the end card."""
    font = os.path.join(work, "font.ttf")
    shutil.copyfile(demo.find_font(), font)
    chain = []
    cues = cue_list(tl)
    for i, (t, caption, sub) in enumerate(cues):
        end = cues[i + 1][0] if i + 1 < len(cues) else length
        for kind, text, size, y, colour in (("c", caption, 66, 52, "white"), ("s", sub, 34, H - 58, "0xb4b4b4")):
            if not text:
                continue
            name = "text%d%s.txt" % (i, kind)
            with open(os.path.join(work, name), "w", encoding="utf-8") as f:
                f.write(text)
            chain.append("drawtext=fontfile=font.ttf:textfile=%s:x=(w-text_w)/2:y=%d:fontsize=%d:fontcolor=%s:line_spacing=12:"
                         "enable='between(t,%.2f,%.2f)'" % (name, y, size, colour, t + 0.15, end - 0.1))
    return chain


def burn(video, audio, work, chain, out, fps):
    with open(os.path.join(work, "burn.txt"), "w", encoding="utf-8") as f:
        f.write(",".join(chain))
    subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", "-i", os.path.abspath(video), "-i", os.path.abspath(audio),
                           "-filter_script:v", "burn.txt", "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "slow",
                           "-crf", "17", "-pix_fmt", "yuv420p", "-r", str(fps), "-c:a", "copy", "-movflags", "+faststart",
                           os.path.abspath(out)], cwd=work)


def master_sound(raw, work, out):
    """The deck's master output, as a track at a loudness a phone plays: -14 LUFS, peaks under -1.5 dB."""
    subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", "-f", "f32le", "-ar", "44100", "-ac", "2", "-i",
                           os.path.abspath(raw) + ".f32", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11,alimiter=limit=0.89:level=0",
                           "-c:a", "aac", "-b:a", "192k", os.path.abspath(out)], cwd=work)


def mux(video, audio, out):
    subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", "-i", os.path.abspath(video), "-i", os.path.abspath(audio), "-map", "0:v",
                           "-map", "1:a", "-c", "copy", "-shortest", "-movflags", "+faststart", os.path.abspath(out)])


def srt_time(t):
    ms = int(round(t * 1000))
    return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def write_srt(tl, length, path):
    cues = cue_list(tl)
    n = 0
    with open(path, "w", encoding="utf-8") as f:
        for i, (t, caption, sub) in enumerate(cues):
            if not (caption or sub):
                continue
            end = cues[i + 1][0] if i + 1 < len(cues) else length
            n += 1
            text = chr(10).join(x for x in (caption, sub) if x)
            f.write("%d%s%s --> %s%s%s%s%s" % (n, chr(10), srt_time(t + 0.15), srt_time(end - 0.1), chr(10), text, chr(10), chr(10)))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("episode")
    ap.add_argument("--patch", help="the djs1000-mods autoexec.bin, for the episodes that show the mods")
    ap.add_argument("--out", default=os.path.join(REPO, "demo", "reels"),
                    help="where the videos go: a folder for each episode in it (default demo/reels, git ignores demo/)")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--face", choices=("flat", "real"),
                    help="how the deck draws the unit's face: real (black gloss, chrome, brushed metal, shadows), or flat. "
                         "Default: FACE in the episode, else real. It is recorded, so changing it means recording again")
    ap.add_argument("--top", choices=("screen", "device"),
                    help="the top of the picture: the app's big screen above the panel (screen), or the unit with its own top and "
                         "small screen, the mods composited inside it (device). Default: TOP in the episode, else screen")
    ap.add_argument("--no-link", action="store_true", help="no simulated decks (deckbench)")
    ap.add_argument("--from-raw", action="store_true", help="do not record again: make the picture from the last recording")
    args = ap.parse_args()
    episode = load_episode(args.episode)
    if getattr(episode, "PATCH", False) and not args.patch and not args.from_raw:
        sys.exit("this episode shows the mods: give the mods' autoexec.bin with --patch")
    out_dir = os.path.abspath(os.path.join(args.out, args.episode))
    work = os.path.join(out_dir, "work")
    os.makedirs(work, exist_ok=True)
    raw = os.path.join(work, "raw.mp4")

    if not args.from_raw:
        record(args, episode, raw)
    plan = episode_plan(work)
    length = plan["length"]
    tl = plan["timeline"]
    top = args.top or getattr(episode, "TOP", "screen")
    composite(raw, work, tl, length, args.fps, os.path.join(work, "clean-video.mp4"), top)
    master_sound(raw, work, os.path.join(work, "sound.m4a"))
    mux(os.path.join(work, "clean-video.mp4"), os.path.join(work, "sound.m4a"), os.path.join(out_dir, "reel-clean-%s.mp4" % top))
    chain = captions(tl, length, episode, work) + end_card(episode, tl, length)
    burn(os.path.join(work, "clean-video.mp4"), os.path.join(work, "sound.m4a"), work, chain, os.path.join(out_dir, "reel-%s.mp4" % top), args.fps)
    write_srt(tl, length, os.path.join(out_dir, "reel.srt"))
    thumb = float(getattr(episode, "THUMB", 6.0))
    subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", "-ss", "%.2f" % thumb, "-i", os.path.join(out_dir, "reel-%s.mp4" % top),
                           "-frames:v", "1", os.path.join(out_dir, "thumb-%s.png" % top)])
    print("wrote %s (%.0f s)" % (os.path.join(out_dir, "reel-%s.mp4" % top), length))


def end_card(episode, tl, length):
    """drawtext filters of the end card's lines, in the last layout ("end"): a black picture."""
    segs = [s for s in layout_segments(tl, length) if s[2] == "end"]
    if not segs:
        return []
    t0, t1, _ = segs[0]
    card = getattr(episode, "END", [])
    chain, y = [], 560
    for text, size, colour in card:
        chain.append("drawtext=fontfile=font.ttf:text='%s':x=(w-text_w)/2:y=%d:fontsize=%d:fontcolor=%s:enable='between(t,%.2f,%.2f)'"
                     % (text.replace("'", "’").replace(":", "\\:"), y, size, colour, t0 + 0.2, t1))
        y += int(size * 1.5)
    return chain


def episode_plan(work):
    import json
    with open(os.path.join(work, "plan.json"), encoding="utf-8") as f:
        data = json.load(f)
    tl = Timeline(None)
    tl.layouts = [tuple(x) for x in data["layouts"]]
    tl.cues = [tuple(x) for x in data["cues"]]
    return {"timeline": tl, "length": data["length"]}


def record(args, episode, raw):
    import json
    work = os.path.dirname(raw)
    emu = start.Emulator(os.environ.get("DJS_WSL_DISTRO"), 7310, env=ENV)
    if emu.running():
        sys.exit("An emulator is running: stop it first (start.py stop).")
    prepare(emu, args.patch)
    os.environ["DJS_CAPTURE_CRF"] = "12"
    emu.start()
    deck = None
    try:
        if not emu.wait():
            sys.exit("the emulator did not answer:\n" + emu.log_tail())
        bench = None if args.no_link or not getattr(episode, "LINK", False) else emu.deckbench()
        if getattr(episode, "LINK", False) and not bench and not args.no_link:
            print("No Pro DJ Link decks: %s" % emu.bench_why)
        s = Session()
        if not s.wait_screen(quiet=1.5, timeout=120):
            sys.exit("the app never drew its first screen")
        s.wait_usb()
        if args.patch:
            regress.wait_patch(emu, s)
        open_internal_project(s, project_index(emu, episode.PROJECT))
        episode.before(s)                       # off camera: what the first picture must already show

        cmd = [sys.executable, os.path.join(REPO, "app", "virtual_djs.py"), "--port", str(emu.port), "--no-audio",
               "--no-input", "--width", str(DECK_W), "--height", str(DECK_H), "--record", raw, "--fps", str(args.fps),
               "--face", args.face or getattr(episode, "FACE", "real")]
        usb, modlist = emu.usb(), emu.modlist()
        if usb and args.patch:
            cmd += ["--usb", usb]
        if modlist and args.patch:
            cmd += ["--modlist", modlist]
        for suffix in (".start", ".stop", ".cmd", ".f32"):
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
        script = demo.Script(s, float(open(raw + ".start").read()))
        script.commands = raw + ".cmd"
        tl = Timeline(script)
        ctx = Context(s, tl, bench)
        for scene in episode.SCENES:
            began = tl.now()
            tl.layout(scene["layout"])
            tl.text(scene.get("caption", ""), scene.get("sub", ""))
            action = scene.get("do")
            if action:
                getattr(episode, "do_" + action)(ctx)
            left = scene.get("seconds", 0) - (tl.now() - began)
            if left > 0:
                tl.wait(left)
        length = tl.now()
        open(raw + ".stop", "w").close()
        deck.wait(timeout=90)
        deck = None
        with open(os.path.join(work, "plan.json"), "w", encoding="utf-8") as f:
            json.dump({"layouts": tl.layouts, "cues": tl.cues, "length": length}, f)
    finally:
        if deck:
            deck.kill()
        emu.stop()


if __name__ == "__main__":
    main()
