# SPDX-License-Identifier: GPL-2.0-or-later
"""The fake Pro DJ Link decks the deck's side panel switches.

Four fake CDJs (tools/fakedecks.py, run in the emulator's network by
start.py) announce themselves and answer the track database, so that what
reads Pro DJ Link in the emulated unit (the app, a mod) has decks to see.
This is the switch panel's side of it: a file, JSON {"1": true, ...}, that
the fake decks look at twice a second; this reads it, and rewrites it when a
switch is clicked. No file (no helper running): no switches.
"""
import json
import os
import threading
import time

COUNT = 4


class FakeDecks:
    def __init__(self, path):
        self.path = path
        self.on = [False] * COUNT
        self._seen = None
        if path:
            threading.Thread(target=self._watch, daemon=True).start()

    def available(self):
        return bool(self.path)

    def _watch(self):
        # On Windows the file is in WSL, and a look at it can take a while:
        # not in the drawing thread.
        while True:
            self.read()
            time.sleep(1.0)

    def read(self):
        try:
            st = os.stat(self.path)
            seen = (st.st_mtime, st.st_size)
            if seen == self._seen:
                return
            with open(self.path, encoding="utf-8") as f:
                wanted = json.load(f)
        except (OSError, ValueError):
            return
        self._seen = seen
        self.on = [bool(wanted.get(str(n + 1))) for n in range(COUNT)]

    def toggle(self, number):
        """Switches deck `number` (1-4). False if the file could not be written."""
        on = list(self.on)
        on[number - 1] = not on[number - 1]
        try:
            with open(self.path, "w", encoding="utf-8", newline="\n") as f:
                json.dump({str(n + 1): on[n] for n in range(COUNT)}, f)
        except OSError:
            return False
        self.on = on
        self._seen = None
        return True
