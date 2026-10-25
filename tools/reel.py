#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Makes a short video (a reel) of the emulator, vertical unless --shape says another: a script plays the unit and the virtual deck records it.

    reel.py EPISODE [--patch autoexec.bin] [--out DIR] [--fps 30] [--top screen|device] [--no-link] [--project NAME]
             [--shape portrait|landscape|hero|site|window] [--res hd|2k|4k] [--grid] [--bg dark|black|green|transparent]
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
import types

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
STATUS_FROM = (0, DECK_H - 26, DECK_W, 26)   # the deck's status line at the foot of its window (--status)
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


def with_status(layouts):
    """The layouts with the status line as a strip of its own under everything else, as wide as the pictures are."""
    out = {}
    for name, regions in layouts.items():
        out[name] = list(regions)
        if name == "end" or not regions:
            continue
        x0 = min(at[0] for _, at in regions)
        x1 = max(at[0] + at[2] for _, at in regions)
        foot = max(at[1] + at[3] for _, at in regions)
        w = x1 - x0
        out[name].append((STATUS_FROM, (x0, foot + 6, w, int(round(STATUS_FROM[3] * w / float(STATUS_FROM[2]))))))
    return out


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
HERO_BACKGROUND = "color=c=%s:s=%dx%d:r=%d:d=%.3f,%sformat=%s"
HERO_GRID = "drawgrid=width=%d:height=%d:thickness=%d:color=white@0.03,"      # --grid: the website's lines, every 64 pixels


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


def hero_full():
    """The hero's layouts for the clean video (no text): the unit where it is, and the app's screen above the list of mods filling the
    whole height of the unit (flush with its top and its foot), a little wider than with the caption over them."""
    unit_h = 1000
    unit_w = int(round(UNIT_FROM[2] * unit_h / float(UNIT_FROM[3])))
    gap = 20
    body_h = 994                      # the unit's case is shorter than its cut: the dark below it is not part of what the panels line up with
    card_w = int((body_h - gap) / (SCREEN[3] / float(SCREEN[2]) + MODS_FROM[3] / float(MODS_FROM[2])))
    screen_h = int(round(SCREEN[3] * card_w / float(SCREEN[2])))
    x = (1920 - (unit_w + 60 + 710)) // 2                    # the unit is where the captioned video has it
    unit_at = (x, 40, unit_w, unit_h)
    screen_at = (x + unit_w + 60, 40, card_w, screen_h)
    mods_at = (screen_at[0], 40 + screen_h + gap, card_w, body_h - screen_h - gap)
    play = [(Cut(UNIT_FROM), unit_at), (Cut(SCREEN, "round-%dx%d.png" % screen_at[2:]), screen_at), ("frame", screen_at),
            (Cut(MODS_FROM, "round-%dx%d.png" % mods_at[2:]), mods_at), ("frame", mods_at)]
    return {"play": play, "play-device": play, "end": []}


# --shape site: the website's own picture (tools/hero.py), exactly: its dark grid, its two titles and the places of its three cards.
# The picture itself is the background (without the unit, which hero.clear_background takes out), and the cards go over where
# the last version had them. The window is cut as hero.py cuts it.
SITE_BASE = (2168, 1442)                       # the picture is 2167x1442, and a video needs an even width
SITE_SIZE = SITE_BASE                          # the same at the --res
SITE_UNIT_AT = (110, 110, 976, 1221)
SITE_SCREEN_AT = (1176, 154, 882, 531)
SITE_MODS_AT = (1176, 785, 882, 547)


def site():
    """The layouts for the video made like the website's picture (--shape site)."""
    play = [(Cut(UNIT_FROM), SITE_UNIT_AT), (Cut(SCREEN, "round-%dx%d.png" % SITE_SCREEN_AT[2:]), SITE_SCREEN_AT), ("frame", SITE_SCREEN_AT),
            (Cut(MODS_FROM, "round-%dx%d.png" % SITE_MODS_AT[2:]), SITE_MODS_AT), ("frame", SITE_MODS_AT)]
    return {"play": play, "play-device": play, "end": play}


