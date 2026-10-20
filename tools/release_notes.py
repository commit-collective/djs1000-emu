#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""The release notes of a tag, for GitHub: the entry of CHANGELOG.md under `## TAG`, each paragraph and list item on one line.

    release_notes.py v0.1.0

GitHub shows the line breaks of a release's notes, and the changelog is wrapped at about 120 columns, so the lines are joined.
Fails if the changelog has no entry for the tag.
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def unwrap(text):
    """Markdown with each paragraph and list item on one line: GitHub shows the line breaks of a release's notes, the
    changelog is wrapped at about 120 columns, and a README does not show them."""
    out = []
    for line in text.split("\n"):
        if not line.strip():
            out.append("")
        elif line.startswith("- ") or not out or out[-1] == "":
            out.append(line)
        else:
            out[-1] += " " + line.strip()
    return "\n".join(out)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    tag = sys.argv[1]
    text = open(os.path.join(REPO, "CHANGELOG.md"), encoding="utf-8").read().replace("\r\n", "\n")
    found = re.search(r"^## %s\b[^\n]*\n(.*?)(?=^## |\Z)" % re.escape(tag), text, re.M | re.S)
    if not found or not found.group(1).strip():
        sys.exit("CHANGELOG.md has no entry for " + tag)
    print(unwrap(found.group(1).strip()))


if __name__ == "__main__":
    main()
