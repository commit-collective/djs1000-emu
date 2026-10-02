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


def main():
    pygame.init()
    link = FakeLink()
    for size in ((1627, 1060), (700, 900), (420, 500)):
        deck = virtual_djs.Deck(link, size, (FakePlayer(), None), None, [0])
        deck.pump()
        deck.draw()
        k = deck.scale
        points = [((key.bounds()[0] + key.bounds()[2]) / 2 * k, (key.bounds()[1] + key.bounds()[3]) / 2 * k)
                  for key in L.KEYS]
        points += [(knob.circle[0] * k, knob.circle[1] * k) for knob in L.KNOBS]
        points += [(L.SLIDER[0] * k, (L.SLIDER[1] + 40) * k), deck.listen_rect.center,
                   deck.lcd_rect.center]
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
            deck.motion((pos[0] - 5, pos[1] + 400))
            deck.draw()
        for key in list(deck.keymap) + [pygame.K_TAB]:
            for mod in (0, pygame.KMOD_RSHIFT):
                e = pygame.event.Event(pygame.KEYDOWN, key=key, mod=mod)
                deck.key(e, True)
                deck.key(pygame.event.Event(pygame.KEYUP, key=key, mod=mod), False)
        deck.switch_output()
        deck.draw()
    print(len(link.sent), "commands sent; ok")


if __name__ == "__main__":
    main()
