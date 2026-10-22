#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Makes the hero picture of the README and the website from a picture of the deck, keeping the layout of the one it replaces.

    hero.py [--scene demo/hero/deck.png] [--template HERO.png] [--out HERO.png]

The picture has three cards on a dark grid: the deck on the left, the app's screen and the list of mods on the right, with a
title over each of the two. It is made on the picture it replaces (--template, by default the website's, which is also where it is
written): the titles, the grid and the frames stay, and the three cards are replaced by what tools/hero_scene.py saved. So nothing
moves from one version to the next, and a new look of the deck is a new scene and one run of this.

Needs Pillow. Nothing here is committed: the picture shows the firmware's screen.
"""
import argparse
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SITE_HERO = os.path.join(REPO, "..", "commitcollective.cc", "public", "djs1000", "emulator", "hero.png")

# Where the three cards are in the picture (x0, y0, x1, y1, as the last version has them), and what of the deck's window (2196x1800)
# goes in each.
DECK_AT = (110, 110, 1086, 1331)
SCREEN_AT = (1176, 154, 2058, 685)             # with the frame the last version had, which is covered and drawn again
MODS_AT = (1176, 785, 2058, 1332)
FRAME = (46, 46, 46)                         # the frame of a card: one dim line, the same on all four sides
DECK_FROM = (0, 25, 1358, 1754)              # the unit, from the top of the housing to the foot of the case
SCREEN_FROM = (1380, 16, 2178, 494)          # the app's screen, inside the frame the deck draws round it, and less its last column and row
#                                              (the app's frame has them light grey: a bright line along two sides)
MODS_FROM = (1380, 515, 2180, 1015)          # the list of mods and the text of the one pointed at


def outside(img):
    """A mask of what is round the unit: the black joined to the picture's corners (the screen is black inside, so not all black)."""
    flood = img.convert("L").point(lambda v: 255 if v <= 1 else 0)
    w, h = flood.size
    for corner in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if flood.getpixel(corner) == 255:
            ImageDraw.floodfill(flood, corner, 128)
    return flood.point(lambda v: 255 if v == 128 else 0)


def clear_background(base, box):
    """Puts back what the picture has behind the deck (a vignette and a grid of lines every 64 pixels) where the deck was."""
    px = base.load()
    x0, y0, x1, y1 = box
    lx, rx = x0 - 8, x1 + 6                                   # a column beside the box on each side, off the grid lines
    for y in range(y0, y1):
        a, b = px[lx, y][0], px[rx, y][0]
        for x in range(x0, x1):
            v = a + (b - a) * (x - lx) / float(rx - lx)
            if x % 64 == 0 or y % 64 == 0:
                v += 4
            v = int(round(v))
            px[x, y] = (v, v, v + 1)


def rounded(size, radius):
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def card(base, scene, source, at, radius=0):
    w, h = at[2] - at[0], at[3] - at[1]
    part = scene.crop(source).resize((w, h), Image.LANCZOS)
    base.paste(part, at[:2], rounded((w, h), radius) if radius else None)
    ImageDraw.Draw(base).rounded_rectangle((at[0], at[1], at[2] - 1, at[3] - 1), radius=radius, outline=FRAME, width=1)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scene", default=os.path.join(REPO, "demo", "hero", "deck.png"))
    ap.add_argument("--template", default=SITE_HERO)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    out = args.out or args.template
    base = Image.open(args.template).convert("RGB")
    scene = Image.open(args.scene).convert("RGB")

    unit = scene.crop(DECK_FROM).resize((DECK_AT[2] - DECK_AT[0], DECK_AT[3] - DECK_AT[1]), Image.LANCZOS)
    clear_background(base, DECK_AT)
    base.paste(unit, DECK_AT[:2], outside(unit).point(lambda v: 255 - v))     # the background shows round the unit
    card(base, scene, SCREEN_FROM, SCREEN_AT, 6)
    card(base, scene, MODS_FROM, MODS_AT, 6)
    base.save(out)
    print("wrote", os.path.abspath(out), base.size)


if __name__ == "__main__":
    main()