def remove_grid(img):
    """Takes the picture's grid (a line of one pixel every 64 pixels, a little brighter) out: a pixel on a line gets the mean of its two
    neighbours across the line where they agree, so a title that crosses a line is left alone."""
    px = img.load()
    w, h = img.size
    for x in range(64, w - 1, 64):
        for y in range(h):
            a, b = px[x - 1, y], px[x + 1, y]
            if max(abs(a[c] - b[c]) for c in range(3)) <= 2:
                px[x, y] = tuple((a[c] + b[c] + 1) // 2 for c in range(3))
    for y in range(64, h - 1, 64):
        for x in range(w):
            a, b = px[x, y - 1], px[x, y + 1]
            if max(abs(a[c] - b[c]) for c in range(3)) <= 2:
                px[x, y] = tuple((a[c] + b[c] + 1) // 2 for c in range(3))


def site_background(work):
    """work/site-bg.png: the website's picture with the unit taken out and a column added at the right (an even width), without its
    grid unless --grid, at the size of the video."""
    import hero
    from PIL import Image
    base = Image.open(hero.SITE_HERO).convert("RGB")
    hero.clear_background(base, hero.DECK_AT)
    out = Image.new("RGB", SITE_BASE)
    out.paste(base, (0, 0))
    out.paste(base.crop((base.width - 1, 0, base.width, base.height)), (base.width, 0))
    if not GRID:
        remove_grid(out)
    if out.size != SITE_SIZE:
        out = out.resize(SITE_SIZE, Image.LANCZOS)
    out.save(os.path.join(work, "site-bg.png"))


def site_filters(i, fps, dur):
    if BG != "dark":                                   # no picture behind: its titles go too
        return hero_filters(i, fps, dur)
    return ["color=c=black:s=%dx%d:r=%d:d=%.3f,format=yuv420p[k%d];" % (W, H, fps, dur, i),
            "movie=site-bg.png,format=yuv420p[g%d];" % i,
            "[k%d][g%d]overlay=0:0:eof_action=repeat[b%d_0];" % (i, i, i)]


def hero_filters(i, fps, dur):
    grid = HERO_GRID % (even(64 * SCALE), even(64 * SCALE), BOX_T) if GRID else ""
    return [(HERO_BACKGROUND + "[b%d_0];") % (BG_COLOUR[BG], W, H, fps, dur, grid, PIX_FMT, i)]


WINDOW_H = 1060                                # the height of the deck's window when it opens on a desktop that has room (virtual_djs.py)


def encoder(fps, preset, crf):
    """The video codec: H.264, or ProRes 4444 with its alpha for --bg transparent (the file is a .mov)."""
    if PIX_FMT == "yuva444p":
        return ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", "-r", str(fps)]
    return ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p", "-r", str(fps)]


def composite_window(raw, out, fps):
    """The window of the deck as it is: the recording, to an even size, whatever the scenes are."""
    subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", "-i", os.path.abspath(raw), "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1",
                           "-c:v", "libx264", "-preset", "medium", "-crf", "14", "-pix_fmt", "yuv420p", "-r", str(fps), os.path.abspath(out)])


RESOLUTIONS = {"hd": 1.0, "2k": 4 / 3.0, "4k": 2.0}      # 1080 on the short side of the picture, 1440, 2160
SCALE, BOX_T, GRID = 1.0, 1, False
CLEAN_LAYOUTS = None                                   # --shape hero: the layouts of the video without text, where they differ
BG, BG_COLOUR = "dark", {"dark": "0x0d0d0f", "black": "black", "green": "0x00ff00", "transparent": "black@0"}
LIFT = 0                                               # --bg black: the unit and the cards never go below this level (of 255), so that
#                                                        the background is the only pure black and a luma key takes it out
PIX_FMT, OVERLAY, EXT = "yuv420p", "", ".mp4"          # --bg transparent: yuva444p, format=auto on each overlay, a ProRes 4444 .mov


def scaled_layouts(layouts, f):
    """The layouts with where each region goes (not where it is cut from) multiplied by f."""
    out = {}
    for name, regions in layouts.items():
        out[name] = []
        for src, at in regions:
            at = tuple(int(round(v * f)) for v in at)
            if isinstance(src, Cut) and src.mask.startswith("round-"):      # its mask is made for the size it is shown at
                src = Cut(tuple(src), "round-%dx%d.png" % at[2:])
            out[name].append((src, at))
    return out


