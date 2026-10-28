---
name: release
description: Prepare a release of the DJS-1000 emulator (checks, changelog, tag). Use when asked to release, tag or cut a version of djs1000-emu. Prepares everything and stops before the tag and the push to ask.
---

# Release the emulator

The procedure is in `docs/releasing.md`: read it first. A release is a tagged commit, source only: there is nothing to build or attach,
and nothing of Pioneer's may go anywhere. **Do not tag or push until the user says so.**

## Steps

1. Clean tree on `main`, no reel or other agent using the emulator. `python start.py stop`.
2. `python tools/regress.py`: every item the same as the reference. `python tools/deck_selftest.py`: ok.
3. A fresh setup: `DJS_HOME=~/djs-fresh scripts/setup.sh UPD KEY` into a throwaway home, then `DJS_HOME=~/djs-fresh scripts/run.sh 75`
   and see the app start. Delete that home afterwards. The key is the user's: never print it or write it anywhere.
4. **`CHANGELOG.md`.** Rename "Not yet released" to `## vX.Y.Z` (the workflow fails without an entry for the tag). Write what
   changed for whoever runs the emulator, and the environment it was tried on (WSL2, Ubuntu 24.04). Plain short sentences,
   wrapped near 120 columns, no semicolons. Check the docs and comments hold no firmware address, no Ghidra symbol and no
   cipher detail: this repo is public.
5. **Ask, then tag and push:** `git tag vX.Y.Z`, `git push`, `git push --tags` (a plain push does not send tags). The workflow
   makes the GitHub release from the changelog entry, with the lines of each paragraph joined by `tools/release_notes.py`.
   To write the notes of a tag again after a changelog fix: Actions, release notes, Run workflow.

## Afterwards

The emulator has its own version line, apart from the mods'. A change to its code (`.py`, `.sh`, `.c`, `.h`, `.txt`) makes the mods'
cached test results stale: tell the user to run the mods' gate again before the next mods release. The website's emulator page
shows the new release by itself.
