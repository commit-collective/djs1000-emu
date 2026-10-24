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


SWITCHED = ["rec-quantize", "sample-names", "reverb-v2", "tempo-ducker"]       # four mods, one after the other down the list


def do_play(ctx):
    """The pattern plays and a few mods are switched off and on again, one at a time and not in a hurry: the pointer comes to a mod, its
    switch goes off for a moment, then on, and the pointer moves on. It ends on the mod whose text is under the list in the picture."""
    ctx.say("hover rec-length")
    ctx.wait(1.0)
    for mod in SWITCHED:
        ctx.say("hover " + mod)
        ctx.wait(0.5)
        ctx.say("toggle " + mod)                              # off
        ctx.wait(1.0)
        ctx.say("toggle " + mod)                              # and on again
        ctx.wait(0.7)
    ctx.say("hover rec-length")
    ctx.wait(1.0)
