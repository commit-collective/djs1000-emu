# djs1000-emu: working rules

- This repo is public. Its docs and code comments stay high level: byte-level protocols are fine, but no firmware addresses,
  no Ghidra symbols (`FUN_...`) and no cipher details. Those are kept outside the repo.
- Firmware and anything unpacked from it never go in any repo.
- Media (videos, renders) is never committed. Reels are generated into the git-ignored `demo/` folder, and personal episodes
  stay in `demo/episodes`.
- Always commit completed changes locally on main. Ask before pushing, tagging or deploying, and never amend a pushed commit.

## Make and verify changes

- Read the README, then only the relevant documents. Running and platform
  details are in `docs/running.md`, the agent-facing TCP client in
  `tools/session.py`, and architecture in `docs/emulation.md`.
- Keep the README a first-run guide. Put command catalogues and implementation
  detail in the relevant document. Do not describe untested platforms as either
  working or impossible. Distinguish main, the latest tag and the live site.
- Before launching or stopping anything, check for an active test or recording
  session. Do not overlap them or stop processes owned by another session.
  Use `python start.py stop`, never a blanket process kill.
- Use `python start.py --no-deck` for scripted work. Changing the virtual deck
  calls for `python tools/deck_selftest.py`. Backend changes call for the
  relevant scripted checks and regression. Doc-only work does not require
  starting the firmware. Say what was and was not validated on hardware.
- Keep setup destructive operations inside a resolved, dedicated workspace.
  Preserve existing settings and backups. Exercise rejection paths without
  using real firmware before trying an extraction.
  Run `python3 tools/test_setup.py` in Linux or WSL after setup changes.
- Commit subjects start with an action verb and stay under 50 characters.
  A body is optional, otherwise use a blank line and lines under 72 characters.
  No semicolons in prose, emojis or attribution. Omit routine check boilerplate,
  but name CI or test changes when they are the purpose of the commit.
- The hero picture of the README and the website (`public/djs1000/emulator/hero.png` in the website repo) is made by
  `tools/hero_scene.py` then `tools/hero.py`. When the look of the deck changes, run both and commit the new picture in the
  website repo, not here. The README links to it there.
