#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Makes a short vertical video (a reel) of the emulator: a script plays the unit and the virtual deck records it.

    reel.py EPISODE [--patch autoexec.bin] [--out DIR] [--fps 30] [--top screen|device] [--no-link] [--project NAME]
             [--shape portrait|landscape]
    reel.py EPISODE --check

EPISODE is a file with the scenes, the text of each and what is played in it: a path to a .py file, or a name, looked up in
demo/episodes (yours: git ignores it) and then in tools/reels (example.py is the one to start from). --check only loads it and
looks at its scenes, nothing is recorded. The unit starts on a fresh set of internal storage (a copy of the factory one made of hard links, see DJS_EMMC_SRC), the
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
import math
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
PORTRAIT = {
    "play": [(SCREEN, SCREEN_AT), ("box", SCREEN_AT), (PANEL, PANEL_AT), ("box", PANEL_AT)],
    "play-device": [(DEVICE, (0, TOP + 126, 1080, 1382))],
    "end": [],
}
LAYOUTS = PORTRAIT
CAPTION_Y, SUB_Y, CAPTION_SIZE, SUB_SIZE, END_Y = 52, 1920 - 58, 66, 34, 560
SHAPE = "portrait"
CAPTION_X, BACKGROUND = "(w-text_w)/2", None            # BACKGROUND: None (black), or a function (i, fps, seconds) -> its filter lines


