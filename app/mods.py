# SPDX-License-Identifier: GPL-2.0-or-later
"""The mods a patch on the USB drive carries, and which of them are on.

A patch that carries mods (the djs1000-mods project) keeps their settings in
djs1000-mods.cfg on the drive, a line a mod:

    name = on    # what it does

and reads it again while the app runs, so that changing on to off there, or
back, takes effect at once. This reads that file from the emulator's USB
folder and rewrites a line when asked; it knows nothing else of the mods. No
file, no mods: the firmware is stock, or the patch carries none.
"""
import os
import re
import threading
import time

FILE = "djs1000-mods.cfg"
LINE = re.compile(r"^(\s*)([A-Za-z0-9_.-]+)(\s*=\s*)(on|off)\b(.*)$")


class Mods:
    def __init__(self, folder):
        self.path = os.path.join(folder, FILE) if folder else None
        self.items = []                  # (name, on, what it does)
        self._seen = None
        if self.path:
            threading.Thread(target=self._watch, daemon=True).start()

    def _watch(self):
        # On Windows the folder is in WSL, and a look at it can take a while:
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
