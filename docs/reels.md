# Reels: short vertical videos of the emulator

`tools/reel.py` makes a short video in 1080x1920 (for Reddit, Shorts, Reels and TikTok) the way `tools/demo.py` makes the long one:
a script plays the unit and the virtual deck records it. Run it on the host, like `start.py`.

    python tools/reel.py emulator_intro --patch ../djs1000-mods/build/autoexec.bin

It needs ffmpeg on the path, Pillow and pygame-ce for the deck, deckbench beside this repository (for the episodes that show
Pro DJ Link), and a copy of the unit's internal storage in WSL (below). The output goes in `DIR/NAME/`, where DIR is `--out`, else `demo/reels`. `demo/` is the one folder for what the tools generate (the
demonstration video as well), and git ignores it: videos are not committed, and these show the firmware's screen.

| file | what |
|---|---|
| `reel-clean-LOOK.mp4` | the picture and the sound with no text, for editing (LOOK is the top of the picture, see below: `screen` or `device`) |
| `reel-LOOK.mp4` | the same with the text of the scenes burned in |
| `reel.srt` | the text of the scenes, for a subtitle track |
| `thumb-LOOK.png` | a frame, for a cover |

The picture is 30 frames a second, h264, with the sound at -14 LUFS and its peaks under -1.5 dB. `--fps 60` makes it 60. `--from-raw`
makes the picture again from the last recording, which takes a minute where the recording takes four: use it to try a layout or a
caption.

## An episode

An episode is a file in `tools/reels` (`emulator_intro.py` is the first). It names the project to open, the scenes and what the
post says. A scene has a layout, a caption above the picture, a line below it, an action and the least time it lasts:

    {"layout": "play", "caption": "Pads, knobs, touch strip", "sub": "all of it works", "do": "pads", "seconds": 7.0}

`do` names a function `do_pads(ctx)` in the same file. It plays the panel through `ctx` (`press`, `touch`, `wait`, `say`, and
`ctx.s`, the session). Use `ctx.press` and `ctx.touch` while a project plays: the session's own waits for the screen to hold still,
which it never does then.

The layouts are in `tools/reel.py` (`LAYOUTS`) and cut regions out of the deck's window, which is recorded at 2196x1800 so that the
app's screen is 800x480 in it. The regions are measured on that window. A scene's `layout` is `play`, `mods` or `end` (black, for the
end card, `END` in the episode): `play` and `mods` are the same picture, so the unit never moves between them, and the name is for the
episode's own use.

## The top of the picture

The picture of every scene but the end card is one layout, which depends on a setting, `--top` (or `TOP` in the episode, `screen` if
neither):

| `--top` | the picture | the list of mods |
|---|---|---|
| `screen` | two framed cards with an even margin: the app's big screen, and the face of the unit under the bezel of its small screen | a page in the big screen |
| `device` | the unit as it is, its top and its small screen kept | a page in the unit's small screen, which is small in the picture, so the text is too |

The page of mods is drawn by the deck itself at the size of the unit's screen (800x480, in the style of its lists), when the scene
sends `page mods` and until `page off`: nothing is cut out and pasted, and nothing in the picture moves when it comes up. The
recording is the same for both looks, but only a recording made with `page mods` in its scene has the page, so `--from-raw --top ...`
works on a recording made after that.

## The unit's internal storage

The episodes open a factory project from the unit's internal storage. Copy it off a unit of your own with the `--dump-emmc` patch of
djs1000-mods, put the `PIONEER DJ SAMPLER` folder in `~/djs/emmc-src` in WSL (or name another place in `$DJS_EMMC_SRC`), and each
reel starts on a fresh set of it: hard links to those files, with copies of `Projects`, `Scenes` and `System`. See
[emulation.md](emulation.md). The factory content is Pioneer's and the sample packs' makers'. It stays out of this repository, and
whether to show it in a video is for the person who posts the video to decide.
