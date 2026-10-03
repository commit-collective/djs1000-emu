# SPDX-License-Identifier: GPL-2.0-or-later
"""The mods a patch on the USB drive carries, and which of them are on.

A patch that carries mods (the djs1000-mods project) keeps their settings in
djs1000-mods.cfg on the drive, a line a mod:

    name = on    # what it does

and reads it again while the app runs, so that changing on to off there, or
back, takes effect at once. This reads that file from the emulator's USB
folder and rewrites a line when asked; it knows nothing else of the mods. No
file, no mods: the firmware is stock, or the patch carries none.

One mod has a control of its own here: cue-tracks takes the tracks to cue
from a file in the unit's memory, /tmp/djs1000-mods/cue (track numbers 1-16,
separated by spaces), until it has controls on the panel. Given the folder
that is the emulator's /tmp, this reads and writes that file too.
"""
import os
import re
import threading
import time

FILE = "djs1000-mods.cfg"
LINE = re.compile(r"^(\s*)([A-Za-z0-9_.-]+)(\s*=\s*)(on|off)\b(.*)$")


CUE_MOD = "cue-tracks"
TRACKS = 16


class Mods:
    def __init__(self, folder, tmp=None):
        self.path = os.path.join(folder, FILE) if folder else None
        self.cue_path = os.path.join(tmp, "djs1000-mods", "cue") if tmp else None
        self.items = []                  # (name, on, what it does)
        self.cued = set()                # tracks 1-16
        self._seen = None
        if self.path:
            threading.Thread(target=self._watch, daemon=True).start()

    def _watch(self):
        # On Windows the folder is in WSL, and a look at it can take a while:
        # not in the drawing thread.
        while True:
            self.read()
            self.read_cue()
            time.sleep(1.0)

    def read(self):
        try:
            st = os.stat(self.path)
            seen = (st.st_mtime, st.st_size)
            if seen == self._seen:
                return
            with open(self.path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            self._seen, self.items = None, []
            return
        items = []
        for line in text.splitlines():
            m = LINE.match(line)
            if m:
                items.append((m.group(2), m.group(4) == "on", m.group(5).strip(" \t#")))
        self._seen, self.items = seen, items

    def can_cue(self):
        """Whether the cue buttons mean anything: the mod is there and on, and
        its folder in the emulator's /tmp exists (the patch is loaded)."""
        return (bool(self.cue_path) and any(n == CUE_MOD and on for n, on, _ in self.items)
                and os.path.isdir(os.path.dirname(self.cue_path)))

    def read_cue(self):
        if not self.cue_path:
            return
        try:
            with open(self.cue_path, encoding="ascii", errors="replace") as f:
                words = f.read().split()
        except OSError:
            words = []
        self.cued = {int(w) for w in words if w.isdigit() and 1 <= int(w) <= TRACKS}

    def toggle_cue(self, track):
        """Cues the track, or takes it off the cue. False if it could not."""
        cued = set(self.cued) ^ {track}
        try:
            with open(self.cue_path, "w", encoding="ascii", newline="") as f:
                f.write(" ".join(str(t) for t in sorted(cued)) + "\n")
        except OSError:
            return False
        self.cued = cued
        return True

    def toggle(self, name):
        """Switches the mod on or off in the file. False if it could not."""
        try:
            with open(self.path, encoding="utf-8", errors="replace", newline="") as f:
                lines = f.read().split("\n")
            for i, line in enumerate(lines):
                m = LINE.match(line.rstrip("\r"))
                if m and m.group(2) == name:
                    on = m.group(4) != "on"
                    lines[i] = "%s%s%s%s%s" % (m.group(1), name, m.group(3),
                                               "on" if on else "off", m.group(5))
                    break
            else:
                return False
            with open(self.path, "w", encoding="utf-8", newline="") as f:
                f.write("\n".join(lines))
        except OSError:
            return False
        self._seen = None
        self.read()
        return True
