# Releasing

A release is a tagged commit. It is source only: the emulator cannot ship anything of Pioneer DJ's, so there is no
file to build or attach. The GitHub release is made from the tag by `.github/workflows/release.yml`, with the
changelog's entry as its notes.

The emulator has its own version line (`v0.1.0`, ...), apart from the mods'. Tag it for what it changes for someone who
runs it. The mods repository's test report records which emulator commit its tests ran against. The emulator does not
name the mods.

## Before the tag

There is no CI (the emulator needs the firmware), so this is run by hand on the maintainer's machine:

1. `python tools/regress.py` (compare with the reference): every item the same.
2. `python tools/deck_selftest.py`: `ok`.
3. `scripts/setup.sh` from scratch into a throwaway home (`DJS_HOME=~/djs-fresh scripts/setup.sh UPD KEY`), then
   `DJS_HOME=~/djs-fresh scripts/run.sh 75` and see the app start. Delete the home.
4. `CHANGELOG.md`: rename "Not yet released" to `## vX.Y.Z` and say what changed for whoever runs the emulator (the
   workflow fails without an entry for the tag). Say which environment it was tried on (WSL2 on Ubuntu 24.04, Linux).

## The tag

```sh
git tag vX.Y.Z
git push && git push --tags      # a plain push does not send tags
```

The workflow creates the release. GitHub shows the line breaks of a release's notes, so `tools/release_notes.py` joins the lines of
each paragraph and list item. After a correction to the changelog, Actions, release notes, Run workflow writes the notes of a tag
again. Then the website's emulator page (`commitcollective.cc/djs1000/emulator/`) shows it
as the latest release by itself.

## Afterwards

A change to the emulator's code (`.py`, `.sh`, `.c`, `.h`, `.txt`) makes the mods' cached test results stale, since
their tests run against it: run the mods' gate again before the next mods release.
