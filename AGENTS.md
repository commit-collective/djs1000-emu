# djs1000-emu: working rules

- This repo is public. Its docs and code comments stay high level: byte-level protocols are fine, but no firmware addresses,
  no Ghidra symbols (`FUN_...`) and no cipher details. Those are kept outside the repo.
- Firmware and anything unpacked from it never go in any repo.
- Media (videos, renders) is never committed. Reels are generated into the git-ignored `demo/` folder, and personal episodes
  stay in `demo/episodes`.
- Commit on main. Ask before pushing, and never amend a pushed commit.
- The hero picture of the README and the website (`public/djs1000/emulator/hero.png` in the website repo) is made by
  `tools/hero_scene.py` then `tools/hero.py`. When the look of the deck changes, run both and commit the new picture in the
  website repo, not here. The README links to it there.
