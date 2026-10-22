# SPDX-License-Identifier: GPL-2.0-or-later
"""An episode to start from: a title, a few pad hits and an end card, about 12 seconds. Copy it to demo/episodes (git ignores that
folder, so your own episodes and what you post with them stay yours) and change it:

    python tools/reel.py example --check            looks at the scenes, needs no unit
    python tools/reel.py example                    records it
    python tools/reel.py demo/episodes/mine.py      one of your own, by its path (or by its name, mine)

A scene is a layout (see LAYOUTS in tools/reel.py), a caption above the picture, a line below it, the function that plays the panel
while it shows (do NAME is do_NAME below) and how long it lasts at least. The text is also written to reel.srt for an editor.
Other settings, all optional: PATCH = True (needs the mods' autoexec.bin, --patch), LINK = True (starts deckbench's simulated
decks, bench is then ctx.bench), FACE, TOP, THUMB (the second of the cover) and END (the lines of the end card).
"""
import regress

PROJECT = ""                                # a project on the unit's internal storage, by name. Empty is the first in the list

SCENES = [
    {"layout": "play", "caption": "A title", "sub": "and a line under it", "seconds": 3.0},
    {"layout": "play", "caption": "Pads", "sub": "played by a script", "do": "pads", "seconds": 6.0},
    {"layout": "end", "caption": "", "sub": "", "seconds": 3.0},
]

END = [("Your name", 90, "white"), ("and a line", 46, "0xb4b4b4")]    # text, size, colour

KICK, SNARE, HAT = 0, 1, 2                  # the pads of the first three tracks of a project


def before(s):
    """Off camera, so that the first picture and the first sound are of the project playing."""
    s.tap(regress.PLAY)
    s.pump(1.0)


def do_pads(ctx):
    """The pattern stops and three pads are hit. Use ctx.press and ctx.touch while a project plays (the session's own wait for the
    screen to hold still, which it never does then), and give the unit a moment after each press."""
    ctx.press(regress.STOP)
    ctx.wait(0.7)
    for pad, gap in ((KICK, 0.6), (SNARE, 0.6), (HAT, 0.4)):
        ctx.s.pad(pad, hold=0.2)
        ctx.wait(gap)