def landscape():
    """The pictures for a 1920x1080 video (--shape landscape): the same cards, side by side. The caption is above them and the small
    text below. In `play` the face is on the left at the height that is left and the app's screen is on the right, in the middle of it.
    In `play-device` the unit as it is is on the left and the app's screen is as big as the room right of it allows."""
    top, foot = 110, 70
    room = 1080 - top - foot
    panel_w = int(round(PANEL[2] * room / float(PANEL[3])))
    device_w = int(round(DEVICE[2] * room / float(DEVICE[3])))
    layouts = {"end": []}
    for name, face, face_w in (("play", PANEL, panel_w), ("play-device", DEVICE, device_w)):
        x = MARGIN + face_w + GAP
        w = 1920 - MARGIN - x
        h = int(round(SCREEN[3] * w / float(SCREEN[2])))
        screen_at = (x, top + (room - h) // 2, w, h)
        face_at = (MARGIN, top, face_w, room)
        layouts[name] = [(SCREEN, screen_at), ("box", screen_at), (face, face_at), ("box", face_at)]
    return layouts


class Cut(tuple):
    """A rectangle of the deck's window that is shown through a mask (a file of the work folder): the unit without what is round it,
    so that the picture's dark grid shows there, or a card with rounded corners (a name that starts with round-)."""

    def __new__(cls, rect, mask="unit-mask.png"):
        cut = super().__new__(cls, rect)
        cut.mask = mask
        return cut


# The shape of the website's picture of the emulator (tools/hero.py): the unit on a dark grid with nothing round it, and on its right
# the app's screen above the list of mods, each in a thin frame. The caption is over the cards instead of over the picture.
UNIT_FROM = (0, 25, 1358, 1742)                # the unit, from the top of the housing to the foot of the case
MODS_FROM = (1380, 515, 800, 500)              # the list of mods and the text of the one pointed at
CARD_RADIUS = 5                                # the website's picture has 6 on a card 882 wide, this is the same on 710
CARD_FRAME = (46, 46, 46)                      # its frame: one dim line
HERO_BACKGROUND = "color=c=0x0d0d0f:s=%dx%d:r=%d:d=%.3f,drawgrid=width=64:height=64:thickness=1:color=white@0.03,format=yuv420p"


def hero():
    """The layouts for a 1920x1080 video in the look of the website's picture (--shape hero)."""
    unit_h = 1000
    unit_w = int(round(UNIT_FROM[2] * unit_h / float(UNIT_FROM[3])))
    card_w = 710
    screen_h = int(round(SCREEN[3] * card_w / float(SCREEN[2])))
    mods_h = int(round(MODS_FROM[3] * card_w / float(MODS_FROM[2])))
    x = (1920 - (unit_w + 60 + card_w)) // 2
    unit_at = (x, 40, unit_w, unit_h)
    screen_at = (x + unit_w + 60, 150, card_w, screen_h)
    mods_at = (screen_at[0], screen_at[1] + screen_h + 20, card_w, mods_h)
    play = [(Cut(UNIT_FROM), unit_at), (Cut(SCREEN, "round-%dx%d.png" % screen_at[2:]), screen_at), ("frame", screen_at),
            (Cut(MODS_FROM, "round-%dx%d.png" % mods_at[2:]), mods_at), ("frame", mods_at)]
    return {"play": play, "play-device": play, "end": []}, screen_at[0]


# --shape site: the website's own picture (tools/hero.py), exactly: its dark grid, its two titles and the places of its three cards.
# The picture itself is the background (without the unit, which hero.clear_background takes out), and the cards go over where
# the last version had them. The window is cut as hero.py cuts it.
SITE_SIZE = (2168, 1442)                       # the picture is 2167x1442, and a video needs an even width
SITE_UNIT_AT = (110, 110, 976, 1221)
SITE_SCREEN_AT = (1176, 154, 882, 531)
SITE_MODS_AT = (1176, 785, 882, 547)


def site():
    """The layouts for the video made like the website's picture (--shape site)."""
    play = [(Cut(UNIT_FROM), SITE_UNIT_AT), (Cut(SCREEN, "round-%dx%d.png" % SITE_SCREEN_AT[2:]), SITE_SCREEN_AT), ("frame", SITE_SCREEN_AT),
            (Cut(MODS_FROM, "round-%dx%d.png" % SITE_MODS_AT[2:]), SITE_MODS_AT), ("frame", SITE_MODS_AT)]
    return {"play": play, "play-device": play, "end": play}


def site_background(work):
    """work/site-bg.png: the website's picture with the unit taken out and a column added at the right (an even width)."""
    import hero
    from PIL import Image
    base = Image.open(hero.SITE_HERO).convert("RGB")
    hero.clear_background(base, hero.DECK_AT)
    out = Image.new("RGB", SITE_SIZE)
    out.paste(base, (0, 0))
    out.paste(base.crop((base.width - 1, 0, base.width, base.height)), (base.width, 0))
    out.save(os.path.join(work, "site-bg.png"))


def site_filters(i, fps, dur):
    return ["color=c=black:s=%dx%d:r=%d:d=%.3f,format=yuv420p[k%d];" % (W, H, fps, dur, i),
            "movie=site-bg.png,format=yuv420p[g%d];" % i,
            "[k%d][g%d]overlay=0:0:eof_action=repeat[b%d_0];" % (i, i, i)]


def hero_filters(i, fps, dur):
    return [(HERO_BACKGROUND + "[b%d_0];") % (W, H, fps, dur, i)]


def set_shape(shape):
    """Portrait (1080x1920, the default), landscape (1920x1080) or hero (1920x1080 as the website's picture): the size, the layouts
    and where the text goes."""
    global W, H, LAYOUTS, CAPTION_Y, SUB_Y, CAPTION_SIZE, SUB_SIZE, END_Y, CAPTION_X, BACKGROUND, LINE, CARD_RADIUS, SHAPE
    CAPTION_X, BACKGROUND, LINE, CARD_RADIUS, SHAPE = "(w-text_w)/2", None, "0x3a3c42", 5, shape
    if shape == "site":
        W, H = SITE_SIZE
        LAYOUTS = site()
        CARD_RADIUS, BACKGROUND = 6, site_filters
    elif shape == "hero":
        W, H = 1920, 1080
        LAYOUTS, left = hero()
        CAPTION_X = str(left)
        CAPTION_Y, SUB_Y, CAPTION_SIZE, SUB_SIZE, END_Y = 40, 94, 40, 26, 330
        BACKGROUND, LINE = hero_filters, "0x2e2e2e"
    elif shape == "landscape":
        W, H = 1920, 1080
        LAYOUTS = landscape()
        CAPTION_Y, SUB_Y, CAPTION_SIZE, SUB_SIZE, END_Y = 28, H - 52, 58, 32, 330
    else:
        W, H = 1080, 1920
        LAYOUTS = PORTRAIT
        CAPTION_Y, SUB_Y, CAPTION_SIZE, SUB_SIZE, END_Y = 52, H - 58, 66, 34, 560


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

    def __init__(self, s, tl, bench, pages=True):
        self.s, self.tl, self.bench = s, tl, bench
        self.pages = pages                       # False: `page mods` is not sent and the screen keeps the app (--shape hero)

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
        if self.pages or not line.startswith("page "):
            self.tl.say(line)


def episode_path(name):
    """A path to an episode, or the name of one: demo/episodes (private, git ignores it) before tools/reels."""
    if name.endswith(".py") or os.sep in name or "/" in name:
        return os.path.abspath(name)
    for folder in (os.path.join(REPO, "demo", "episodes"), os.path.join(HERE, "reels")):
        path = os.path.join(folder, name + ".py")
        if os.path.exists(path):
            return path
    return os.path.join(HERE, "reels", name + ".py")


def load_episode(name):
    path = episode_path(name)
    if not os.path.exists(path):
        sys.exit("no episode %s: it would be %s" % (name, path))
    base = os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location("episode_" + base, path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, os.path.dirname(path))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    module.NAME = base
    return module


def check_episode(episode):
    """The faults an episode can have that need no unit to find: a scene with no layout, an action with no function."""
    faults = []
    scenes = getattr(episode, "SCENES", None)
    if not scenes:
        return ["no SCENES"]
    for i, scene in enumerate(scenes, 1):
        if scene.get("layout") not in ("play", "mods", "end"):
            faults.append("scene %d: layout %r is not play, mods or end" % (i, scene.get("layout")))
        action = scene.get("do")
        if action and not callable(getattr(episode, "do_" + action, None)):
            faults.append("scene %d: no function do_%s" % (i, action))
        if not scene.get("seconds", 0) > 0:
            faults.append("scene %d: no seconds" % i)
    return faults


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
    """The row of the project in the app's list (alphabetical). No name is the first one."""
    code, text = emu.sh('ls "${DJS_HOME:-$HOME/djs}/reel/emmc/PIONEER DJ SAMPLER/Projects"')
    names = sorted((n for n in text.split("\n") if n.endswith(".prj")), key=str.lower)
    if not name:
        return 0
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
    if SHAPE == "site":
        site_background(work)
    if any(isinstance(src, Cut) and src.mask == "unit-mask.png" for regions in LAYOUTS.values() for src, _ in regions):
        unit_mask(raw, work, k)
    for regions in LAYOUTS.values():
        for src, (_, _, dw, dh) in regions:
            if isinstance(src, Cut) and src.mask.startswith("round-"):
                round_card(work, dw, dh)
    lines, labels = [], []
    for i, (t0, t1, name) in enumerate(layout_segments(tl, length)):
        regions = LAYOUTS[layout_named(name, top)]
        dur = t1 - t0
        if BACKGROUND:
            lines.extend(BACKGROUND(i, fps, dur))
        else:
            lines.append("color=c=black:s=%dx%d:r=%d:d=%.3f,format=yuv420p[b%d_0];" % (W, H, fps, dur, i))
        # A region is (source, where): a rectangle of the window, or None for a black box, or "box" for a thin line around where.
        cut = [j for j, (src, _) in enumerate(regions) if isinstance(src, tuple)]
        if cut:
            outs = "".join("[s%d_%d]" % (i, j) for j in cut)
            lines.append("[0:v]trim=start=%.3f:end=%.3f,setpts=PTS-STARTPTS,split=%d%s;" % (t0, t1, len(cut), outs))
        for j, (src, (dx, dy, dw, dh)) in enumerate(regions):
            if src == "frame":                       # the thin rounded line round a card, a picture with nothing else in it
                lines.append("movie=frame-%dx%d.png,format=rgba[f%d_%d];[b%d_%d][f%d_%d]overlay=%d:%d[b%d_%d];" % (
                    dw, dh, i, j, i, j, i, j, dx, dy, i, j + 1))
                continue
            if src == "box":
                lines.append("[b%d_%d]drawbox=x=%d:y=%d:w=%d:h=%d:color=%s:t=1[b%d_%d];" % (i, j, dx - 1, dy - 1, dw + 2, dh + 2, LINE, i, j + 1))
                continue
            if src is None:
                lines.append("color=c=black:s=%dx%d:r=%d:d=%.3f,format=yuv420p[c%d_%d];" % (dw, dh, fps, dur, i, j))
            else:
                sx, sy, sw, sh = src
                lines.append("[s%d_%d]crop=%d:%d:%d:%d,scale=%d:%d:flags=lanczos,setsar=1[c%d_%d];" % (
                    i, j, even(sw * k), even(sh * k), even(sx * k), even(sy * k), dw, dh, i, j))
                if isinstance(src, Cut):                  # a mask, 255 where the picture shows: only the unit, or a card with rounded corners
                    lines.append("movie=%s,scale=%d:%d,format=gray[m%d_%d];" % (src.mask, dw, dh, i, j))
                    lines.append("[c%d_%d]format=rgba[r%d_%d];[r%d_%d][m%d_%d]alphamerge[c%d_%d];" % (i, j, i, j, i, j, i, j, i, j))
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


def unit_mask(raw, work, k):
    """work/unit-mask.png: white where the unit is and black round it, from a frame of the recording (the unit's own black is inside
    it, so what is round it is the black that joins the corners, as tools/hero.py has it)."""
    import hero
    from PIL import Image, ImageOps
    frame = os.path.join(work, "unit-frame.png")
    subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", os.path.abspath(raw), "-frames:v", "1", frame])
    sx, sy, sw, sh = UNIT_FROM
    crop = Image.open(frame).convert("RGB").crop((int(sx * k), int(sy * k), int((sx + sw) * k), int((sy + sh) * k)))
    ImageOps.invert(hero.outside(crop)).save(os.path.join(work, "unit-mask.png"))


def round_card(work, w, h):
    """work/round-WxH.png (white inside a rounded rectangle) and work/frame-WxH.png (its outline, on nothing), drawn at four times the
    size and brought down so that the corners are smooth."""
    from PIL import Image, ImageDraw
    n = 4
    mask = Image.new("L", (w * n, h * n), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w * n - 1, h * n - 1), radius=CARD_RADIUS * n, fill=255)
    mask.resize((w, h), Image.LANCZOS).save(os.path.join(work, "round-%dx%d.png" % (w, h)))
    line = Image.new("RGBA", (w * n, h * n), (0, 0, 0, 0))
    ImageDraw.Draw(line).rounded_rectangle((0, 0, w * n - 1, h * n - 1), radius=CARD_RADIUS * n, outline=CARD_FRAME + (255,), width=n)
    line.resize((w, h), Image.LANCZOS).save(os.path.join(work, "frame-%dx%d.png" % (w, h)))


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
        for kind, text, size, y, colour in (("c", caption, CAPTION_SIZE, CAPTION_Y, "white"), ("s", sub, SUB_SIZE, SUB_Y, "0xb4b4b4")):
            if not text:
                continue
            name = "text%d%s.txt" % (i, kind)
            with open(os.path.join(work, name), "w", encoding="utf-8") as f:
                f.write(text)
            chain.append("drawtext=fontfile=font.ttf:textfile=%s:x=%s:y=%d:fontsize=%d:fontcolor=%s:line_spacing=12:"
                         "enable='between(t,%.2f,%.2f)'" % (name, CAPTION_X, y, size, colour, t + 0.15, end - 0.1))
    return chain


