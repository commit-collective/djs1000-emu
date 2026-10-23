# Reels: short vertical videos of the emulator

`tools/reel.py` makes a short video in 1080x1920 (for Reddit, Shorts, Reels and TikTok) the way `tools/demo.py` makes the long one:
a script plays the unit and the virtual deck records it. Run it on the host, like `start.py`.

    python tools/reel.py example

It needs ffmpeg on the path, Pillow and pygame-ce for the deck, deckbench beside this repository (for the episodes that show
Pro DJ Link, and `--patch` for the mods), and a copy of the unit's internal storage in WSL (below). The output goes in `DIR/NAME/`, where DIR is `--out`, else `demo/reels`. `demo/` is the one folder for what the tools generate (the
demonstration video as well), and git ignores it: videos are not committed, and these show the firmware's screen.

| file | what |
|---|---|
| `reel-clean-LOOK.mp4` | the picture and the sound with no text, for editing (LOOK is the top of the picture, see below: `screen` or `device`, with `-wide` after it for `--shape landscape`) |
| `reel-LOOK.mp4` | the same with the text of the scenes burned in |
| `reel.srt` | the text of the scenes, for a subtitle track |
| `thumb-LOOK.png` | a frame, for a cover |

An episode can record from the simulated decks: `INPUT = True` (with `LINK = True`) feeds the unit's input with their sound (deckbench's
audio port, which `start.py` now starts the bench with), so a scene can do live sampling: the IN meter moves, a pad hit records a take
of the deck, and the pad plays it back. The input monitor plays in the unit's headphones, not on the master, so a reel mixes the
headphones into its sound (they are silent otherwise).

The picture is 30 frames a second, h264, with the sound at -14 LUFS and its peaks under -1.5 dB. `--fps 60` makes it 60. `--from-raw`
makes the picture again from the last recording, which takes a minute where the recording takes four: use it to try a layout or a
caption.

`--shape landscape` makes a 1920x1080 picture (Reddit, YouTube) from the same recording: the face on the left and the app's screen on
the right, in both looks (in `device`, the unit as it is, with its small screen, and the big screen as large as the room allows). Its
files have `-wide` after the look (`reel-screen-wide.mp4`), so both shapes sit in the one folder.

`--shape hero` is 1920x1080 in the look of the website's picture (`tools/hero.py`): the unit on a dark grid with nothing round it, and
on its right the app's screen above the list of mods, each in a thin frame with rounded corners as in that picture, with the caption over the cards. It ignores `--top` and
writes `reel-hero.mp4`. The list of mods is beside the unit, so the app's screen is not given a page of it (`page` commands are
not sent) and it is recorded on its own, in `work-hero`.

`--shape window` is the deck's whole window as it is, at the size it was recorded at (2196x1800): the unit, the app's screen, the list of mods
and the status line, with no layout, no caption and no end card, and it writes `reel-window.mp4`. Like `hero` and `site`, the list of mods
is the panel beside the unit and not a page on its screen, so it is recorded on its own (`work-hero`).

`--shape site` is that picture itself, to the pixel (2168x1442, as the picture is 2167 wide): the website's `hero.png` is the background
with the unit taken out, so its titles, grid and frames are exactly the website's, and the unit, the app's screen and the list of
mods are put where the picture has them, with the same rounded corners. There is no text. `tools/reels/hero.py` is the episode for it
(`python tools/reel.py hero --patch ...`): the generated test kit of the picture, with a pattern that plays for 12 seconds while the list of mods is gone through and switches go off and on. It needs the
website's repository beside this one (`SITE_HERO` in `tools/hero.py`).

## An episode

An episode is a Python file. [`tools/reels/example.py`](../tools/reels/example.py) is the one to start from: copy it to
`demo/episodes/`, which git ignores, so your episodes and what you post with them stay yours. `reel.py NAME` looks in
`demo/episodes` and then in `tools/reels`, and `reel.py path/to/file.py` takes any file. `--check` loads an episode and looks at its
scenes (a layout that does not exist, an action with no function) without recording, so it needs no unit. `--project` opens another
project than the episode's `PROJECT` (no name is the first in the list).

An episode names the project to open and the scenes. A scene has a layout, a caption above the picture, a line below it, an action
and the least time it lasts:

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
