# SPDX-License-Identifier: GPL-2.0-or-later
"""The website's picture of the emulator (tools/hero.py), to the pixel, with the pattern playing: no caption, nothing added. About
12 seconds. It is the generated test kit (the same as the picture's), not a factory project, so there is nothing of Pioneer's in it
but the app's own screen.

    python tools/reel.py hero --patch ../djs1000-mods/build/autoexec.bin

The picture behind is the website's own (SITE_HERO in tools/hero.py, by default in the website's repository beside this one), so
its titles and grid are the ones the website has. The video is 2168x1442 (the picture is 2167 wide).
"""
import regress

KIT = True                                  # the generated kit of tools/demo.py (load_kit), not a project of the internal storage
PATCH = True                                # the list of mods is in the picture
SHAPE = "site"
THUMB = 3.0

SCENES = [
    {"layout": "play", "caption": "", "sub": "", "do": "play", "seconds": 12.0},
]

HAT_TRACK, SNARE_TRACK, KICK_TRACK = 2, 1, 0


def steps(s, track, which):
    s.touch(*regress.TRACK[track])
    s.press(regress.HOME)
    for n in which:
        s.press(regress.STEP[n])


def before(s):
    """Off camera: a pattern with something to hear, the kick last so that its steps are the lit ones, as in the picture, and the
    project playing when the recording starts."""
    steps(s, HAT_TRACK, (2, 6, 10, 14))
    steps(s, SNARE_TRACK, (4, 12))
    steps(s, KICK_TRACK, (0, 4, 8, 12))
    s.settle()
    s.tap(regress.PLAY)
    s.pump(1.0)


MODS = ["input-select", "quick-sample", "rec-length", "rec-quantize", "loop-bounce", "sample-names", "fx-chain", "reverb-v2",
        "track-reverb", "tempo-ducker", "cue-tracks"]


def do_play(ctx):
    """The pattern plays and the list of mods is gone through: the pointer runs down it, then switches go off and on at random (the
    same ones every time), quickly, and all of them are on again at the end with the text of one mod under the list, as in the
    picture."""
    import random
    rng = random.Random(5)
    for mod in MODS:                                          # down the list
        ctx.say("hover " + mod)
        ctx.wait(0.25)
    off = set()
    for _ in range(16):                                       # and at random
        mod = rng.choice(MODS)
        ctx.say("hover " + mod)
        ctx.wait(0.12)
        ctx.say("toggle " + mod)
        off ^= {mod}
        ctx.wait(0.3)
    for mod in MODS:                                          # all on again
        if mod in off:
            ctx.say("hover " + mod)
            ctx.wait(0.1)
            ctx.say("toggle " + mod)
            ctx.wait(0.2)
    ctx.say("hover rec-length")