def burn(video, audio, work, chain, out, fps):
    with open(os.path.join(work, "burn.txt"), "w", encoding="utf-8") as f:
        f.write(",".join(chain))
    subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", "-i", os.path.abspath(video), "-i", os.path.abspath(audio),
                           "-filter_script:v", "burn.txt", "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "slow",
                           "-crf", "17", "-pix_fmt", "yuv420p", "-r", str(fps), "-c:a", "copy", "-movflags", "+faststart",
                           os.path.abspath(out)], cwd=work)


def declick(path, out, rate=44100, fade=0.008):
    """Copies the sound with a short fade out before each hard stop. When the unit stops (the pattern, a sample), what was loud
    can end on a sample that is far from zero and the sound drops to digital silence: a click. Found by the level falling by
    more than 35 dB in 5 ms from above -40 dB. The sound is not touched anywhere else."""
    import array
    data = array.array("f")
    with open(path, "rb") as f:
        data.frombytes(f.read())
    hop = int(rate * 0.005)
    frames = len(data) // 2
    level = []
    for i in range(0, frames - hop, hop):
        total = 0.0
        for k in range(i * 2, (i + hop) * 2, 2):
            total += data[k] * data[k]
        level.append(10 * math.log10(total / hop + 1e-18))
    count = 0
    for k in range(1, len(level)):
        if level[k - 1] > -40 and level[k] < level[k - 1] - 35:
            end = k * hop                                        # the frame the silence starts at
            while end > 0 and abs(data[2 * (end - 1)]) < 1e-6 and abs(data[2 * (end - 1) + 1]) < 1e-6:
                end -= 1                                         # (the signal may stop a little before the window)
            n = int(rate * fade)
            for j in range(n):
                g = j / float(n)                                 # 1 down to 0 over the last n frames
                for c in (0, 1):
                    data[2 * (end - n + j) + c] *= 1.0 - g
            count += 1
    with open(out, "wb") as f:
        f.write(data.tobytes())
    return count