def set_shape(shape, res="hd", grid=False, bg="dark", status=False):
    """Portrait (1080x1920, the default), landscape (1920x1080), hero (1920x1080 in the look of the website's picture), site (that
    picture itself, 2168x1442) or window (the deck's window as it opens): the size, the layouts and where the text goes. res makes the
    picture 1.33 (2k) or 2 (4k) times as big, every layout, text and line with it (the window shape is the recording as it is)."""
    global W, H, LAYOUTS, CAPTION_Y, SUB_Y, CAPTION_SIZE, SUB_SIZE, END_Y, CAPTION_X, BACKGROUND, LINE, CARD_RADIUS, SHAPE
    global SCALE, BOX_T, GRID, SITE_SIZE, BG, PIX_FMT, OVERLAY, EXT, LIFT, CLEAN_LAYOUTS
    CLEAN_LAYOUTS = None
    BG = bg if shape in ("hero", "site") else "dark"       # the other shapes have no background of their own
    LIFT = 4 if BG == "black" else 0
    PIX_FMT, OVERLAY, EXT = ("yuva444p", ":format=auto", ".mov") if BG == "transparent" else ("yuv420p", "", ".mp4")
    CAPTION_X, BACKGROUND, LINE, CARD_RADIUS, SHAPE = "(w-text_w)/2", None, "0x3a3c42", 5, shape
    SCALE = 1.0 if shape == "window" else RESOLUTIONS[res]
    BOX_T, GRID = max(1, int(round(SCALE))), grid
    SITE_SIZE = (even(SITE_BASE[0] * SCALE), even(SITE_BASE[1] * SCALE))
    left = 0
    if shape == "window":
        LAYOUTS = {"play": [], "play-device": [], "end": []}               # nothing is laid out (see composite_window)
    elif shape == "site":
        W, H = SITE_SIZE
        LAYOUTS = scaled_layouts(site(), SCALE)
        CARD_RADIUS, BACKGROUND = 6, site_filters
    elif shape == "hero":
        W, H = 1920, 1080
        LAYOUTS, left = hero()
        CLEAN_LAYOUTS = hero_full()
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
    if status and shape in ("portrait", "landscape", "hero"):
        LAYOUTS = with_status(LAYOUTS)
        CLEAN_LAYOUTS = with_status(CLEAN_LAYOUTS) if CLEAN_LAYOUTS else None
    if shape not in ("window", "site"):
        W, H = even(W * SCALE), even(H * SCALE)
        LAYOUTS = scaled_layouts(LAYOUTS, SCALE)
        CLEAN_LAYOUTS = scaled_layouts(CLEAN_LAYOUTS, SCALE) if CLEAN_LAYOUTS else None
        CAPTION_Y, SUB_Y, CAPTION_SIZE, SUB_SIZE, END_Y = (int(round(v * SCALE)) for v in (CAPTION_Y, SUB_Y, CAPTION_SIZE, SUB_SIZE, END_Y))
        if shape == "hero":
            CAPTION_X = str(int(round(left * SCALE)))
    CARD_RADIUS = CARD_RADIUS * SCALE


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
    if name.endswith((".py", ".steps")) or os.sep in name or "/" in name:
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
    if path.endswith(".steps"):
        return steps_episode(path, base)
    spec =importlib.util.spec_from_file_location("episode_" + base, path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, os.path.dirname(path))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    module.NAME = base
    return module


