# SPDX-License-Identifier: GPL-2.0-or-later
"""The fake Pro DJ Link decks the deck's side panel switches.

Three fake CDJs (tools/fakedecks.py, run in the emulator's network by
start.py) announce themselves and answer the track database, so that what
reads Pro DJ Link in the emulated unit (the app, a mod) has decks to see. They
are players 2 to 4: the emulated unit is player 1 (its PLAYER No.), and a deck
with the same number would be a clash on the network, and no linked players.

Each deck has four switches: ON (it is on the network), PLAY, SYNC and MASTER
(the tempo master). This is the panel's side of it: a file, JSON {"2":
{"on": 0, "play": 0, "sync": 0, "master": 0}, ...}, that the fake decks look at
twice a second, where a number that changes is a click on that switch; and the
file the fake decks write back (the same name and ".state") with what each deck
really is, since the master role can pass to another player by itself (the
unit asks for it). This reads the second to show it, and rewrites the first
when a switch is clicked. No file (no helper running): no switches.
"""
import json
import os
import threading
import time

FIRST = 2                                # the number of the first fake deck
COUNT = 3
WHAT = ("on", "play", "sync", "master")


class FakeDecks:
    def __init__(self, path):
        self.path = path
        self.state = {n: {"on": False, "play": False, "sync": False, "master": False, "bpm": 0.0}
                      for n in range(FIRST, FIRST + COUNT)}
        self.clicks = {n: {w: 0 for w in WHAT} for n in range(FIRST, FIRST + COUNT)}
        self._seen = None
        if path:
            self._read_clicks()
            threading.Thread(target=self._watch, daemon=True).start()

    def available(self):
        return bool(self.path)

    def on(self, number):
        return self.state[number]["on"]

    def _watch(self):
        # On Windows the files are in WSL, and a look at them can take a while:
        # not in the drawing thread.
        while True:
            self.read()
            time.sleep(0.5)

    def _read_clicks(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                wanted = json.load(f)
        except (OSError, ValueError):
            return
        for n in self.clicks:
            mine = wanted.get(str(n))
            if isinstance(mine, dict):
                for w in WHAT:
                    self.clicks[n][w] = max(self.clicks[n][w], int(mine.get(w, 0)))

    def read(self):
        """What the decks are now (the helper's file)."""
        try:
            path = self.path + ".state"
            st = os.stat(path)
            seen = (st.st_mtime, st.st_size)
            if seen == self._seen:
                return
            with open(path, encoding="utf-8") as f:
                state = json.load(f)
        except (OSError, ValueError):
            return
        self._seen = seen
        for n in self.state:
            mine = state.get(str(n))
            if isinstance(mine, dict):
                self.state[n].update({k: mine[k] for k in ("on", "play", "sync", "master", "bpm")
                                      if k in mine})

    def click(self, number, what):
        """A click on switch `what` of deck `number`. False if the file could
        not be written."""
        self.clicks[number][what] += 1
        try:
            with open(self.path, "w", encoding="utf-8", newline="\n") as f:
                json.dump({str(n): c for n, c in self.clicks.items()}, f)
        except OSError:
            return False
        return True