def master_sound(raw, work, out):
    """The deck's master output, as a track at a loudness a phone plays: -14 LUFS, peaks under -1.5 dB, a click taken out where
    the sound stops hard, and a few milliseconds of fade in at the start."""
    clean = os.path.abspath(raw) + ".clean.f32"
    n = declick(os.path.abspath(raw) + ".f32", clean)
    if n:
        print("declicked %d hard stop(s)" % n)
    subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", "-f", "f32le", "-ar", "44100", "-ac", "2", "-i", clean,
                           "-af", "afade=t=in:d=0.02,loudnorm=I=-14:TP=-1.5:LRA=11,alimiter=limit=0.89:level=0",
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
    ap.add_argument("--project", help="the project to open from the unit's internal storage (default: PROJECT in the episode, else the first)")
    ap.add_argument("--check", action="store_true", help="only look at the episode's scenes, no recording (needs no unit)")
    ap.add_argument("--shape", choices=("portrait", "landscape", "hero", "site"), default=None,
                    help="portrait is 1080x1920 (Reels, Shorts, TikTok), landscape 1920x1080 (Reddit, YouTube). It is made from the "
                         "same recording, so --from-raw changes it. hero is landscape in the look of the website's picture, site is that picture "
                         "itself, to the pixel, made to move (2168x1442). Default: SHAPE in the episode, else portrait")
    ap.add_argument("--no-link", action="store_true", help="no simulated decks (deckbench)")
    ap.add_argument("--from-raw", action="store_true", help="do not record again: make the picture from the last recording")
    args = ap.parse_args()
    episode = load_episode(args.episode)
    if args.check:
        faults = check_episode(episode)
        for fault in faults:
            print("%s: %s" % (episode.NAME, fault))
        print("%s: %d scenes, %s" % (episode.NAME, len(getattr(episode, "SCENES", [])), "%d faults" % len(faults) if faults else "ok"))
        sys.exit(1 if faults else 0)
    if getattr(episode, "PATCH", False) and not args.patch and not args.from_raw:
        sys.exit("this episode shows the mods: give the mods' autoexec.bin with --patch")
    args.shape = args.shape or getattr(episode, "SHAPE", "portrait")
    set_shape(args.shape)
    out_dir = os.path.abspath(os.path.join(args.out, episode.NAME))
    # The hero shape has the list of mods beside the unit, so the app's screen is not given a page of it: it is another recording
    work = os.path.join(out_dir, "work-hero" if args.shape in ("hero", "site") else "work")
    os.makedirs(work, exist_ok=True)
    raw = os.path.join(work, "raw.mp4")

    if not args.from_raw:
        record(args, episode, raw)
    plan = episode_plan(work)
    length = plan["length"]
    tl = plan["timeline"]
    top = args.top or getattr(episode, "TOP", "screen")
    tag = args.shape if args.shape in ("hero", "site") else top + ("-wide" if args.shape == "landscape" else "")        # the files of the landscape picture have -wide after the look
    composite(raw, work, tl, length, args.fps, os.path.join(work, "clean-video.mp4"), top)
    master_sound(raw, work, os.path.join(work, "sound.m4a"))
    mux(os.path.join(work, "clean-video.mp4"), os.path.join(work, "sound.m4a"), os.path.join(out_dir, "reel-clean-%s.mp4" % tag))
    chain = captions(tl, length, episode, work) + end_card(episode, tl, length)
    if chain:
        burn(os.path.join(work, "clean-video.mp4"), os.path.join(work, "sound.m4a"), work, chain, os.path.join(out_dir, "reel-%s.mp4" % tag), args.fps)
    else:                                                  # no text anywhere (the site shape): the one picture is both
        shutil.copyfile(os.path.join(out_dir, "reel-clean-%s.mp4" % tag), os.path.join(out_dir, "reel-%s.mp4" % tag))
    write_srt(tl, length, os.path.join(out_dir, "reel.srt"))
    thumb = float(getattr(episode, "THUMB", 6.0))
    subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", "-ss", "%.2f" % thumb, "-i", os.path.join(out_dir, "reel-%s.mp4" % tag),
                           "-frames:v", "1", os.path.join(out_dir, "thumb-%s.png" % tag)])
    print("wrote %s (%.0f s)" % (os.path.join(out_dir, "reel-%s.mp4" % tag), length))


def end_card(episode, tl, length):
    """drawtext filters of the end card's lines, in the last layout ("end"): a black picture."""
    segs = [s for s in layout_segments(tl, length) if s[2] == "end"]
    if not segs:
        return []
    t0, t1, _ = segs[0]
    card = getattr(episode, "END", [])
    chain, y = [], END_Y
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
        if getattr(episode, "KIT", False):                    # the generated kit (a project made from the test samples), not a factory one
            demo.load_kit(s)
        else:
            open_internal_project(s, project_index(emu, args.project or getattr(episode, "PROJECT", "")))
        getattr(episode, "before", lambda s: None)(s)                       # off camera: what the first picture must already show

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
        ctx = Context(s, tl, bench, pages=args.shape not in ("hero", "site"))
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