def steps_episode(path, base):
    """An episode made of a REC's NAME.steps (app/virtual_djs.py): one scene in which every command the deck sent is sent again, at
    the same second. It starts from the unit as it boots, with no project open (BARE) and your own
    stick in it, so a recording made to be played back should begin there too, and its steps load the project. Or a project is given
    (--project, --usb-project) and is opened first, and the recording begins after loading it."""
    steps, project = [], ""
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("# project:"):
                project = line.partition(":")[2].strip()
            if line and not line.startswith("#"):
                at, _, command = line.partition(" ")
                steps.append((float(at), command))
    if not steps:
        sys.exit("%s has no steps" % path)

    journal = None                                   # what was done in deckbench meanwhile (NAME.bench beside the steps)
    side = os.path.splitext(path)[0] + ".bench"
    if os.path.exists(side):
        import json
        with open(side, encoding="utf-8") as f:
            journal = json.load(f)
    events = [(at, "send", command) for at, command in steps]
    if journal:
        events += [(at, "bench", request) for at, request in journal["actions"]]
        events.sort(key=lambda e: e[0])

    def bench_post(ctx, path):
        import urllib.request
        try:
            urllib.request.urlopen(urllib.request.Request(ctx.bench.replace("localhost", "127.0.0.1").rstrip("/") + path, method="POST"),
                                   timeout=5).read()
        except OSError as e:
            print("deckbench did not take %s: %s" % (path, e))

    def bench_reachable(ctx):
        import urllib.request
        try:
            urllib.request.urlopen(ctx.bench.replace("localhost", "127.0.0.1").rstrip("/") + "/api/ready", timeout=4).read()
            return True
        except OSError as e:
            print("deckbench does not answer at %s (%s): its part of the recording is left out. On Windows a stale wslrelay.exe can hold "
                  "the port (wsl --shutdown clears it)" % (ctx.bench, e))
            return False

    def do_steps(ctx):
        if journal and ctx.bench and not bench_reachable(ctx):
            ctx.bench = None
        if journal and ctx.bench:                    # the bench as it was when the recording began: every deck off, then the baseline
            for n in (1, 2, 3, 4):
                for what in ("on/0", "plug", "audio/clear"):
                    bench_post(ctx, "/api/deck/%d/%s" % (n, what))
            for request in journal["baseline"]:
                bench_post(ctx, request)
        began = ctx.tl.now()
        for at, kind, command in events:
            late = began + at - ctx.tl.now()
            if late > 0:
                ctx.wait(late)
            if kind == "bench":
                if ctx.bench:
                    bench_post(ctx, command)
            else:
                ctx.say("send " + command)           # through the deck, which draws the knobs and the strip as they move

    scenes = [{"layout": "play", "seconds": max(e[0] for e in events) + 3.0, "do": "steps"}]
    episode = types.SimpleNamespace(NAME=base, SCENES=scenes, do_steps=do_steps, STEPS=True, BARE=True)
    if journal:                                  # deckbench was up: it is again, and the unit's input is the bench's sound if it was
        episode.LINK, episode.INPUT = True, journal.get("input") == "bench"
    if project:                                  # the recording began with this project open: it is opened first, from where it was
        name = os.path.splitext(os.path.basename(project))[0]
        episode.BARE = False
        if "/usb" in project:
            episode.USB_PROJECT, episode.MIRROR_SETTINGS = name, True
        else:
            episode.PROJECT = name
    return episode


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


def prepare(emu, patch, kit=False, usb_project="", mod_settings=None, stick=False, mirror_settings=False):
    """A fresh unit: empty stick (or with the generated test kit on it, for an episode that loads it, or with a project of your own
    copied from the stick in $DJS_USB_SRC, default ~/djs/usb, with its samples, and the mods' settings the episode gives) and settings,
    and the internal storage as hard links to the copy of the factory one (instant, and the app's writes go to the folders that are copies: projects,
    scenes and system). stick: the stick is a copy of your own ($DJS_USB_SRC, with its autoexec.bin and settings), which a played-back
    REC needs to find what it opened."""
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
    if stick:
        cmd += '''U="${DJS_USB_SRC:-$HOME/djs/usb}"
[ -d "$U" ] || { echo "no stick in $U"; exit 1; }
cp -a "$U/." "$D/usb/" || exit 1
rm -f "$D"/usb/*.log "$D"/usb/*.log.old "$D"/usb/djs1000-trace.txt "$D"/usb/djs1000-report.txt
'''
    if kit:
        cmd += '''python3 '%s/tools/make_test_kit.py' "$D/usb/PIONEER DJ SAMPLER/Samples/Test Kit"
''' % emu.repo()
    if usb_project:
        cmd += '''U="${DJS_USB_SRC:-$HOME/djs/usb}/PIONEER DJ SAMPLER"; N='%s'
[ -f "$U/Projects/$N.prj" ] || { echo "no project $N on the stick in $U"; exit 1; }
mkdir -p "$D/usb/PIONEER DJ SAMPLER/Projects" "$D/usb/PIONEER DJ SAMPLER/Samples"
cp -a "$U/Projects/$N.prj" "$D/usb/PIONEER DJ SAMPLER/Projects/" || exit 1
[ -d "$U/Samples/$N" ] && { cp -a "$U/Samples/$N" "$D/usb/PIONEER DJ SAMPLER/Samples/" || exit 1; }
''' % usb_project
    if mirror_settings:                       # the settings of your own stick, as the recording had them
        cmd += '''S="${DJS_USB_SRC:-$HOME/djs/usb}/djs1000-mods.txt"; [ -f "$S" ] && cp "$S" "$D/usb/"
'''
    if mod_settings:                          # what the mods read from the stick: `key = value` lines, the rest is as they start
        text = "".join("%s = %s\n" % (k, v) for k, v in mod_settings.items())
        cmd += "cat > \"$D/usb/djs1000-mods.txt\" << 'MODS_EOF'\n" + text + "MODS_EOF\n"
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


