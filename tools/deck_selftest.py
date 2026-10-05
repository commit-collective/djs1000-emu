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


def check_fake_decks(link):
    """The side panel's switches of the fake Pro DJ Link decks write the file
    the helper reads, and show what is in it."""
    import json
    import tempfile

    import prolink

    path = os.path.join(tempfile.mkdtemp(), "fakedecks.json")
    deck = virtual_djs.Deck(link, (1627, 1060), (FakePlayer(), None), None, [0],
                            decks=prolink.FakeDecks(path))
    deck.pump()
    deck.draw()
    assert len(deck.deck_rects) == 4 * prolink.COUNT, "no switches for the fake decks"
    for rect, number, what in deck.deck_rects:
        pos = rect.center
        assert deck.find(pos) == ("deck", number, what)
        deck.press(pos)
        deck.release(pos)
    clicks = json.load(open(path))
    assert clicks == {str(n): {w: 1 for w in prolink.WHAT}
                      for n in range(prolink.FIRST, prolink.FIRST + prolink.COUNT)},         "switches did not write"
    rect, number, what = deck.deck_rects[5]
    deck.press(rect.center)
    deck.release(rect.center)
    assert json.load(open(path))[str(number)][what] == 2
    deck.draw()


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
                   deck.lcd_rect.center, ((L.STRIP[0] + 50) * k, (L.STRIP[1] + 100) * k)]
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
    check_fake_decks(link)
    print(len(link.sent), "commands sent; ok")


if __name__ == "__main__":
    main()
