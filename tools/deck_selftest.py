#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Presses, drags and releases the mouse on every control of the virtual deck
and at a grid of points across its window, with no app and no real window:
whatever the mouse does must not raise.

    python tools/deck_selftest.py

Prints the commands' count and "ok". Needs pygame-ce and Pillow.
"""
import os
import sys

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "app"))

import pygame  # noqa: E402

import art  # noqa: E402
import layout as L  # noqa: E402
import virtual_djs  # noqa: E402


class FakeLink:
    connected = True
    addr = ("test", 0)

    def __init__(self):
        self.sent = []

    def send(self, line):
        self.sent.append(line)

    def take(self):
        return [("up",), ("lamps", bytes(range(128))), ("down",)]


class FakePlayer:
    name = "test device"

    def reset(self):
        pass


def sweep_art():
    """The face and every sprite at many sizes of window, in the style set: a shape that is less than a pixel at a small size
    must not raise (a window the size of the user's did, once)."""
    for scale in (0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.7, 0.8, 0.9, 1.0, 1.2, 1.5):
        art.face(scale)
        for i in range(len(L.KEYS)):
            for level, rgb, down in ((0, None, False), (2, None, True), (0, (250, 120, 40), False)):
                art.key_sprite(i, scale, level, rgb, down)
        for i in range(len(L.KNOBS)):
            art.knob_sprite(i, scale, 3, False)
            art.knob_sprite(i, scale, 3, True)
        art.slider_cap(scale)


def main():
    pygame.init()
    link = FakeLink()
    for style in ("flat", "real"):
        art.set_style(style)
        sweep_art()
        deck_checks(link)
    print(len(link.sent), "commands sent; ok")


def deck_checks(link):
    for size in ((1627, 1060), (700, 900), (420, 500)):
        deck = virtual_djs.Deck(link, size, (FakePlayer(), None), None, [0])
        deck.pump()
        deck.draw()
        k, ox = deck.scale, deck.ox                      # the unit begins ox from the window's edge
        points = [((key.bounds()[0] + key.bounds()[2]) / 2 * k + ox, (key.bounds()[1] + key.bounds()[3]) / 2 * k)
                  for key in L.KEYS]
        points += [(knob.circle[0] * k + ox, knob.circle[1] * k) for knob in L.KNOBS]
        points += [(L.SLIDER[0] * k + ox, (L.SLIDER[1] + 40) * k), deck.listen_rect.center,
                   deck.lcd_rect.center, ((L.STRIP[0] + 50) * k + ox, (L.STRIP[1] + 100) * k)]
        if deck.dock:
            points.append(deck.dock.center)
        points += [(x, y) for x in range(0, size[0], 53) for y in range(0, size[1], 47)]
        for x, y in points:
            pos = (int(x), int(y))
            deck.motion(pos)
            deck.press(pos)
            deck.motion((pos[0] + 9, pos[1] - 23))
            deck.wheel(pos, 1)
            deck.release((pos[0] + 9, pos[1] - 23))
            if deck.find(pos) == ("strip",):
                deck.pin(pos)
                deck.draw()
                deck.pin(pos)
            deck.motion((pos[0] - 5, pos[1] + 400))
            deck.draw()
        for key in list(deck.keymap) + [pygame.K_TAB]:
            for mod in (0, pygame.KMOD_RSHIFT):
                e = pygame.event.Event(pygame.KEYDOWN, key=key, mod=mod)
                deck.key(e, True)
                deck.key(pygame.event.Event(pygame.KEYUP, key=key, mod=mod), False)
        deck.switch_output()
        deck.draw()
        for step in (deck.toggle_lamps, deck.toggle_dock, deck.toggle_dock, deck.toggle_lamps):
            step()
            deck.draw()
        deck.have_screen = False
        deck.draw()
        deck.up_at = None
        deck.draw()


if __name__ == "__main__":
    main()