def open_usb_project(s, row=0):
    """From the Project menu: OPEN, USB, the project (the stick holds the episode's USB_PROJECT, which is the first row unless
    there are others before it), OK."""
    s.turn(1)
    s.settle()
    s.push()                               # OPEN
    s.settle()
    s.push()                               # USB
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


def composite(raw, work, tl, length, fps, out, top="screen", layouts=None):
    """The window of the deck, cut up and stacked into 1080x1920 as each scene's layout says. No text."""
    layouts = layouts or LAYOUTS
    if SHAPE == "window":
        return composite_window(raw, out, fps)
    raw_w, raw_h = probe(raw)
    k = raw_h / float(DECK_H)
    if SHAPE == "site":
        site_background(work)
    if any(isinstance(src, Cut) and src.mask == "unit-mask.png" for regions in layouts.values() for src, _ in regions):
        unit_mask(raw, work, k)
    for regions in layouts.values():
        for src, (_, _, dw, dh) in regions:
            if isinstance(src, Cut) and src.mask.startswith("round-"):
                round_card(work, dw, dh)
    lines, labels = [], []
    for i, (t0, t1, name) in enumerate(layout_segments(tl, length)):
        regions = layouts[layout_named(name, top)]
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
                lines.append("movie=frame-%dx%d.png,format=rgba[f%d_%d];[b%d_%d][f%d_%d]overlay=%d:%d%s[b%d_%d];" % (
                    dw, dh, i, j, i, j, i, j, dx, dy, OVERLAY, i, j + 1))
                continue
            if src == "box":
                lines.append("[b%d_%d]drawbox=x=%d:y=%d:w=%d:h=%d:color=%s:t=%d[b%d_%d];" % (
                    i, j, dx - BOX_T, dy - BOX_T, dw + 2 * BOX_T, dh + 2 * BOX_T, LINE, BOX_T, i, j + 1))
                continue
            if src is None:
                lines.append("color=c=black:s=%dx%d:r=%d:d=%.3f,format=yuv420p[c%d_%d];" % (dw, dh, fps, dur, i, j))
            else:
                sx, sy, sw, sh = src
                lift = ",lutrgb=r='max(val\\,%d)':g='max(val\\,%d)':b='max(val\\,%d)'" % (LIFT, LIFT, LIFT) if LIFT else ""
                lines.append("[s%d_%d]crop=%d:%d:%d:%d,scale=%d:%d:flags=lanczos,setsar=1%s[c%d_%d];" % (
                    i, j, even(sw * k), even(sh * k), even(sx * k), even(sy * k), dw, dh, lift, i, j))
                if isinstance(src, Cut):                  # a mask, 255 where the picture shows: only the unit, or a card with rounded corners
                    lines.append("movie=%s,scale=%d:%d,format=gray[m%d_%d];" % (src.mask, dw, dh, i, j))
                    lines.append("[c%d_%d]format=rgba[r%d_%d];[r%d_%d][m%d_%d]alphamerge[c%d_%d];" % (i, j, i, j, i, j, i, j, i, j))
            lines.append("[b%d_%d][c%d_%d]overlay=%d:%d%s[b%d_%d];" % (i, j, i, j, dx, dy, OVERLAY, i, j + 1))
        lines.append("[b%d_%d]fps=%d,setsar=1[seg%d];" % (i, len(regions), fps, i))
        labels.append("[seg%d]" % i)
    lines.append("%sconcat=n=%d:v=1:a=0[outv]" % ("".join(labels), len(labels)))
    script = os.path.join(work, "composite.txt")
    with open(script, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", "-i", os.path.abspath(raw), "-filter_complex_script", "composite.txt",
                           "-map", "[outv]"] + encoder(fps, "medium", 14) + [os.path.abspath(out)], cwd=work)


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
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w * n - 1, h * n - 1), radius=int(round(CARD_RADIUS * n)), fill=255)
    mask.resize((w, h), Image.LANCZOS).save(os.path.join(work, "round-%dx%d.png" % (w, h)))
    line = Image.new("RGBA", (w * n, h * n), (0, 0, 0, 0))
    ImageDraw.Draw(line).rounded_rectangle((0, 0, w * n - 1, h * n - 1), radius=int(round(CARD_RADIUS * n)), outline=CARD_FRAME + (255,), width=n * BOX_T)
    line.resize((w, h), Image.LANCZOS).save(os.path.join(work, "frame-%dx%d.png" % (w, h)))


def cue_list(tl):
    """The text cues in order, a cue that another replaces at once (the same moment) left out."""
    cues = sorted(tl.cues, key=lambda c: c[0])
    return [c for i, c in enumerate(cues) if i + 1 == len(cues) or cues[i + 1][0] - c[0] > 0.05]


