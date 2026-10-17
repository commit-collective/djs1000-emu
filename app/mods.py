# SPDX-License-Identifier: GPL-2.0-or-later
"""The mods a patch carries, and which of them are on.

A patch that carries mods (the djs1000-mods project) holds the list of them, modlist.txt (JSON: a name, a line on
what it does and a status for each), next to its autoexec.sh; the emulator opens the patch at each start and the
list is there, in the run folder. That is the one list: this does not know any mod by name. Which of them are on
is djs1000-mods.cfg on the USB drive, a line a mod:

    name = on    # what it does

which the app reads again while it runs, so that changing on to off there, or back, takes effect at once. A mod
with no line is on, unless its status is "wip" (work in progress: off until the line says on, and the app has to
restart for it). No list, no mods: the firmware is stock, or the patch carries none.
"""
import json
import os
import re
import threading
import time

FILE = "djs1000-mods.cfg"
LINE = re.compile(r"^(\s*)([A-Za-z0-9_.-]+)(\s*=\s*)(on|off)\b(.*)$")


class Mods:
    def __init__(self, folder, modlist=None):
        self.path = os.path.join(folder, FILE) if folder else None
        self.modlist = modlist
        self.items = []                  # (name, on, what it does)
        self._seen = None
        if self.path and self.modlist:
            threading.Thread(target=self._watch, daemon=True).start()

    def _watch(self):
        # On Windows the folder is in WSL, and a look at it can take a while:
        # not in the drawing thread.
        while True:
            self.read()
            time.sleep(1.0)

    def _listed(self):
        """The mods of the patch, from its list; [] if there is none."""
        try:
            with open(self.modlist, encoding="utf-8", errors="replace") as f:
                return json.load(f).get("mods", [])
        except (OSError, ValueError):
            return []

    def read(self):
        try:
            seen = tuple((st.st_mtime, st.st_size) for st in (os.stat(self.modlist), self._stat_cfg()))
        except OSError:
            self._seen, self.items = None, []
            return
        if seen == self._seen:
            return
        mods = self._listed()
        state = {}
        try:
            with open(self.path, encoding="utf-8", errors="replace") as f:
                for line in f.read().splitlines():
                    m = LINE.match(line)
                    if m:
                        state[m.group(2)] = m.group(4) == "on"
        except OSError:
            pass                         # no file yet: the mods' own defaults
        items = []
        for mod in mods:
            wip = mod.get("status") == "wip"
            about = mod.get("about", "") + (" (work in progress)" if wip else " (beta)" if mod.get("status") == "beta" else "")
            items.append((mod["name"], state.get(mod["name"], not wip), about))
        self._seen, self.items = seen, items

    def _stat_cfg(self):
        try:
            return os.stat(self.path)
        except OSError:
            return os.stat(self.modlist)         # no settings yet: the list's own times will do

    def toggle(self, name):
        """Switches the mod on or off in the file (a line is added if there is none). False if it could not."""
        on_now = dict((n, on) for n, on, _ in self.items).get(name)
        if on_now is None:
            return False
        try:
            try:
                with open(self.path, encoding="utf-8", errors="replace", newline="") as f:
                    lines = f.read().split("\n")
            except OSError:
                lines = []
            for i, line in enumerate(lines):
                m = LINE.match(line.rstrip("\r"))
                if m and m.group(2) == name:
                    lines[i] = "%s%s%s%s%s" % (m.group(1), name, m.group(3), "off" if on_now else "on", m.group(5))
                    break
            else:
                if lines and lines[-1] == "":
                    lines.pop()
                lines.append("%s = %s" % (name, "off" if on_now else "on"))
                lines.append("")
            with open(self.path, "w", encoding="utf-8", newline="") as f:
                f.write("\n".join(lines))
        except OSError:
            return False
        self._seen = None
        self.read()
        return True