def captions(tl, length, episode, work):
    """The drawtext filters of the text: the caption above the picture, the small line below, and the end card."""
    if SHAPE in ("site", "window"):                    # the picture is the window or the website's picture, as it is: no text on it
        return []
    font = os.path.join(work, "font.ttf")
    shutil.copyfile(demo.find_font(), font)
    chain = []
    cues = cue_list(tl)
    for i, (t, caption, sub) in enumerate(cues):
        end = cues[i + 1][0] if i + 1 < len(cues) else length
        if SHAPE in ("landscape", "hero"):                       # wide enough for one line, and a second one would run into the small text
            caption = caption.replace(chr(10), " ")
        for kind, text, size, y, colour in (("c", caption, CAPTION_SIZE, CAPTION_Y, "white"), ("s", sub, SUB_SIZE, SUB_Y, "0xb4b4b4")):
            if not text:
                continue
            name = "text%d%s.txt" % (i, kind)
            with open(os.path.join(work, name), "w", encoding="utf-8") as f:
                f.write(text)
            chain.append("drawtext=fontfile=font.ttf:textfile=%s:x=%s:y=%d:fontsize=%d:fontcolor=%s:line_spacing=%d:"
                         "enable='between(t,%.2f,%.2f)'" % (name, CAPTION_X, y, size, colour, int(round(12 * SCALE)), t + 0.15, end - 0.1))
    return chain


def burn(video, audio, work, chain, out, fps):
    with open(os.path.join(work, "burn.txt"), "w", encoding="utf-8") as f:
        f.write(",".join(chain))
    subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", "-i", os.path.abspath(video), "-i", os.path.abspath(audio),
                           "-filter_script:v", "burn.txt", "-map", "0:v", "-map", "1:a"] + encoder(fps, "slow", 17) + ["-c:a", "copy", "-movflags", "+faststart",
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
    # What the unit's input monitor plays comes out of its headphones, not the master: it is mixed in (it is silent otherwise)
    phones = os.path.abspath(raw) + ".f32p"
    mix = os.path.exists(phones) and os.path.getsize(phones) > 0
    levels = "afade=t=in:d=0.02,loudnorm=I=-14:TP=-1.5:LRA=11,alimiter=limit=0.89:level=0"
    # The emulator's sound is a few percent longer than the picture it was recorded with (see app/capture.py), so the sound is sped up
    # by the ratio the deck wrote, without a change of pitch, and each sound stays where its picture is
    speed = ""
    rate = os.path.abspath(raw) + ".rate"
    ratio = 1.0
    if os.path.exists(rate):
        ratio = float(open(rate).read())
    elif os.path.exists(os.path.abspath(raw) + ".f32"):             # a recording from before the deck wrote it: the lengths say
        seconds = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                                 os.path.abspath(raw)], text=True))
        ratio = os.path.getsize(os.path.abspath(raw) + ".f32") / 8.0 / 44100 / seconds
    if abs(ratio - 1.0) > 0.002:
        speed = "asetrate=%d,aresample=44100," % round(44100 * ratio)     # resampled: atempo smears the bass
        print("sound sped up %.2f%% to match the picture" % ((ratio - 1.0) * 100))
    raw_in = ["-f", "f32le", "-ar", "44100", "-ac", "2"]
    if mix:
        sound = (raw_in + ["-i", clean] + raw_in + ["-i", phones] +
                 ["-filter_complex", "[0:a]%s[m];[1:a]%s[p];[m][p]amix=inputs=2:normalize=0:duration=first,%s[a]" % (
                     speed.rstrip(",") or "anull", speed.rstrip(",") or "anull", levels), "-map", "[a]"])
    else:
        sound = raw_in + ["-i", clean, "-af", speed + levels]
    subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error"] + sound + ["-c:a", "aac", "-b:a", "192k", os.path.abspath(out)], cwd=work)


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
    ap.add_argument("--usb-project", metavar="NAME",
                    help="the project to open from the stick (in $DJS_USB_SRC, default ~/djs/usb, with its samples and the stick's mods "
                         "settings) before the scenes: USB_PROJECT in the episode. For a .steps file it is the project that the "
                         "recording had open when it began")
    ap.add_argument("--check", action="store_true", help="only look at the episode's scenes, no recording (needs no unit)")
    ap.add_argument("--shape", choices=("portrait", "landscape", "hero", "site", "window"), default=None,
                    help="portrait is 1080x1920 (Reels, Shorts, TikTok), landscape 1920x1080 (Reddit, YouTube). It is made from the "
                         "same recording, so --from-raw changes it. hero is landscape in the look of the website's picture, site is that picture "
                         "itself, to the pixel, made to move (2168x1442), window is the deck's window as it opens (about 1626x1060), "
                         "with no layout and no text. Default: SHAPE in the episode, else portrait")
    ap.add_argument("--res", choices=tuple(RESOLUTIONS), default="hd",
                    help="the size of the picture: hd is as the shape says (1080 on its short side), 2k is 1440 and 4k is 2160, with every "
                         "layout and text made bigger. Like --shape, it is made from the same recording (--from-raw). The deck's window is "
                         "recorded at one size, so the app's screen (800x480) is scaled up. The files have -2k or -4k after the shape")
    ap.add_argument("--grid", action="store_true",
                    help="the website's grid of lines behind the unit (--shape hero and site), left out by default")
    ap.add_argument("--bg", choices=("dark", "black", "green", "transparent"), default="dark",
                    help="what is behind the unit and the cards (--shape hero and site): the dark of the website's picture (dark), "
                         "to composite over something else in an editor: black (the background is pure black and the unit and cards are "
                         "lifted by 4 levels (of 255), so a luma key takes only the background out), green (0x00ff00, for a chroma key, but "
                         "the unit has green pads), or transparent (a ProRes 4444 .mov with an alpha channel, very large). The site "
                         "shape's titles are in its picture, so these have none. The files have -black, -green or -alpha after the shape")
    ap.add_argument("--status", action="store_true",
                    help="the deck's status line (the state, MASTER / PHONES, the input level, the decks) as a thin strip of its own under "
                         "the unit and the cards (not --shape site and window: the window has it already). The files have -status after the shape")
    ap.add_argument("--no-link", action="store_true", help="no simulated decks (deckbench)")
    ap.add_argument("--from-raw", action="store_true", help="do not record again: make the picture from the last recording")
    args = ap.parse_args()
    episode = load_episode(args.episode)
    if args.usb_project:
        episode.USB_PROJECT = args.usb_project
    if getattr(episode, "STEPS", False) and (args.usb_project or args.project):      # the recording began with a project open
        episode.BARE = False
        episode.MIRROR_SETTINGS = bool(args.usb_project)
    if args.check:
        faults = check_episode(episode)
        for fault in faults:
            print("%s: %s" % (episode.NAME, fault))
        print("%s: %d scenes, %s" % (episode.NAME, len(getattr(episode, "SCENES", [])), "%d faults" % len(faults) if faults else "ok"))
        sys.exit(1 if faults else 0)
    if getattr(episode, "PATCH", False) and not args.patch and not args.from_raw:
        sys.exit("this episode shows the mods: give the mods' autoexec.bin with --patch")
    args.shape = args.shape or getattr(episode, "SHAPE", "portrait")
    set_shape(args.shape, args.res, args.grid, args.bg, args.status)
    out_dir = os.path.abspath(os.path.join(args.out, episode.NAME))
    # The hero shape has the list of mods beside the unit, so the app's screen is not given a page of it: it is another recording
    work = os.path.join(out_dir, "work-window" if args.shape == "window" else "work-hero" if args.shape in ("hero", "site") else "work")
    os.makedirs(work, exist_ok=True)
    raw = os.path.join(work, "raw.mp4")

    if not args.from_raw:
        record(args, episode, raw)
    plan = episode_plan(work)
    length = plan["length"]
    tl = plan["timeline"]
    top = args.top or getattr(episode, "TOP", "screen")
    tag = args.shape if args.shape in ("hero", "site", "window") else top + ("-wide" if args.shape == "landscape" else "")        # the files of the landscape picture have -wide after the look
    if args.res != "hd" and args.shape != "window":
        tag += "-" + args.res                              # reel-hero-2k.mp4 beside reel-hero.mp4
    if BG != "dark":
        tag += "-" + {"transparent": "alpha"}.get(BG, BG)
    if args.status and args.shape in ("portrait", "landscape", "hero"):
        tag += "-status"
    chain = captions(tl, length, episode, work) + end_card(episode, tl, length)
    clean = os.path.join(work, "clean-video" + EXT)
    base = clean
    if CLEAN_LAYOUTS and chain:                            # the text has room above the pictures, the clean video fills the height
        base = os.path.join(work, "captioned-video" + EXT)
        composite(raw, work, tl, length, args.fps, base, top)
    composite(raw, work, tl, length, args.fps, clean, top, CLEAN_LAYOUTS)
    master_sound(raw, work, os.path.join(work, "sound.m4a"))
    mux(os.path.join(work, "clean-video" + EXT), os.path.join(work, "sound.m4a"), os.path.join(out_dir, "reel-clean-%s%s" % (tag, EXT)))
    if chain:
        burn(base, os.path.join(work, "sound.m4a"), work, chain, os.path.join(out_dir, "reel-%s%s" % (tag, EXT)), args.fps)
    else:                                                  # no text anywhere (the site shape): the one picture is both
        shutil.copyfile(os.path.join(out_dir, "reel-clean-%s%s" % (tag, EXT)), os.path.join(out_dir, "reel-%s%s" % (tag, EXT)))
    write_srt(tl, length, os.path.join(out_dir, "reel.srt"))
    thumb = float(getattr(episode, "THUMB", 6.0))
    subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", "-ss", "%.2f" % thumb, "-i", os.path.join(out_dir, "reel-%s%s" % (tag, EXT)),
                           "-frames:v", "1", os.path.join(out_dir, "thumb-%s.png" % tag)])
    print("wrote %s (%.0f s)" % (os.path.join(out_dir, "reel-%s%s" % (tag, EXT)), length))


def end_card(episode, tl, length):
    """drawtext filters of the end card's lines, in the last layout ("end"): a black picture."""
    if SHAPE in ("site", "window"):
        return []
    segs = [s for s in layout_segments(tl, length) if s[2] == "end"]
    if not segs:
        return []
    t0, t1, _ = segs[0]
    card = getattr(episode, "END", [])
    chain, y = [], END_Y
    for text, size, colour in card:
        chain.append("drawtext=fontfile=font.ttf:text='%s':x=(w-text_w)/2:y=%d:fontsize=%d:fontcolor=%s:enable='between(t,%.2f,%.2f)'"
                     % (text.replace("'", "’").replace(":", "\\:"), y, int(round(size * SCALE)), colour, t0 + 0.2, t1))
        y += int(round(size * SCALE * 1.5))
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
    prepare(emu, args.patch, getattr(episode, "KIT", False), getattr(episode, "USB_PROJECT", ""), getattr(episode, "MOD_SETTINGS", None),
            stick=getattr(episode, "STEPS", False), mirror_settings=getattr(episode, "MIRROR_SETTINGS", False))
    mods = args.patch or getattr(episode, "STEPS", False)       # a played-back REC runs the mods that its stick holds
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
        if mods:
            regress.wait_patch(emu, s)
        if getattr(episode, "BARE", False):                   # a played-back REC: the unit as it boots, the steps load what they need
            pass
        elif getattr(episode, "KIT", False):                  # the generated kit (a project made from the test samples), not a factory one
            demo.load_kit(s)
        elif getattr(episode, "USB_PROJECT", ""):             # a project of your own, copied to the stick (see prepare)
            open_usb_project(s)
        else:
            open_internal_project(s, project_index(emu, args.project or getattr(episode, "PROJECT", "")))
        getattr(episode, "before", lambda s: None)(s)                       # off camera: what the first picture must already show

        cmd = [sys.executable, os.path.join(REPO, "app", "virtual_djs.py"), "--port", str(emu.port), "--mute",
               "--record", raw, "--fps", str(args.fps), "--face", args.face or getattr(episode, "FACE", "real")]
        # The size of the window: the layouts are measured on a big one (the app's screen is 800x480 in it), but the window shape
        # is the deck as it opens, whose screen and list of mods are as they are and the face as high as a desktop has room for
        cmd += ["--height", str(WINDOW_H)] if args.shape == "window" else ["--width", str(DECK_W), "--height", str(DECK_H)]
        # The unit's input: silence, or the simulated decks' sound when the episode records from them (INPUT = True, with deckbench)
        cmd += ["--input-tcp", "127.0.0.1:%d" % start.AUDIO_PORT] if bench and getattr(episode, "INPUT", False) else ["--no-input"]
        usb, modlist = emu.usb(), emu.modlist()
        if usb and mods:
            cmd += ["--usb", usb]
        if modlist and mods:
            cmd += ["--modlist", modlist]
        for suffix in (".start", ".stop", ".cmd", ".f32", ".f32p", ".rate"):
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
        ctx = Context(s, tl, bench, pages=args.shape not in ("hero", "site", "window"))
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
