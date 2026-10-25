#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""The virtual DJS-1000: the running app drawn as the machine, in one window.

    python app/virtual_djs.py [options]       (--help lists them all)

    --host, --port        where the emulator is (127.0.0.1, 7310)
    --audio, --no-audio, --mute, --listen, --headphones, --list-audio, --audio-buffer, --audio-block
                          the sound out (docs/virtual-deck.md)
    --input, --input-tcp, --no-input
                          the sound in
    --compact, --height, --width, --face, --no-outline, --key
                          how the window looks (--key: black round it, for keying a recording)
    --usb, --modlist, --hover
                          the list of mods
    --record, --fps, --snapshot
                          a video or a picture of the window

Start the app first (scripts/run.sh). The window shows it as soon as it is
there, and again after a restart. The face's screen is the app's own, its
lamps are the ones the app lights, and its controls go to the app as the
panel's would:

  keys, pads       hold the mouse button. A pad plays harder the lower you
                   press it
  knobs, selector  mouse wheel, or drag up and down. A click pushes the
                   selector
  screen           the mouse is a finger, on the face and on the large copy
  keyboard         the keys printed in the status line under the mouse

The main sound device (the system's default, or the one whose name contains
--audio's NAME) plays the master output or the headphone output: the MASTER /
PHONES switch in the status line, or Tab, chooses. --headphones names a
second device that plays the headphone output all the time. The app's input is fed from the system's
default recording device, or --input's. --list-audio prints the devices.

Beside the face is the app's screen at full size, which is the easier one
to touch, with a reminder of the keys under it. F10 hides that panel
(--compact starts without it). F12 swaps the reminder for every two-level
lamp by id, as the app sets it (docs/panel-protocol.md).

Needs pygame-ce and Pillow (requirements.txt).
"""

import argparse
import array
import math
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("SDL_WINDOWS_DPI_AWARENESS", "permonitorv2")

import pygame  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import art  # noqa: E402
import audio  # noqa: E402
import layout as L  # noqa: E402
from link import Link  # noqa: E402
from mods import Mods  # noqa: E402
from capture import Capture  # noqa: E402

CAPTURES = os.path.join(os.path.dirname(HERE), "demo", "captures")      # where REC puts its files (demo/ is git-ignored: media is never committed)

TITLE = "Virtual DJS-1000"
BG = (5, 5, 5)
DOCK_PAD = 16
SECTION_GAP = 18                         # between the large screen and the mods, and between the sections of the side panel (a recording keeps 8)
STATUS_H = 26
MENU_ROW, MENU_W = 24, 252              # the tools menu: a row, and its width
VELOCITIES = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, None]      # the pad velocity setting: a share, or None for by where on the pad
BENCH_URL = "http://127.0.0.1:8750/"     # where deckbench's page is (start.py starts it there)
BENCH_AUDIO = "127.0.0.1:7320"           # and its decks' sound (--input-tcp, and the menu's "Sound in: deckbench")
ROW = 26                                 # a row of the side panel's lists
HEAD = 28                                # a section's header
DETAIL_H = 18 * 5 + 12                   # what the mods' list shows of the mod the mouse is on: its page text
FPS = 60
MIN_HOLD = 120                           # ms a clicked key or pad stays down at least
BOOT_S = 24                              # about how long the app takes to draw its first screen
HELP = (                                 # the side panel's reminder: (keys, what they do)
    ("Mouse", "press keys and pads, drag or wheel knobs, touch the screen"),
    ("Right-click", "pad, step key: hold it down (click to let go)   \u00b7   strip: leave a finger on it   \u00b7   tempo slider: centre"),
    ("Space  B  N", "PLAY/PAUSE   STOP   REC"),
    ("\u2191 \u2193   Enter   \u2190", "selector: turn, push   \u00b7   BACK (also Esc)"),
    ("F1 \u2013 F6", "the six knobs (Right Shift: the other way)"),
    ("1\u20138   Q\u2013I", "step keys 1\u20138 and 9\u201316"),
    ("P  L  X  H  M", "PROJECT   SAMPLING   FX   HOME   MODE"),
    ("Left Shift", "SHIFT"),
    ("Tab", "main sound device: MASTER / PHONES"),
    ("F10   F12", "hide this panel   \u00b7   lamp diagnostics"),
    ("F7   F8   F9", "record the window   \u00b7   tools menu   \u00b7   hide or show the status line"),
)
DRAG_PX = 7                              # mouse travel for one encoder step

# Keyboard keys for controls that are not drawn as a Key or Knob.
EXTRA_KEYS = {
    pygame.K_BACKSPACE: ("bit", (1, 2)),
    pygame.K_RETURN: ("bit", (1, 1)),
    pygame.K_KP_ENTER: ("bit", (1, 1)),
    pygame.K_COMMA: ("enc", (0, -1)),
    pygame.K_PERIOD: ("enc", (0, 1)),
    pygame.K_UP: ("enc", (0, -1)),
    pygame.K_DOWN: ("enc", (0, 1)),
    pygame.K_PAGEUP: ("enc", (0, -5)),
    pygame.K_PAGEDOWN: ("enc", (0, 5)),
    pygame.K_RIGHT: ("bit", (1, 1)),     # the selector's push
    pygame.K_LEFT: ("bit", (1, 2)),      # BACK
}
KEYCAPS = {"Esc": pygame.K_ESCAPE, "-": pygame.K_MINUS, "Space": pygame.K_SPACE,
           "Left Shift": pygame.K_LSHIFT}


def edge(h):
    """The room the window has under the unit, which is its margin on the other three sides too (not in a recording, whose regions are
    measured from the window's edge): what is left between the foot of the unit's body and the status line."""
    scale = max(0.2, (h - STATUS_H) / L.H)
    return max(2, h - STATUS_H - int(L.BODY[3] * scale) - 1)


class Meter:
    """What the master's sound is doing, for the status line: how loud it is and how fast it arrives (1.0 is real time: the emulator
    is a little faster or slower than that, which is why a recording's sound has to be fitted to its picture). feed() is called from
    the link's thread, the rest from the window's."""

    def __init__(self):
        self.peak = 0.0                  # the loudest sample since it was last read
        self.shown = 0.0                 # what the bar shows: it falls slowly
        self.hold, self.hold_at = 0.0, 0.0
        self.clip_at = -9.0              # when a sample last reached full scale
        self.frames = 0
        self.marks = deque(maxlen=2000)  # (time, frames so far)

    def feed(self, data):
        n = len(data) // 8
        if not n:
            return
        a = array.array("f")
        a.frombytes(data[:n * 8])
        p = max(max(a), -min(a))
        if p > self.peak:
            self.peak = p
        if p >= 0.99:
            self.clip_at = time.perf_counter()
        self.frames += n
        self.marks.append((time.perf_counter(), self.frames))

    def speed(self):
        """Frames that arrived a second, over the last five seconds, over 44100: None if there is not enough sound to say."""
        try:
            marks = list(self.marks)
        except RuntimeError:
            return None
        now = time.perf_counter()
        marks = [m for m in marks if now - m[0] <= 5.0]
        if len(marks) < 2 or now - marks[-1][0] > 2.0 or marks[-1][0] - marks[0][0] < 1.5:
            return None
        return (marks[-1][1] - marks[0][1]) / 44100.0 / (marks[-1][0] - marks[0][0])

    def level(self):
        """(the bar, the held peak, whether it clipped lately), each 0 to 1 on a scale of -60 dB to 0."""
        now = time.perf_counter()
        p, self.peak = self.peak, 0.0
        self.shown = max(p, self.shown * 0.9)
        if p >= self.hold or now - self.hold_at > 1.5:
            self.hold, self.hold_at = max(p, self.shown), now

        def scale(v):
            return min(1.0, max(0.0, (20 * math.log10(max(v, 1e-6)) + 60) / 60))
        return scale(self.shown), scale(self.hold), now - self.clip_at < 1.0


class BenchWatch:
    """What deckbench says of its decks, asked for in the background every two seconds, for the status line."""

    def __init__(self, url):
        self.url = url.rstrip("/") + "/"
        self.up = False
        self.on = self.playing = self.with_file = 0
        self.master = None
        self.closed = False
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        import json
        import urllib.request
        while not self.closed:
            try:
                with urllib.request.urlopen(self.url + "api/state", timeout=1.5) as reply:
                    decks = json.load(reply)["decks"]
                self.on = sum(1 for d in decks.values() if d.get("on"))
                self.playing = sum(1 for d in decks.values() if d.get("on") and d.get("play"))
                self.with_file = sum(1 for d in decks.values() if d.get("on") and d.get("audio"))
                masters = [n for n, d in decks.items() if d.get("on") and d.get("master")]
                self.master = masters[0] if masters else None
                self.up = True
            except (OSError, ValueError, KeyError, AttributeError):
                self.up = False
            time.sleep(2.0)

    def text(self):
        """The status line's words: how many decks are on, how many play, which is the master, how many play a file of their own."""
        text = f"decks {self.on} on \u00b7 {self.playing} playing"
        if self.master:
            text += f" \u00b7 master {self.master}"
        if self.with_file:
            text += f" \u00b7 {self.with_file} with a file"
        return text


class Recording:
    """REC: the window (without its status line and the menu) as video, and the sound as you hear it (the output the MASTER / PHONES switch
    has chosen, not the two added: the headphones carry an attenuated, partly inverted copy of the program, which would thin it), in a
    folder. The video is app/capture.py's, the same as --record; when it ends the sound is joined to it: NAME.mp4 (video and sound),
    NAME.wav (the sound alone, 24 bits, for an editor) and NAME.steps (what was pressed, for tools/reel.py)."""

    def __init__(self, folder, size, fps, project=""):
        os.makedirs(folder, exist_ok=True)
        self.name = "deck-" + time.strftime("%Y%m%d-%H%M%S")
        self.base = os.path.join(folder, self.name)
        self.video = self.base + ".video.mp4"
        self.size, self.fps = size, fps
        self.capture = Capture(self.video, size, fps)
        self.began = time.time()
        # NAME.steps: every command the deck sends the app, as "seconds command" lines, which tools/reel.py plays back
        self.steps = open(self.base + ".steps", "w", encoding="utf-8", buffering=1)
        self.steps.write("# djs1000 deck steps: seconds into the recording, then the command line\n")
        if project:                                   # the project the app had open (its path as the app sees it), for the replay to open first
            self.steps.write("# project: %s\n" % project)

    def step(self, line):
        try:
            self.steps.write("%.3f %s\n" % (time.time() - self.began, line))
        except (OSError, ValueError):
            pass

    def frame(self, surf):
        if surf.get_size() != self.size:             # the window was resized: the file keeps the size it began with
            surf = pygame.transform.smoothscale(surf, self.size)
        self.capture.frame(surf)

    def sound(self, data, which):
        self.capture.sound(data, which)

    def seconds(self):
        return time.time() - self.began

    def finish(self, done, wait=False):
        """Ends the video and, in the background, joins it with the sound. done(text) says where the file is, or what went wrong."""
        self.capture.close()
        self.steps.close()
        worker = threading.Thread(target=self._join, args=(done,), daemon=True)
        worker.start()
        if wait:
            worker.join()

    def _join(self, done):
        ffmpeg = shutil.which("ffmpeg")
        try:
            master, rate = self.video + ".f32", self.video + ".rate"
            ratio = float(open(rate).read()) if os.path.exists(rate) else 1.0
            # the emulator's sound runs a little fast or slow against the clock (capture.py). The sound is kept as it is, at its own pitch
            # and pace, and the picture is retimed by that little to follow it
            retime = "setpts=%.6f*PTS,fps=%d" % (ratio, self.fps) if abs(ratio - 1.0) > 0.002 else "null"
            sound = os.path.exists(master) and os.path.getsize(master) > 0
            final = self.base + ".mp4"
            if sound:
                raw = ["-f", "f32le", "-ar", "44100", "-ac", "2"]
                wav = self.base + ".wav"
                subprocess.check_call([ffmpeg, "-y", "-loglevel", "error"] + raw + ["-i", master, "-c:a", "pcm_s24le", wav])
                video = ["-c:v", "copy"] if retime == "null" else ["-vf", retime, "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-pix_fmt", "yuv420p"]
                subprocess.check_call([ffmpeg, "-y", "-loglevel", "error", "-i", self.video, "-i", wav, "-map", "0:v", "-map", "1:a"] + video + [
                                       "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", final])
            else:
                os.replace(self.video, final)
            for suffix in ("", ".f32", ".f32p", ".rate", ".start", ".stop", ".cmd"):
                try:
                    os.remove(self.video + suffix)
                except OSError:
                    pass
            try:
                shown = os.path.relpath(final, os.path.dirname(HERE))      # from the repository, if it is on this drive
            except ValueError:
                shown = final
            done("saved " + shown)
        except (OSError, subprocess.CalledProcessError, ValueError) as e:
            done("the recording was not joined: %s (the parts are %s.*)" % (e, self.video))


def surface(img):
    mode = "RGBA" if img.mode == "RGBA" else "RGB"
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    surf = pygame.image.frombytes(img.tobytes(), img.size, mode)
    return surf.convert_alpha() if mode == "RGBA" else surf.convert()


class Deck:
    @staticmethod
    def icon():
        """The window's icon (see art.icon), as a pygame surface."""
        im = art.icon(64)
        return pygame.image.frombytes(im.tobytes(), im.size, "RGBA")

    def __init__(self, link, size, players=(None, None), recorder=None, listen=None, mods=None, tidy=True):
        self.link = link
        self.tidy = tidy                 # the window's margin and spacing: not in a recording, which is cut up by places in the window
        self.mods = mods or Mods(None)   # what a patch on the USB drive carries
        self.mod_rects = []              # (where, name): the switches drawn in the side panel
        self.mod_hover = None            # the mod the mouse was last on in the list (its text shows under it)
        self.hover_pinned = False        # --hover: the mod shown is the one asked for, whatever the mouse does
        self.fold = {"mods": False, "help": False}      # the side panel's two sections: folded or not
        self.scroll = {"mods": 0, "help": 0}            # how far each is scrolled, in pixels
        self.fold_rects = []             # (where, section): the headers
        self.body_rects = {}             # section: where its body is drawn (the mouse wheel scrolls it)
        self.track_rects = {}            # section: (the scrollbar's track, the thumb, the most it scrolls)
        self.thumb = None                # (section, where in the thumb it was taken): being dragged
        self.master, self.phones = players
        self.recorder = recorder
        self.show_dock = True            # the large screen beside the face (F10)
        self.lift = 0                    # --key: nothing but what is round the unit is darker than this (of 255), see apply_key
        self.key_rects = []              # the rectangles of the side panel that are kept off black too
        self.lift_face = None
        self.meter = Meter()             # the master's level and speed (main gives it the sound)
        self.show_status = True          # the line at the foot (F9)
        self.menu_open = False           # the tools menu (F8)
        self.menu_items, self.menu_rects, self.menu_panel = [], [], pygame.Rect(0, 0, 0, 0)
        self.tools_rect = pygame.Rect(0, 0, 0, 0)
        self.copy_rect = pygame.Rect(0, 0, 0, 0)
        self.last_action = ""            # the last thing done with the mouse, as a line for an episode script (a click copies it)
        self.on_top = False
        self.rec = None                  # a Recording, while REC is on
        self.rec_ok = True               # False for a --record, which has its own capture
        self.captures = CAPTURES
        self.rec_fps = 30
        self.notice = ("", 0)            # a message for the status line, and until when (ticks)
        self.latched = {}                # the pads and step keys a right click holds down: key index -> the line that lets it go
        self.velocity = None             # a pad hit by the mouse: a share (10 to 100) of full velocity, or None: by where it is hit
        self.bench = None                # BenchWatch, if deckbench is looked at
        self.bench_rect = pygame.Rect(0, 0, 0, 0)
        self.input_makers = {}           # "system" and "bench": what makes the recorder that feeds the app's input
        self.input_kind = "system" if recorder else "none"
        self._system = recorder if recorder else None
        self.outline = True              # a thin line closes each section of the side panel (not in a recording: the reel frames its cards)
        self.show_lamps = False          # under it, the lamps by id instead of the keys (F12)
        self.have_screen = False         # the app has drawn something
        self.mod_page = False            # the face's small screen shows the list of mods, drawn as a page of the unit (a recording's `page mods`)
        self._page_fonts = None
        self.up_at = None                # when the link came up, for the start-up bar
        self.big = pygame.font.SysFont("arial", 22, bold=True)
        self.listen = listen if listen is not None else [0]   # the output the main device plays
        self.listen_rect = pygame.Rect(0, 0, 0, 0)
        pygame.display.set_icon(self.icon())
        self.win = pygame.display.set_mode(size, pygame.RESIZABLE)
        pygame.display.set_caption(TITLE)
        self.font = pygame.font.SysFont("arial", 14)
        self.small = pygame.font.SysFont("arial", 11)
        self.screen = pygame.Surface((L.LCD_W, L.LCD_H)).convert()
        self.screen.fill((0, 0, 0))
        self.lamps = bytes(128)
        self.down = None                 # what the mouse holds: (kind, ...)
        self.down_at = 0                 # when it took it, ms
        self.later = []                  # (when, line): releases held back, see release()
        self.keys_down = {}              # keyboard key -> bit held
        self.held_keys = set()           # the keys a recording script holds down (`key NAME 1`), by their index in L.KEYS
        self.knob_step = [knob.at for knob in L.KNOBS]
        self.slider = 0.5                # the tempo slider: 0 top (-) to 1 bottom (+)
        self.strip = None                # where the strip is touched, 0-127
        self.pinned = False              # the touch stays when the mouse lets go
        self.drag_y = 0
        self.moved = False
        self.hover = ""
        self.sprites = {}
        self.unknown = L.unknown_bits()
        self.keymap = self._keymap()
        self.layout()

    def _keymap(self):
        m = {}
        for key in L.KEYS:
            if key.keycap and key.bit:
                code = KEYCAPS.get(key.keycap) or pygame.key.key_code(key.keycap.lower())
                m[code] = ("bit", key.bit)
        for knob in L.KNOBS:
            if knob.keycap.startswith("F") and knob.enc:
                m[getattr(pygame, f"K_F{knob.enc}")] = ("enc", (knob.enc, 1))
        m.update(EXTRA_KEYS)
        return m

    # ---- geometry -------------------------------------------------------

    def layout(self):
        w, h = self.win.get_size()
        self.scale = max(0.2, (h - STATUS_H) / L.H)
        self.face_w = int(L.W * self.scale)
        self.edge = edge(h) if self.tidy else None
        self.ox = self.edge or 0                      # where the unit begins
        self.face = surface(art.face(self.scale))
        self.lift_face = self.lift_layer(art.face_alpha(self.scale)) if self.lift else None
        self.cap = surface(art.slider_cap(self.scale))
        self.sprites.clear()
        x0, y0, x1, y1 = (int(v * self.scale) for v in L.LCD)
        self.lcd_rect = pygame.Rect(x0 + self.ox, y0, x1 - x0, y1 - y0)
        right = self.edge + 1 if self.tidy else DOCK_PAD       # (the large screen's line is one outside it)
        room = w - self.ox - self.face_w - DOCK_PAD - right
        self.dock = None
        self.grid = []
        self.lamp_cells = []
        shown = self.show_dock and room >= 360
        if self.tidy:                                 # a window larger than the unit and its panels: they sit in the middle
            used = self.face_w + (DOCK_PAD + int(L.LCD_W * min(1.0, room / L.LCD_W)) if shown else 0)
            shift = max(0, (w - 2 * self.edge - used) // 2)
            if shift:
                self.ox += shift
                self.lcd_rect.move_ip(shift, 0)
        if shown:
            k = min(1.0, room / L.LCD_W)
            self.dock = pygame.Rect(self.ox + self.face_w + DOCK_PAD, self.edge + 1 if self.tidy else DOCK_PAD, int(L.LCD_W * k),
                                    int(L.LCD_H * k))
            if self.show_lamps:
                self._grid(self.dock.left, self.dock.bottom + 34, self.dock.width)

    def lift_layer(self, alpha):
        """A picture that is black round the unit and `lift` on it, which the window takes the larger of at each pixel (apply_key)."""
        from PIL import Image
        k = self.lift
        return surface(Image.composite(Image.new("RGB", alpha.size, (k, k, k)), Image.new("RGB", alpha.size, (0, 0, 0)), alpha))

    def apply_key(self):
        """For a screen recording that is keyed on its brightness: the window is black only where nothing is (round the unit, between
        the cards and in the corners), and every pixel of the unit and of the cards is at least `lift` bright, as the black reels are
        made. Drawn last, over everything but the status line."""
        win = self.win
        if self.lift_face:
            win.blit(self.lift_face, (self.ox, 0), special_flags=pygame.BLEND_RGB_MAX)
        for r in self.key_rects:
            win.fill((self.lift,) * 3, r, special_flags=pygame.BLEND_RGB_MAX)

    def fit(self, h):
        """The window's width for height h: the unit, and the side panel if it is shown."""
        face_w = int(L.W * max(0.2, (h - STATUS_H) / L.H))
        if self.tidy:
            e = edge(h)
            w = e + face_w + (L.LCD_W + DOCK_PAD + e + 1 if self.show_dock else e)
        else:
            w = face_w + (L.LCD_W + 2 * DOCK_PAD if self.show_dock else 0)
        return min(w, pygame.display.get_desktop_sizes()[0][0] - 40)

    def toggle_dock(self):
        """Shows or hides the side panel, and sizes the window to what is left."""
        self.show_dock = not self.show_dock
        _, h = self.win.get_size()
        self.win = pygame.display.set_mode((self.fit(h), h), pygame.RESIZABLE)
        self.layout()
        self.keep_on_top()

    # ---- the tools menu and the status line's switches -------------------

    def say(self, text):
        """A message in the status line for a few seconds."""
        self.notice = (text, pygame.time.get_ticks() + 8000)

    def toggle_rec(self):
        """REC: starts recording the window and the sound to demo/captures, or ends it."""
        if self.rec:
            rec, self.rec = self.rec, None
            self.say("saving the recording...")
            rec.finish(self.say)
            return
        if not shutil.which("ffmpeg"):
            self.say("REC needs ffmpeg on the path")
            return
        w, h = self.win.get_size()
        self.rec = Recording(self.captures, (w, h - STATUS_H), self.rec_fps, self.link.project)
        self.say(f"recording to {self.rec.name}.mp4 (F7 ends it): the window without its status line")

    def keep_on_top(self):
        try:
            pygame.Window.from_display_module().always_on_top = self.on_top
        except (AttributeError, pygame.error):
            self.on_top = False

    def toggle_menu(self):
        self.menu_open = not self.menu_open

    def toggle_status(self):
        self.show_status = not self.show_status

    def toggle_key(self):
        self.lift = 0 if self.lift else 4
        self.layout()

    def toggle_outline(self):
        self.outline = not self.outline

    def toggle_on_top(self):
        self.on_top = not self.on_top
        self.keep_on_top()

    def resize(self, factor):
        _, h = self.win.get_size()
        h = int(min(pygame.display.get_desktop_sizes()[0][1] - 60, max(420, h * factor)))
        self.win = pygame.display.set_mode((self.fit(h), h), pygame.RESIZABLE)
        self.layout()
        self.keep_on_top()

    def set_input(self, kind):
        """The app's input comes from this computer's recording device ("system"), from deckbench's stream ("bench") or nothing."""
        if kind == self.input_kind:
            return
        if self.recorder:
            self.recorder.closed = True          # (a device stays open, silent, for a return to it: SDL is not asked to close it)
        new = None
        try:
            if kind == "system":
                new = self._system or self.input_makers["system"]()
                new.closed = False
                self._system = new
            elif kind == "bench":
                new = self.input_makers["bench"]()
        except Exception as e:                   # no recording device
            print(f"no input: {e}", file=sys.stderr)
            kind = "none"
        self.recorder, self.input_kind = new, kind
        if new:
            for i, knob in enumerate(L.KNOBS):   # the INPUT LEVEL knob is where it was
                if knob.gain:
                    new.gain = self.knob_step[i] / L.POT_STEPS

    def open_bench(self):
        if self.bench:
            webbrowser.open(self.bench.url)

    def step_velocity(self, direction):
        """The pad velocity of a mouse hit: less or more, by tens of a hundred, and past 100 by where on the pad it is hit."""
        i = VELOCITIES.index(self.velocity) + direction
        self.velocity = VELOCITIES[max(0, min(len(VELOCITIES) - 1, i))]

    def wait_more(self, ms):
        self.master.set_wait(self.master.wait_ms + ms)

    def tool_items(self):
        """The tools menu: (label, "check" or "action", the state of a check, what a click does)."""
        items = [("Keyable background (luma key)", "check", lambda: bool(self.lift), self.toggle_key),
                 ("Side panel outline", "check", lambda: self.outline, self.toggle_outline),
                 ("Status line  (F9)", "check", lambda: self.show_status, self.toggle_status),
                 ("Always on top", "check", lambda: self.on_top, self.toggle_on_top),
                 (lambda: "Pad velocity  " + ("by position" if self.velocity is None else f"{self.velocity}%"), "stepper", None, self.step_velocity),
                 ("Window larger", "action", None, lambda: self.resize(1.1)),
                 ("Window smaller", "action", None, lambda: self.resize(1 / 1.1)),
                 ("USB stick: unplug", "action", None, lambda: self.link.send("usb 0")),
                 ("USB stick: plug in", "action", None, lambda: self.link.send("usb 1"))]
        if self.rec_ok:
            items.insert(0, ("Record the window  (F7)", "check", lambda: bool(self.rec), self.toggle_rec))
        if self.input_makers:
            items += [("Sound in: this computer", "check", lambda: self.input_kind == "system", lambda: self.set_input("system")),
                      ("Sound in: deckbench", "check", lambda: self.input_kind == "bench", lambda: self.set_input("bench")),
                      ("Sound in: nothing", "check", lambda: self.input_kind == "none", lambda: self.set_input("none"))]
        if self.bench and self.bench.up:
            items += [("Open deckbench's page", "action", None, self.open_bench)]
        if hasattr(self.master, "set_wait"):
            items += [("Sound waits 50 ms less", "action", None, lambda: self.wait_more(-50)),
                      ("Sound waits 50 ms more", "action", None, lambda: self.wait_more(50))]
        return items

    def copy_last(self):
        if self.last_action:
            try:
                pygame.scrap.init()
                pygame.scrap.put_text(self.last_action)
            except pygame.error:
                pass

    def toggle_lamps(self):
        self.show_lamps = not self.show_lamps
        self.layout()

    def _grid(self, x, y, width):
        """The unknown button bits, then every two-level lamp."""
        cell, gap = 46, 6
        per_row = max(1, (width + gap) // (cell + gap))
        self.grid_y = y
        for i, bit in enumerate(self.unknown):
            r = pygame.Rect(x + (i % per_row) * (cell + gap), y + (i // per_row) * (30 + gap),
                            cell, 30)
            self.grid.append((r, bit))
        rows = (len(self.unknown) + per_row - 1) // per_row
        self.lamp_y = y + rows * (30 + gap) + (30 if rows else 0)
        self.lamp_cells = []
        for i, lamp in enumerate(sorted(L.LAMPS)):
            r = pygame.Rect(x + (i % per_row) * (cell + gap),
                            self.lamp_y + (i // per_row) * (22 + gap), cell, 22)
            self.lamp_cells.append((r, lamp))

    def to_units(self, pos):
        return (pos[0] - self.ox) / self.scale, pos[1] / self.scale

    def lcd_point(self, pos):
        """The app-window point under the mouse, on either copy of the screen."""
        for rect in (self.dock, self.lcd_rect):
            if rect and rect.collidepoint(pos):
                x = (pos[0] - rect.left) * L.LCD_W // rect.width
                y = (pos[1] - rect.top) * L.LCD_H // rect.height
                return x + L.LCD_ORIGIN[0], y + L.LCD_ORIGIN[1]
        return None

    def find(self, pos):
        """What is under the mouse: ("lcd", x, y), ("knob", i), ("key", i),
        ("bit", (byte, bit)) or None."""
        if self.menu_open:
            for r, i in self.menu_rects:
                if r.collidepoint(pos):
                    return ("tool", i)
            if self.menu_panel.collidepoint(pos):
                return ("toolbg",)
        if self.tools_rect.collidepoint(pos):
            return ("tools",)
        if self.bench_rect.collidepoint(pos):
            return ("bench",)
        if self.copy_rect.collidepoint(pos):
            return ("copy",)
        p = self.lcd_point(pos)
        if p:
            return ("lcd", *p)
        if self.listen_rect.collidepoint(pos):
            return ("listen",)
        for r, bit in self.grid:
            if r.collidepoint(pos):
                return ("bit", bit)
        for r, name in self.mod_rects:
            if r.collidepoint(pos):
                return ("mod", name)
        for r, key in self.fold_rects:
            if r.collidepoint(pos):
                return ("fold", key)
        for key, (track, thumb, _) in self.track_rects.items():
            if track.collidepoint(pos):
                return ("thumb", key, pos[1] - thumb.top if thumb.collidepoint(pos) else -1)
        if pos[0] >= self.ox + self.face_w:
            return None
        x, y = self.to_units(pos)
        fx0, fy0, fx1, fy1 = L.SLIDER_FRAME
        if fx0 <= x <= fx1 and fy0 <= y <= fy1:
            return ("slider",)
        sx0, sy0, _, sy1 = L.STRIP
        if sx0 + 14 <= x <= sx0 + 96 and sy0 <= y <= sy1:
            return ("strip",)
        for i, knob in enumerate(L.KNOBS):
            if knob.hit(x, y):
                return ("knob", i)
        for i, key in enumerate(L.KEYS):
            if key.kind != "led" and key.hit(x, y):
                return ("key", i)
        return None

    def describe(self, what):
        if not what:
            return ""
        if what[0] == "tools":
            return "tools: keyable background, lines, window size, USB stick, how long the sound waits  \u00b7  F8"
        if what[0] == "tool":
            label = self.menu_items[what[1]][0] if what[1] < len(self.menu_items) else ""
            return label() if callable(label) else label
        if what[0] == "toolbg":
            return ""
        if what[0] == "bench":
            return "deckbench's decks  \u00b7  click to open its page"
        if what[0] == "copy":
            return ""
        if what[0] == "lcd":
            return f"screen  {what[1] - 1}, {what[2] - 1}"
        if what[0] == "listen":
            return "which output the main sound device plays  \u00b7  click, or Tab"
        if what[0] == "deck":
            return {"on": f"fake CDJ {what[1]} on Pro DJ Link  ·  click to put it on the "
                          "network or take it off",
                    "play": f"fake CDJ {what[1]}  ·  play or stop it: a playing deck sends beats",
                    "sync": f"fake CDJ {what[1]}  ·  sync on or off: a synced deck plays at the "
                            "tempo master's tempo",
                    "master": f"fake CDJ {what[1]}  ·  tempo master: it takes the role from "
                              "whoever has it (the unit included)"}[what[2]]
        if what[0] == "mod":
            return f"mod {what[1]}  ·  click to switch it on or off, as the app runs"
        if what[0] == "fold":
            return "click to fold or unfold this section"
        if what[0] == "thumb":
            return "scrollbar  \u00b7  drag, or the mouse wheel over the section"
        if what[0] == "strip":
            return "touch strip  \u00b7  hold and slide; right-click leaves a finger on it"
        if what[0] == "slider":
            return "tempo slider  \u00b7  drag; right-click for the centre"
        if what[0] == "bit":
            byte, bit = what[1]
            return f"unknown button  id {L.BUTTON_IDS[what[1]]:#04x}  frame byte {byte} bit {bit}"
        if what[0] == "knob":
            knob = L.KNOBS[what[1]]
            how = f"encoder {knob.enc}" if knob.enc is not None else \
                f"frame word {knob.word:#x}" if knob.word is not None else \
                "the level of the input the deck sends" if knob.gain else "not identified yet"
            return "  ·  ".join(filter(None, [knob.name.replace("_", " "), how,
                                                 knob.keycap and f"keys {knob.keycap}"]))
        key = L.KEYS[what[1]]
        if key.pad is not None:
            how = f"pad {key.pad + 1}"
        elif key.bit:
            how = f"frame byte {key.bit[0]} bit {key.bit[1]}"
        else:
            how = "not identified yet"
        return "  ·  ".join(filter(None, [key.name.replace("_", " "), how,
                                             key.keycap and f"key {key.keycap}"]))

    # ---- input ----------------------------------------------------------

    def turn(self, i, delta):
        knob = L.KNOBS[i]
        self.knob_step[i] += delta
        if knob.look == "pot":
            self.knob_step[i] = max(0, min(L.POT_STEPS, self.knob_step[i]))
            if knob.word is not None:
                self.link.send(f"word {knob.word} {self.knob_step[i] * 1023 // L.POT_STEPS}")
            if knob.gain and self.recorder:
                self.recorder.gain = self.knob_step[i] / L.POT_STEPS
        if knob.enc is not None:
            self.last_action = f"ctx.say('knob {knob.name} {delta}')"
            self.link.send(f"enc {knob.enc} {delta}")

    def replay(self, line):
        """A command line of a recording's steps (a .steps file): sent to the app as it is, and what the deck draws of it follows (the
        knob that a `word` turns, the finger of a `strip`, the encoder that an `enc` turns)."""
        part = line.split()
        try:
            if part[0] == "word" and len(part) == 3:
                word, value = int(part[1]), int(part[2])
                if word == L.SLIDER_WORD:
                    self.slider = 0.5 if value == L.SLIDER_CENTRE else min(1.0, max(0.0, value / 1023))
                for i, knob in enumerate(L.KNOBS):
                    if knob.word == word and knob.look == "pot":
                        self.knob_step[i] = round(value * L.POT_STEPS / 1023)
            elif part[0] == "enc" and len(part) == 3:
                for i, knob in enumerate(L.KNOBS):
                    if knob.enc == int(part[1]):
                        self.turn(i, int(part[2]))
                        return
            elif part[0] == "strip" and len(part) == 2:
                self.strip = int(part[1]) if int(part[1]) >= 0 else None
        except ValueError:
            pass
        self.link.send(line)

    def analogue(self):
        """Sends where the pots and the slider stand: the app only knows
        what the panel tells it."""
        for i, knob in enumerate(L.KNOBS):
            if knob.word is not None:
                self.link.send(f"word {knob.word} {self.knob_step[i] * 1023 // L.POT_STEPS}")
        self.link.send(f"word {L.SLIDER_REF} {L.SLIDER_CENTRE}")
        self.link.send(f"word {L.SLIDER_WORD} {self.slider_value()}")

    def slider_value(self):
        if abs(self.slider - 0.5) < 0.012:   # the centre click
            return L.SLIDER_CENTRE
        return int(round(self.slider * 1023))

    def stroke(self, pos):
        """A finger on the touch strip: 127 at the top (+) to 0 at the bottom."""
        _, y = self.to_units(pos)
        top, bottom = L.STRIP[1] + 20, L.STRIP[3] - 20
        self.strip = int(round(127 * min(1.0, max(0.0, (bottom - y) / (bottom - top)))))
        self.link.send(f"strip {self.strip}")

    def pin(self, pos):
        """Right-click on the strip: a finger that stays there, so that the
        mouse is free for the pads. Again, and it is lifted."""
        if self.pinned:
            self.pinned, self.strip = False, None
            self.link.send("strip -1")
        else:
            self.pinned = True
            self.stroke(pos)

    def slide(self, pos):
        _, y = self.to_units(pos)
        _, top, bottom = L.SLIDER
        self.slider = min(1.0, max(0.0, (y - top) / (bottom - top)))
        self.link.send(f"word {L.SLIDER_WORD} {self.slider_value()}")

    def switch_output(self):
        """The main device plays the other output: master or headphones."""
        if self.master:
            self.listen[0] ^= 1
            self.master.reset()

    def pad_velocity(self, key, pos):
        """How hard, of 1023: a hit begins at the pad's calibration (336) and is at full velocity near 840. By default harder towards the
        bottom of the pad, or a fixed share of that range (the tools menu)."""
        if self.velocity is not None:
            return int(336 + (840 - 336) * self.velocity / 100.0)
        _, y = self.to_units(pos)
        y0, y1 = key.box[1], key.box[3]
        return int(460 + 400 * min(1.0, max(0.0, (y - y0) / (y1 - y0))))

    def holdable(self, key):
        """A performance button: a pad or a step key."""
        return key.pad is not None or key.kind == "step"

    def latch(self, pos):
        """Right click on a pad or a step key: it is held down until it is clicked again (left or right) or its keyboard key is pressed."""
        what = self.find(pos)
        if not what or what[0] != "key" or not self.holdable(L.KEYS[what[1]]):
            return
        i = what[1]
        if i in self.latched:
            self.unlatch(i)
            return
        key = L.KEYS[i]
        if key.pad is not None:
            v = self.pad_velocity(key, pos)
            self.link.send(f"pad {key.pad} {v} {v}")
            self.latched[i] = f"pad {key.pad} 0 0"
            self.last_action = f"ctx.s.send('pad {key.pad} {v} {v}')  # {key.name} held (pad {key.pad} 0 0 lets go)"
        elif key.bit:
            self.link.send(f"bit {key.bit[0]} {key.bit[1]} 1")
            self.latched[i] = f"bit {key.bit[0]} {key.bit[1]} 0"
            self.last_action = f"ctx.s.send('bit {key.bit[0]} {key.bit[1]} 1')  # {key.name} held (bit {key.bit[0]} {key.bit[1]} 0 lets go)"

    def unlatch(self, i):
        line = self.latched.pop(i, None)
        if line:
            self.link.send(line)

    def press(self, pos):
        what = self.find(pos)
        if self.menu_open and (not what or what[0] not in ("tool", "toolbg", "tools")):
            self.menu_open = False                    # a click away from the menu only closes it
            return
        if not what:
            return
        if what[0] == "tools":
            self.toggle_menu()
            return
        if what[0] == "toolbg":
            return
        if what[0] == "bench":
            self.open_bench()
            return
        if what[0] == "tool":
            if what[1] < len(self.menu_items):
                label, kind, state, handler = self.menu_items[what[1]]
                if kind == "stepper":                 # the left half of the row is less, the right half more
                    handler(-1 if pos[0] < self.menu_rects[what[1]][0].centerx else 1)
                else:
                    handler()
            return
        if what[0] == "copy":
            self.copy_last()
            return
        if what[0] == "listen":
            self.switch_output()
            return
        if what[0] == "mod":
            self.last_action = f"ctx.say('toggle {what[1]}')"
            self.mods.toggle(what[1])
            return
        if what[0] == "fold":
            self.fold[what[1]] = not self.fold[what[1]]
            self.scroll[what[1]] = 0
            return
        if what[0] == "thumb":
            _, thumb, _ = self.track_rects[what[1]]
            grip = what[2] if what[2] >= 0 else thumb.height // 2     # beside the thumb: it comes there
            self.thumb = (what[1], grip)
            self.drag_thumb(pos[1])
            return
        if what[0] == "key" and what[1] in self.latched:
            self.unlatch(what[1])                     # a click on a key that is held lets it go, and is no press
            return
        self.down = what
        self.down_at = pygame.time.get_ticks()
        self.flush(now=True)
        if what[0] == "slider":
            self.slide(pos)
        elif what[0] == "strip":
            self.stroke(pos)
        elif what[0] == "lcd":
            self.last_action = f"ctx.touch({what[1] - 1}, {what[2] - 1})"
            self.link.send(f"touch 1 {what[1]} {what[2]}")
        elif what[0] == "bit":
            self.link.send(f"bit {what[1][0]} {what[1][1]} 1")
        elif what[0] == "knob":
            self.drag_y = pos[1]
            self.moved = False
        elif what[0] == "key":
            key = L.KEYS[what[1]]
            if key.pad is not None:
                v = self.pad_velocity(key, pos)
                self.last_action = f"ctx.s.pad({key.pad})  # {key.name}" + (f", level {v}" if self.velocity is not None else "")
                self.link.send(f"pad {key.pad} {v} {v}")
            elif key.bit:
                self.last_action = f"ctx.press(({key.bit[0]}, {key.bit[1]}))  # {key.name}"
                self.link.send(f"bit {key.bit[0]} {key.bit[1]} 1")

    def release(self, pos):
        self.thumb = None
        what, self.down = self.down, None
        if not what:
            return
        if what[0] == "lcd":
            p = self.lcd_point(pos) or what[1:]
            self.link.send(f"touch 0 {p[0]} {p[1]}")
        elif what[0] == "bit":
            self.link.send(f"bit {what[1][0]} {what[1][1]} 0")
        elif what[0] == "strip" and not self.pinned:
            self.strip = None
            self.link.send("strip -1")
        elif what[0] == "knob":
            knob = L.KNOBS[what[1]]
            if knob.push and not self.moved:
                self.link.send(f"tap {knob.push[0]} {knob.push[1]}")
        elif what[0] == "key":
            key = L.KEYS[what[1]]
            if key.pad is not None:
                self.let_go(f"pad {key.pad} 0 0")
            elif key.bit:
                self.let_go(f"bit {key.bit[0]} {key.bit[1]} 0")

    def let_go(self, line):
        """A key or pad released: not before it has been held MIN_HOLD ms. The
        app takes a pad or key as pressed after a few panel frames, 2 ms each
        on the unit. Here its panel cycle runs at about 10 ms, slower while it
        plays, and a quick click was over before it counted."""
        self.later.append((self.down_at + MIN_HOLD, line))
        self.flush()

    def flush(self, now=False):
        t = pygame.time.get_ticks()
        for when, line in self.later:
            if now or when <= t:
                self.link.send(line)
        self.later = [(w, l) for w, l in self.later if not now and w > t]

    def drag_thumb(self, y):
        key, grip = self.thumb
        track, thumb, most = self.track_rects[key]
        span = max(1, track.height - thumb.height)
        self.scroll[key] = int(min(1.0, max(0.0, (y - grip - track.top) / span)) * most)

    def motion(self, pos):
        if self.thumb:
            self.drag_thumb(pos[1])
        elif self.down and self.down[0] == "lcd":
            p = self.lcd_point(pos)
            if p:
                self.link.send(f"touch 2 {p[0]} {p[1]}")
        elif self.down and self.down[0] == "slider":
            self.slide(pos)
        elif self.down and self.down[0] == "strip":
            self.stroke(pos)
        elif self.down and self.down[0] == "knob":
            steps = int((self.drag_y - pos[1]) / DRAG_PX)
            if steps:
                self.drag_y -= steps * DRAG_PX
                self.moved = True
                self.turn(self.down[1], steps)
        else:
            self.hover = self.describe(self.find(pos))

    def wheel(self, pos, dy):
        for key, rect in self.body_rects.items():
            if rect.collidepoint(pos) and key in self.track_rects:
                self.scroll[key] = min(self.track_rects[key][2], max(0, self.scroll[key] - dy * ROW))
                return
        what = self.find(pos)
        if what and what[0] == "knob" and dy:
            self.turn(what[1], dy)

    def key(self, event, down):
        act = self.keymap.get(event.key)
        if not act:
            return
        kind, arg = act
        if kind == "enc":
            if down:
                delta = -arg[1] if (event.mod & pygame.KMOD_RSHIFT) else arg[1]
                for i, knob in enumerate(L.KNOBS):
                    if knob.enc == arg[0]:
                        self.turn(i, delta)
        elif down and any(L.KEYS[i].bit == arg for i in self.latched):
            for i in [i for i in self.latched if L.KEYS[i].bit == arg]:
                self.unlatch(i)                       # its keyboard key lets a held step key go
        elif down != (event.key in self.keys_down):
            if down:
                self.keys_down[event.key] = arg
            else:
                self.keys_down.pop(event.key, None)
            self.link.send(f"bit {arg[0]} {arg[1]} {int(down)}")

    # ---- the app's side -------------------------------------------------

    def pump(self):
        self.flush()
        for item in self.link.take():
            if item[0] == "screen":
                self.have_screen = True
                _, y, rows, width, data = item
                strip = pygame.image.frombuffer(data, (width, rows), "BGRA")
                self.screen.blit(strip, (-L.LCD_ORIGIN[0], y - L.LCD_ORIGIN[1]))
                # The app's frame has its last column and row in light grey, where nothing else on the screen has an edge: a bright line
                # along two sides. The bezel is black there.
                self.screen.fill((0, 0, 0), (L.LCD_W - 1, 0, 1, L.LCD_H))
                self.screen.fill((0, 0, 0), (0, L.LCD_H - 1, L.LCD_W, 1))
            elif item[0] == "lamps":
                self.lamps = item[1]
            elif item[0] == "up":
                self.up_at = pygame.time.get_ticks()
                self.analogue()
            elif item[0] == "down":
                self.latched.clear()
                self.have_screen = False
                self.up_at = None
                self.screen.fill((0, 0, 0))
                self.lamps = bytes(128)
                for player in (self.master, self.phones):
                    if player:
                        player.reset()

    # ---- drawing --------------------------------------------------------

    def sprite(self, maker, *state):
        got = self.sprites.get((maker, state))
        if got is None:
            img, x, y = maker(*state)
            got = self.sprites[(maker, state)] = (surface(img), x, y)
        return got

    def ring(self, size):
        """The amber ring of a held key, smooth at the corners: drawn at four times the size and brought down."""
        got = self.sprites.get(("ring", size))
        if got is None:
            n = 4
            big = pygame.Surface((size[0] * n, size[1] * n), pygame.SRCALPHA)
            pygame.draw.rect(big, (255, 190, 60), big.get_rect(), 2 * n, border_radius=7 * n)
            got = self.sprites[("ring", size)] = pygame.transform.smoothscale(big, size)
        return got

    def draw(self):
        win = self.win
        win.fill(art.bg())
        win.blit(self.face, (self.ox, 0))
        if self.mod_page:
            win.blit(pygame.transform.smoothscale(self.render_mod_page(), self.lcd_rect.size), self.lcd_rect)
        elif self.have_screen:
            win.blit(pygame.transform.smoothscale(self.screen, self.lcd_rect.size), self.lcd_rect)
        else:
            self.draw_boot(self.lcd_rect)
        held_bits = set(self.keys_down.values())
        held = self.down[1] if self.down and self.down[0] == "key" else None
        if self.down and self.down[0] == "bit":
            held_bits.add(self.down[1])
        for i, key in enumerate(L.KEYS):
            level = L.lamp_level(self.lamps, key.lamp) if key.lamp is not None else 0
            if level == 1 and key.dim_is_off:
                level = 0
            rgb = L.rgb_lamp(self.lamps, key.rgb) if key.rgb is not None else None
            if rgb and not any(rgb):
                rgb = None
            down = i == held or i in self.held_keys or i in self.latched or (key.bit in held_bits and key.bit is not None)
            if key.kind in ("pad", "step"):         # no white of their own: the unit's lamps are all they show (a pad's own flash on a
                down = False                        # press comes from the app, and a step key shows none), held or not
            if level or rgb or down:
                surf, x, y = self.sprite(art.key_sprite, i, self.scale, level, rgb, down)
                win.blit(surf, (x + self.ox, y))
        for i in self.latched:                      # held by a right click: an amber ring, as the strip's pinned finger is amber
            x0, y0, x1, y1 = L.KEYS[i].bounds()
            ring = pygame.Rect(self.ox + int(x0 * self.scale), int(y0 * self.scale), int((x1 - x0) * self.scale), int((y1 - y0) * self.scale))
            ring = ring.inflate(6, 6)
            win.blit(self.ring(ring.size), ring.topleft)
        for i, knob in enumerate(L.KNOBS):
            down = bool(self.down and self.down == ("knob", i)) or \
                (knob.push in held_bits and knob.push is not None)
            if knob.look != "knob":
                surf, x, y = self.sprite(art.knob_sprite, i, self.scale, self.knob_step[i], down)
                win.blit(surf, (x + self.ox, y))
        if self.strip is not None:      # the finger on the strip
            sx0, sy0, _, sy1 = L.STRIP
            y = sy1 - 20 - (sy1 - sy0 - 40) * self.strip / 127
            r = pygame.Rect(self.ox + int((sx0 + 26) * self.scale), int((y - 5) * self.scale),
                            int(58 * self.scale), max(3, int(10 * self.scale)))
            pygame.draw.rect(win, (255, 190, 60) if self.pinned else (150, 200, 255), r,
                             border_radius=3)
        cap = self.cap
        sx, st, sb = L.SLIDER
        win.blit(cap, cap.get_rect(center=(self.ox + int(sx * self.scale),
                                           int((st + (sb - st) * self.slider) * self.scale))))
        self.key_rects = []
        if self.dock:
            self.draw_dock()
        if self.lift:
            self.apply_key()
        if self.rec:
            w, h = win.get_size()
            self.rec.frame(win.subsurface((0, 0, w, h - STATUS_H)))       # the window as it is, the status line and the menu not in it
        self.draw_status()
        if self.menu_open:
            self.draw_menu()
        pygame.display.flip()

    def draw_boot(self, rect):
        """The screen before the app has drawn: the emulator is not there, or
        the app is starting, which takes about half a minute."""
        win = self.win
        pygame.draw.rect(win, (0, 0, 0), rect)
        small = rect.width < 500
        title_font, text_font = (self.font, self.small) if small else (self.big, self.font)
        now = pygame.time.get_ticks()
        if self.up_at is None:
            title, note = "WAITING FOR THE EMULATOR", "start it with start.py"
            done = None
        else:
            title, note = "STARTING UP", "the app takes about half a minute"
            done = min(0.97, (now - self.up_at) / 1000 / BOOT_S)
        t = title_font.render(title, True, (225, 228, 232))
        win.blit(t, t.get_rect(center=(rect.centerx, rect.centery - rect.height // 9)))
        bar = pygame.Rect(0, 0, rect.width // 2, max(4, rect.height // 60))
        bar.center = (rect.centerx, rect.centery + rect.height // 30)
        pygame.draw.rect(win, (40, 41, 45), bar, border_radius=3)
        if done is None:                    # nothing to measure: a light going to and fro
            k = abs((now / 1400) % 2 - 1)
            lit = pygame.Rect(bar.left + int((bar.width - bar.width // 5) * k), bar.top,
                              bar.width // 5, bar.height)
        else:
            lit = pygame.Rect(bar.left, bar.top, max(bar.height, int(bar.width * done)), bar.height)
        pygame.draw.rect(win, (150, 220, 120), lit, border_radius=3)
        t = text_font.render(note, True, (150, 152, 158))
        win.blit(t, t.get_rect(center=(rect.centerx, bar.bottom + rect.height // 12)))

    def draw_dock(self):
        win = self.win
        shown = self.render_mod_page() if self.mod_page else self.screen      # the page of mods replaces the app's screen here too
        if not self.have_screen and not self.mod_page:
            self.draw_boot(self.dock)
        elif self.dock.size == shown.get_size():
            win.blit(shown, self.dock)
        else:
            win.blit(pygame.transform.smoothscale(shown, self.dock.size), self.dock)
        pygame.draw.rect(win, (46, 47, 51), self.dock.inflate(2, 2), 1)
        self.key_rects.append(self.dock.inflate(2, 2))
        self.mod_rects = []
        if not self.show_lamps:
            self.fold_rects = []
            self.body_rects = {}
            self.track_rects = {}
            self.draw_panel(self.dock.left, self.dock.bottom + (SECTION_GAP if self.tidy else 18))
            return
        held = self.down[1] if self.down and self.down[0] == "bit" else None
        if self.grid:
            label = self.font.render("Buttons not identified yet (id, frame byte.bit)", True,
                                     (170, 172, 178))
            win.blit(label, (self.dock.left, self.grid_y - 22))
        for r, bit in self.grid:
            pygame.draw.rect(win, (70, 72, 80) if bit == held else (26, 27, 30), r, border_radius=4)
            pygame.draw.rect(win, (90, 92, 98), r, 1, border_radius=4)
            t = self.small.render(f"{L.BUTTON_IDS[bit]:02x}  {bit[0]}.{bit[1]}", True,
                                  (225, 228, 232))
            win.blit(t, t.get_rect(center=r.center))
        label = self.font.render("Lamp diagnostics: every two-level lamp by id, as the app "
                                 "sets it (F12 closes)", True, (170, 172, 178))
        win.blit(label, (self.dock.left, self.lamp_y - 22))
        for r, lamp in self.lamp_cells:
            level = L.lamp_level(self.lamps, lamp)
            fill = ((26, 27, 30), (110, 96, 24), (255, 225, 60))[level]
            pygame.draw.rect(win, fill, r, border_radius=4)
            t = self.small.render(f"{lamp:02x}", True, (10, 10, 10) if level > 1 else (200, 203, 208))
            win.blit(t, t.get_rect(center=r.center))

    def draw_panel(self, x, y):
        """Under the large screen: the installed mods (if the patch on the USB drive carries any) and what the mouse and
        the keyboard do, each a section that folds (click its title) and scrolls (the wheel, or its bar) when it does
        not fit: the two share the height there is."""
        win = self.win
        width = self.dock.width
        bottom = int(L.BODY[3] * self.scale) - 1 if self.tidy else win.get_size()[1] - STATUS_H - 8     # level with the foot of the unit
        gap = SECTION_GAP if self.tidy else 8
        sections = []
        if self.mods.items:
            sections.append(("mods", "Installed mods (USB)", "click a switch - takes effect as the app runs",
                             sum(h for _, _, h in self.mod_rows()) + DETAIL_H + 8, self.draw_mods_body))
        sections.append(("help", "Controls", "", len(HELP) * 24 + 4, self.draw_help_body))
        free = bottom - y - HEAD * len(sections) - gap * (len(sections) - 1)
        views = {}
        open_ = [s for s in sections if not self.fold[s[0]]]
        if len(open_) == 1:
            views[open_[0][0]] = min(open_[0][3], max(0, free))
        elif len(open_) == 2:
            first = min(open_[0][3], max(free // 2, free - open_[1][3], free - 130))   # the second keeps five rows
            views[open_[0][0]] = max(0, first)
            views[open_[1][0]] = max(0, min(open_[1][3], free - first))
        for key, title, hint, content, body in sections:
            top = y
            head = pygame.Rect(x, y, width, HEAD - 4)
            pygame.draw.rect(win, (26, 27, 30), head, border_radius=4)
            ax, ay = head.left + 12, head.centery        # a triangle: pointing right when folded, down when open
            tri = [(ax - 4, ay - 5), (ax - 4, ay + 5), (ax + 4, ay)] if self.fold[key] else \
                [(ax - 5, ay - 3), (ax + 5, ay - 3), (ax, ay + 4)]
            pygame.draw.polygon(win, (190, 192, 198), tri)
            t = self.font.render(title, True, (225, 228, 232))
            win.blit(t, (head.left + 28, head.top + 3))
            if hint and not self.fold[key]:
                t2 = self.font.render(hint, True, (150, 152, 158))
                win.blit(t2, (head.left + 28 + t.get_width() + 14, head.top + 3))
            self.fold_rects.append((head, key))
            y += HEAD
            if self.fold[key]:
                self.frame_section(pygame.Rect(x, top, width, HEAD - 4))
                y += gap
                continue
            view = views.get(key, 0)
            extra = DETAIL_H + 8 if key == "mods" else 0     # the mods' list has the mod's text under it, not scrolled
            content -= extra
            view_all, view = view, max(0, view - extra)
            body_rect = pygame.Rect(x, y, width, view)
            most = max(0, content - view)
            self.scroll[key] = min(self.scroll[key], most)
            win.set_clip(body_rect)
            body(x, y - self.scroll[key], width - (12 if most else 0), body_rect)
            win.set_clip(None)
            self.body_rects[key] = body_rect
            if key == "mods":
                self.draw_mod_detail(x, y + view + 8, width)
            if most:
                track = pygame.Rect(x + width - 8, y, 8, view)
                size = max(24, view * view // content)
                thumb = pygame.Rect(track.left, y + int((view - size) * self.scroll[key] / most), 8, size)
                pygame.draw.rect(win, (26, 27, 30), track, border_radius=4)
                pygame.draw.rect(win, (110, 112, 120) if self.thumb and self.thumb[0] == key else (80, 82, 90), thumb,
                                 border_radius=4)
                self.track_rects[key] = (track, thumb, most)
            self.frame_section(pygame.Rect(x, top, width, y + view_all - top))
            y += view_all + gap

    def frame_section(self, r):
        """A thin line round a section of the side panel, closed, as the cards of the reels are (and the large screen above it)."""
        if self.outline:
            pygame.draw.rect(self.win, (46, 47, 51), r.inflate(2, 2), 1, border_radius=5)
        self.key_rects.append(r.inflate(2, 2))

    def mod_rows(self):
        """The list's rows, top to bottom: ("group", the heading, height) where the group changes, ("mod", the mod, height)."""
        rows, group = [], None
        for mod in self.mods.items:
            if mod["group"] and mod["group"] != group:
                group = mod["group"]
                rows.append(("group", group, ROW))
            rows.append(("mod", mod, ROW))
        return rows

    def wrap(self, text, width, limit):
        """`text` in lines of at most `width` pixels, at most `limit` of them (the last ends in ... if there is more)."""
        lines, line = [], ""
        for word in text.split():
            if line and self.font.size(line + " " + word)[0] > width:
                lines.append(line)
                line = word
            else:
                line = (line + " " + word) if line else word
        lines.append(line)
        if len(lines) > limit:
            lines = lines[:limit]
            while lines[-1] and self.font.size(lines[-1] + "...")[0] > width:
                lines[-1] = lines[-1].rsplit(" ", 1)[0] if " " in lines[-1] else lines[-1][:-1]
            lines[-1] += "..."
        return lines

    def draw_mods_body(self, x, y, width, clip):
        """The mods, grouped as the website groups them: a switch, the title and the key of each. The mouse on a row shows
        the mod's text under the list. A switch (and the title beside it) can be clicked where it is drawn."""
        win = self.win
        mouse = pygame.mouse.get_pos()
        for kind, what, height in self.mod_rows():
            if y + height >= clip.top and y <= clip.bottom:
                if kind == "group":
                    t = self.small.render(what.upper(), True, (150, 152, 158))
                    win.blit(t, (x + 2, y + 10))
                else:
                    mod = what
                    row = pygame.Rect(x, y - 3, width, ROW - 2)
                    if row.collidepoint(mouse) and clip.collidepoint(mouse) and not self.hover_pinned:
                        self.mod_hover = mod["name"]
                    if self.mod_hover == mod["name"]:
                        pygame.draw.rect(win, (26, 27, 30), row, border_radius=4)
                    on = mod["on"]
                    t = self.small.render("ON" if on else "OFF", True, (10, 10, 10) if on else (150, 152, 158))
                    r = pygame.Rect(x + 4, y - 1, 40, 20)
                    pygame.draw.rect(win, (150, 220, 120) if on else (40, 41, 45), r, border_radius=4)
                    win.blit(t, t.get_rect(center=r.center))
                    t = self.font.render(mod["title"], True, (225, 228, 232))
                    win.blit(t, (x + 56, y))
                    key = self.font.render(mod["name"], True, (130, 132, 138))
                    win.blit(key, (x + 56 + t.get_width() + 10, y))
                    if mod["status"] in ("beta", "wip"):
                        tag = self.small.render("BETA" if mod["status"] == "beta" else "WIP", True, (150, 152, 158))
                        tx = x + 56 + t.get_width() + 20 + key.get_width()
                        pygame.draw.rect(win, (110, 112, 120), (tx, y + 1, tag.get_width() + 10, 16), 1, border_radius=3)
                        win.blit(tag, (tx + 5, y + 3))
                    hit = pygame.Rect(x, y - 3, 56 + t.get_width(), 24).clip(clip)
                    if hit.width and hit.height:
                        self.mod_rects.append((hit, mod["name"]))
            y += height

    def render_mod_page(self):
        """The list of mods as a page of the unit's own screen (800x480, the look of its lists: a title bar, rows, the one pointed at
        lit), for a recording that shows the mods on the unit's screen. It is what the mods' side panel says, in the unit's style."""
        if self._page_fonts is None:
            self._page_fonts = {name: pygame.font.SysFont("arial", size, bold=bold) for name, size, bold in
                                (("title", 24, False), ("row", 22, False), ("key", 16, False), ("group", 14, True), ("text", 17, False))}
        f = self._page_fonts
        page = pygame.Surface((L.LCD_W, L.LCD_H))
        page.fill((0, 0, 0))
        pygame.draw.rect(page, (10, 26, 56), (0, 0, L.LCD_W, 34))
        page.blit(f["title"].render("MODS", True, (235, 238, 245)), (16, 4))
        on = sum(1 for m in self.mods.items if m["on"])
        count = f["key"].render("%d of %d on" % (on, len(self.mods.items)), True, (150, 160, 180))
        page.blit(count, (L.LCD_W - count.get_width() - 16, 9))
        box = pygame.Rect(8, L.LCD_H - 76, L.LCD_W - 16, 68)
        top = 40
        groups = len({m["group"] for m in self.mods.items if m["group"]})
        need = 22 * groups + 25 * len(self.mods.items)
        fit = min(1.0, (box.top - 6 - top) / float(max(1, need)))             # a longer list is packed closer
        y, group = float(top), None
        for mod in self.mods.items:
            if mod["group"] and mod["group"] != group:
                group = mod["group"]
                page.blit(f["group"].render(group.upper(), True, (130, 134, 146)), (16, y + 4))
                y += 22 * fit
            lit = self.mod_hover == mod["name"]
            ry = int(y)
            row = pygame.Rect(8, ry, L.LCD_W - 16, int(24 * fit) or 1)
            pygame.draw.rect(page, (224, 225, 232) if lit else (24, 24, 24), row)
            pill = pygame.Rect(16, ry + 2, 46, max(10, int(20 * fit)))
            pygame.draw.rect(page, (150, 220, 120) if mod["on"] else (60, 60, 66), pill, border_radius=4)
            label = f["key"].render("ON" if mod["on"] else "OFF", True, (10, 10, 10) if mod["on"] else (170, 172, 178))
            page.blit(label, label.get_rect(center=pill.center))
            title = f["row"].render(mod["title"], True, (10, 10, 10) if lit else (235, 238, 245))
            page.blit(title, (76, ry + 24 * fit / 2 - title.get_height() / 2))
            key = f["key"].render(mod["name"], True, (90, 92, 100) if lit else (130, 134, 146))
            page.blit(key, (76 + title.get_width() + 12, ry + 24 * fit / 2 - key.get_height() / 2 + 1))
            y += 25 * fit
        pygame.draw.rect(page, (18, 18, 20), box)
        mod = next((m for m in self.mods.items if m["name"] == self.mod_hover), None)
        if mod:
            side, self.font = self.font, f["text"]               # wrap() measures with the font the lines are drawn in
            try:
                lines = self.wrap(mod["page"], box.width - 24, 3)
            finally:
                self.font = side
            for i, line in enumerate(lines):
                page.blit(f["text"].render(line, True, (205, 208, 214)), (box.left + 12, box.top + 6 + 20 * i))
        return page

    def draw_mod_detail(self, x, y, width):
        """The text of the mod the mouse was last on: the website's own words, then what it needs."""
        win = self.win
        box = pygame.Rect(x, y, width, DETAIL_H)
        pygame.draw.rect(win, (20, 21, 24), box, border_radius=4)
        mod = next((m for m in self.mods.items if m["name"] == self.mod_hover), None)
        if not mod:
            t = self.font.render("Point at a mod to read what it does.", True, (110, 112, 120))
            win.blit(t, (x + 12, y + 10))
            return
        room = width - 24
        lines = [(l, (200, 203, 208)) for l in self.wrap(mod["page"], room, 3)]
        notes = []
        if mod["status"] == "beta":
            notes.append("Still being tested")
        if mod["requires"]:
            notes.append("Also installs " + ", ".join(mod["requires"]))
        if mod["needs"]:
            notes.append(mod["needs"])
        for note in notes[:5 - len(lines)]:
            lines.append((self.wrap("› " + note, room, 1)[0], (150, 152, 158)))
        for i, (text, color) in enumerate(lines):
            win.blit(self.font.render(text, True, color), (x + 12, y + 8 + 18 * i))

    def draw_help_body(self, x, y, width, clip):
        win = self.win
        for i, (keys, what) in enumerate(HELP):
            cy = y + i * 24
            if cy + 20 < clip.top or cy > clip.bottom:
                continue
            t = self.font.render(keys, True, (225, 228, 232))
            win.blit(t, (x + 8, cy))
            t = self.font.render(what, True, (150, 152, 158))
            win.blit(t, (x + 138, cy))

    def draw_sound(self, x, top):
        """The status line's sound part: the MASTER / PHONES switch for the main
        device, then the devices. Returns where it ends."""
        win = self.win
        self.listen_rect = pygame.Rect(0, 0, 0, 0)
        if self.master:
            left = x
            for i, name in enumerate(("MASTER", "PHONES")):
                on = self.listen[0] == i
                t = self.small.render(name, True, (10, 10, 10) if on else (150, 152, 158))
                r = pygame.Rect(x, top + 4, t.get_width() + 14, STATUS_H - 8)
                pygame.draw.rect(win, (150, 220, 120) if on else (40, 41, 45), r,
                                 border_top_left_radius=4 if i == 0 else 0,
                                 border_bottom_left_radius=4 if i == 0 else 0,
                                 border_top_right_radius=4 if i else 0,
                                 border_bottom_right_radius=4 if i else 0)
                win.blit(t, t.get_rect(center=r.center))
                x = r.right
            self.listen_rect = pygame.Rect(left, top, x - left, STATUS_H)
            text = f"on {self.master.name}"
            dry, late = getattr(self.master, "dry", 0), getattr(self.master, "late", 0)
            if dry or late:
                text += f" ({dry} dry, {late} late)"       # the app was late with its sound, the deck was late asking for it
        else:
            text = "no sound"
        if self.phones:
            text += f"  \u00b7  phones also on {self.phones.name}"
        if self.recorder:
            text += f"  \u00b7  in: {self.recorder.name}"
        t = self.font.render(text, True, (150, 220, 120))
        win.blit(t, (x + 8, top + 5))
        return x + 8 + t.get_width()


    def draw_menu(self):
        """The tools menu, over the window's lower right corner."""
        win = self.win
        w, h = win.get_size()
        self.menu_items = items = self.tool_items()
        height = len(items) * MENU_ROW + 10
        bottom = h - (STATUS_H if self.show_status else 0) - 4
        self.menu_panel = panel = pygame.Rect(w - MENU_W - 8, bottom - height, MENU_W, height)
        pygame.draw.rect(win, (24, 25, 28), panel, border_radius=6)
        pygame.draw.rect(win, (70, 72, 80), panel, 1, border_radius=6)
        mouse = pygame.mouse.get_pos()
        self.menu_rects = []
        for i, (label, kind, state, _) in enumerate(items):
            r = pygame.Rect(panel.left + 4, panel.top + 5 + i * MENU_ROW, MENU_W - 8, MENU_ROW)
            if r.collidepoint(mouse):
                pygame.draw.rect(win, (44, 46, 52), r, border_radius=4)
            x = r.left + 10
            if kind == "check":
                box = pygame.Rect(r.left + 8, r.centery - 6, 12, 12)
                pygame.draw.rect(win, (150, 220, 120) if state() else (40, 41, 45), box, border_radius=3)
                pygame.draw.rect(win, (110, 112, 120), box, 1, border_radius=3)
                x = r.left + 30
            if kind == "stepper":                    # a triangle at each end: a click on the left half is less, on the right more
                mid = r.centery
                pygame.draw.polygon(win, (150, 152, 158), [(r.left + 10, mid), (r.left + 17, mid - 5), (r.left + 17, mid + 5)])
                pygame.draw.polygon(win, (150, 152, 158), [(r.right - 10, mid), (r.right - 17, mid - 5), (r.right - 17, mid + 5)])
                x = r.left + 26
            t = self.font.render(label() if callable(label) else label, True, (225, 228, 232))
            win.blit(t, (x, r.centery - t.get_height() // 2))
            self.menu_rects.append((r, i))

    def draw_tools_button(self, right, top):
        """The TOOLS button, its right edge at `right`. Returns where it is."""
        win = self.win
        t = self.small.render("TOOLS", True, (10, 10, 10) if self.menu_open else (200, 203, 208))
        r = pygame.Rect(right - t.get_width() - 24, top + 4, t.get_width() + 24, STATUS_H - 8)
        pygame.draw.rect(win, (150, 220, 120) if self.menu_open else (40, 41, 45), r, border_radius=4)
        win.blit(t, (r.left + 8, r.centery - t.get_height() // 2))
        tip = [(r.right - 14, r.centery + 2), (r.right - 6, r.centery + 2), (r.right - 10, r.centery - 3)]
        pygame.draw.polygon(win, (10, 10, 10) if self.menu_open else (200, 203, 208), tip)
        self.tools_rect = r
        return r

    def draw_status(self):
        w, h = self.win.get_size()
        over = self.copy_rect.collidepoint(pygame.mouse.get_pos())
        self.bench_rect = pygame.Rect(0, 0, 0, 0)
        self.tools_rect = pygame.Rect(0, 0, 0, 0)
        self.copy_rect = pygame.Rect(0, 0, 0, 0)
        if not self.show_status:
            # Hidden: the TOOLS button alone comes up when the mouse goes to the foot of the window, so that the line (in the menu) and the
            # menu can always be reached
            x, y = pygame.mouse.get_pos()
            if pygame.mouse.get_focused() and y >= h - STATUS_H:
                self.draw_tools_button(w - 8, h - STATUS_H)
            return
        bar = pygame.Rect(0, h - STATUS_H, w, STATUS_H)
        pygame.draw.rect(self.win, (18, 18, 20), bar)
        state = "Running" if self.link.connected and self.have_screen else \
            "Starting up" if self.link.connected else \
            f"Waiting for the emulator on {self.link.addr[0]}:{self.link.addr[1]}"
        color = (150, 220, 120) if self.link.connected else (240, 180, 70)
        t = self.font.render(state, True, color)
        self.win.blit(t, (10, bar.top + 5))
        x = 10 + t.get_width()
        if self.link.connected:
            x = self.draw_sound(x + 14, bar.top)
        self.status_w = x - 10
        left = max(self.ox + self.face_w, 10 + self.status_w + 30)
        # From the right: the tools button, the level, how fast the sound comes, how much waits to be played, deckbench's decks. Each has a
        # place of the width of the most it can say, so that what one says changing does not move the rest (what does not fit is left out)
        win = self.win
        x = self.draw_tools_button(w - 8, bar.top).left - 14
        waiting = getattr(self.master, "waiting_ms", None)
        places = []
        if self.rec:
            places.append(("rec", self.font.size("REC 00:00:00")[0] + 14))
        if self.link.connected:
            places += [("level", 72), ("speed", self.font.size("\u00d70.00")[0])]
            if waiting:
                places.append(("waits", self.font.size("waits 1000 of 1000 ms")[0]))
        if self.bench and self.bench.up:
            places.append(("bench", self.font.size(self.bench.text())[0]))      # the last, so that its words changing moves nothing else
        for kind, width in places:
            if x - width <= left + 260:
                break
            place = pygame.Rect(x - width, bar.top, width, STATUS_H)
            if kind == "rec":
                seconds = int(self.rec.seconds()) if self.rec else 0
                pygame.draw.circle(win, (230, 80, 70), (place.left + 5, bar.top + STATUS_H // 2), 4)
                t = self.font.render("REC %02d:%02d" % (seconds // 60, seconds % 60) if seconds < 3600 else "REC %d:%02d:%02d" % (seconds // 3600, seconds // 60 % 60, seconds % 60), True, (230, 80, 70))
                win.blit(t, (place.left + 14, bar.top + 5))
            elif kind == "level":
                bar_rect = pygame.Rect(place.left, bar.top + 9, 64, 8)
                level, hold, clipped = self.meter.level()
                pygame.draw.rect(win, (40, 41, 45), bar_rect, border_radius=2)
                fill = pygame.Rect(bar_rect.left, bar_rect.top, int(bar_rect.width * level), bar_rect.height)
                colour = (230, 80, 70) if level > 0.95 else (240, 180, 70) if level > 0.85 else (150, 220, 120)
                pygame.draw.rect(win, colour, fill, border_radius=2)
                pygame.draw.rect(win, (225, 228, 232), (bar_rect.left + min(bar_rect.width - 2, int(bar_rect.width * hold)), bar_rect.top, 2, 8))
                if clipped:
                    pygame.draw.rect(win, (230, 80, 70), (bar_rect.right + 2, bar_rect.top, 4, 8))
            elif kind == "speed":
                speed = self.meter.speed()
                if speed is not None:
                    t = self.font.render("\u00d7%.2f" % speed, True, (150, 220, 120) if 0.97 <= speed <= 1.04 else (240, 180, 70))
                    win.blit(t, (place.right - t.get_width(), bar.top + 5))
            elif kind == "waits":
                t = self.font.render(f"waits {waiting()} of {self.master.wait_ms} ms", True, (150, 152, 158))
                win.blit(t, (place.right - t.get_width(), bar.top + 5))
            elif kind == "bench":
                t = self.font.render(self.bench.text(), True, (150, 220, 120) if self.bench.on else (150, 152, 158))
                win.blit(t, (place.left, bar.top + 5))               # from the left: its words change in length
                self.bench_rect = pygame.Rect(place.left, bar.top, min(t.get_width(), width), STATUS_H)
            x = place.left - 14
        # What is under the mouse, or when nothing is, the last thing done (a click copies it)
        room = pygame.Rect(left, bar.top, max(0, x - left), STATUS_H)
        if self.hover:
            text, colour = self.hover, (225, 228, 232)
        elif self.notice[0] and pygame.time.get_ticks() < self.notice[1]:
            text, colour = self.notice[0], (240, 180, 70)
        elif self.last_action:
            text = f"last: {self.last_action}" + ("    click to copy" if over else "")
            colour = (170, 172, 178) if over else (120, 122, 128)
        else:
            text, colour = "", (0, 0, 0)
        if text and room.width > 40:
            t = self.font.render(text, True, colour)
            win.set_clip(room)
            win.blit(t, (left, bar.top + 5))
            win.set_clip(None)
            if not self.hover:
                self.copy_rect = pygame.Rect(left, bar.top, min(t.get_width(), room.width), STATUS_H)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7310)
    ap.add_argument("--height", type=int, default=0, help="window height in pixels")
    ap.add_argument("--audio", metavar="NAME", help="play on the device whose name has NAME in it")
    ap.add_argument("--no-audio", action="store_true", help="do not play the app's sound")
    ap.add_argument("--audio-buffer", type=int, default=audio.BUFFER_MS, metavar="MS",
                    help="sound to have waiting before playing starts, in milliseconds (default %d): more is steadier and later"
                         % audio.BUFFER_MS)
    ap.add_argument("--audio-block", type=int, default=audio.PERIOD, metavar="FRAMES",
                    help="frames the sound card is given at a time (default %d): a bigger one rides out the deck being busy "
                         "(the `late` count), at as much more delay (8192 is 186 ms)" % audio.PERIOD)
    ap.add_argument("--key", nargs="?", const=4, type=int, metavar="LEVEL",
                    help="the background is black and the unit and the cards of the side panel are at least LEVEL (of 255, 4 by default, "
                         "and on unless this is a recording) bright, so that a luma key of a few points takes out only what is round "
                         "them, for a screen recording to key. The status line is not kept off black: crop it, or hide it (F9)")
    ap.add_argument("--no-key", action="store_true", help="the background is whatever it is: no lift of the blacks (--key's opposite)")
    ap.add_argument("--no-outline", action="store_true", help="no thin line round the sections of the side panel")
    ap.add_argument("--bench", metavar="URL", default=BENCH_URL,
                    help="deckbench's page, asked for how many of its decks are on and playing (shown in the status line, a click opens "
                         "the page; default %s, where start.py starts it)" % BENCH_URL)
    ap.add_argument("--mute", action="store_true",
                    help="play nothing, but show the MASTER / PHONES switch as if a sound device were there (for a recording)")
    ap.add_argument("--listen", choices=("master", "phones"), default="master",
                    help="the output the main device plays at start (Tab switches)")
    ap.add_argument("--headphones", metavar="NAME",
                    help="play the headphone output on the device whose name has NAME in it")
    ap.add_argument("--input", metavar="NAME",
                    help="feed the app's input from the recording device whose name has NAME in it")
    ap.add_argument("--input-tcp", metavar="HOST:PORT",
                    help="feed the app's input from a TCP stream of raw stereo 16-bit 44.1 kHz samples instead of a "
                         "recording device: deckbench's --audio-port, a drum loop in time with its decks")
    ap.add_argument("--no-input", action="store_true", help="feed the app's input silence")
    ap.add_argument("--list-audio", action="store_true", help="print the sound devices and quit")
    ap.add_argument("--compact", action="store_true",
                    help="start without the side panel (the large screen; F10 shows it)")
    ap.add_argument("--face", choices=("flat", "real"), default=os.environ.get("DJS_FACE", "real"),
                    help="how the face is drawn: real (black gloss, bevels, chrome and brushed metal, shadows) or flat (dark "
                         "grey plastic, the first look; default $DJS_FACE, else real)")
    ap.add_argument("--usb", metavar="DIR",
                    help="the emulator's USB folder, to show and switch the mods of a patch on it")
    ap.add_argument("--modlist", metavar="FILE",
                    help="the list of mods the patch carries (modlist.txt in the folder the emulator opened it in)")
    ap.add_argument("--hover", metavar="MOD",
                    help="start with this mod's text shown under the list of mods (for a picture)")
    ap.add_argument("--record", metavar="MP4",
                    help="record the window as video and the master output as FILE.f32, until FILE.stop exists "
                         "(see app/capture.py, which tools/demo.py uses)")
    ap.add_argument("--fps", type=int, default=0, help="frames a second of --record (25 by default) and of REC (30)")
    ap.add_argument("--captures", metavar="DIR", default=CAPTURES,
                    help="where REC (in the tools menu, F7) puts its recordings: a video with its sound (.mp4) and the sound alone (.wav) "
                         "(default %s, which git ignores)" % CAPTURES)
    ap.add_argument("--width", type=int, default=0, help="window width in pixels")
    ap.add_argument("--snapshot", metavar="PNG",
                    help="draw one frame after a few seconds, save it and quit")
    args = ap.parse_args()

    pygame.init()
    if args.list_audio:
        print("Playback:\n  " + "\n  ".join(audio.devices()))
        print("Recording:\n  " + "\n  ".join(audio.devices(True)))
        return
    master = audio.Silent() if args.mute else None if args.no_audio else audio.Player(audio.pick(args.audio), args.audio_buffer, args.audio_block)
    phones = audio.Player(audio.pick(args.headphones), args.audio_buffer, args.audio_block) if args.headphones else None
    outputs = (master, phones)

    listen = [1 if args.listen == "phones" else 0]

    capture = []

    meter = Meter()
    decks = []

    def play(which, data):
        if which == 0:
            meter.feed(data)
        if decks and decks[0].rec and which == decks[0].listen[0]:      # what is heard: the output the MASTER / PHONES switch has chosen
            decks[0].rec.sound(data, 0)
        if capture:
            capture[0].sound(data, which)
        if master and which == listen[0]:
            master.feed(data)
        if phones and which == 1:
            phones.feed(data)
    desk_w, desk_h = pygame.display.get_desktop_sizes()[0]
    h = args.height or min(desk_h - 110, 1060)
    face_w = int(L.W * (h - STATUS_H) / L.H)
    margin = 0 if args.record else edge(h)
    w = face_w + 2 * margin if args.compact else min(desk_w - 40, margin + face_w + L.LCD_W + DOCK_PAD + margin + 1)
    if args.record and not args.compact:
        w = face_w + L.LCD_W + 2 * DOCK_PAD       # a recording does not depend on the size of the desktop
    w = args.width or w
    link = Link(args.host, args.port, audio=play)
    recorder = None
    if args.input_tcp:
        host, _, port = args.input_tcp.rpartition(":")
        recorder = audio.StreamRecorder(link.send_input, host or "127.0.0.1", int(port))
    elif not args.no_input:
        try:
            recorder = audio.Recorder(link.send_input, audio.pick(args.input, True))
        except Exception as e:           # no recording device, or it is refused
            print(f"no input: {e}", file=sys.stderr)
    art.set_style(args.face)
    deck = Deck(link, (w, h), outputs, recorder, listen, Mods(args.usb, args.modlist), tidy=not args.record)
    bench_host, _, bench_port = (args.input_tcp or BENCH_AUDIO).rpartition(":")
    deck.input_makers = {"system": lambda: audio.Recorder(link.send_input, audio.pick(args.input, True)),
                         "bench": lambda: audio.StreamRecorder(link.send_input, bench_host or "127.0.0.1", int(bench_port))}
    deck.input_kind = "bench" if args.input_tcp else "system" if recorder else "none"
    deck._system = None if args.input_tcp else recorder
    if not args.record:
        deck.bench = BenchWatch(args.bench)
    if args.record:
        capture.append(Capture(args.record, (w, h), args.fps or 25))
        deck.fold["help"] = True              # the list of mods gets the room the controls' reminder takes
    deck.meter = meter
    decks.append(deck)
    link.log = lambda line: decks[0].rec.step(line) if decks[0].rec else None
    deck.captures = args.captures
    deck.rec_fps = args.fps or 30
    deck.rec_ok = not args.record
    deck.mod_hover = args.hover
    deck.hover_pinned = bool(args.hover)
    deck.lift = max(0, min(args.key, 40)) if args.key is not None else 0 if (args.record or args.no_key) else 4
    deck.outline = not (args.record or args.no_outline)
    if deck.lift:
        deck.layout()
    if args.compact:
        deck.show_dock = False
        deck.layout()
    clock = pygame.time.Clock()
    started = pygame.time.get_ticks()
    running = True
    while running:
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            elif e.type == pygame.VIDEORESIZE:
                deck.layout()
            elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                deck.press(e.pos)
            elif e.type == pygame.MOUSEBUTTONUP and e.button == 1:
                deck.release(e.pos)
            elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 3:
                if deck.find(e.pos) == ("slider",):
                    deck.slider = 0.5
                    deck.analogue()
                elif deck.find(e.pos) == ("strip",):
                    deck.pin(e.pos)
                else:
                    deck.latch(e.pos)
            elif e.type == pygame.MOUSEMOTION:
                deck.motion(e.pos)
            elif e.type == pygame.MOUSEWHEEL:
                deck.wheel(pygame.mouse.get_pos(), e.y)
            elif e.type == pygame.KEYDOWN and e.key == pygame.K_TAB:
                deck.switch_output()
            elif e.type == pygame.KEYDOWN and e.key == pygame.K_F7 and deck.rec_ok:
                deck.toggle_rec()
            elif e.type == pygame.KEYDOWN and e.key == pygame.K_F8:
                deck.toggle_menu()
            elif e.type == pygame.KEYDOWN and e.key == pygame.K_F9:
                deck.toggle_status()
            elif e.type == pygame.KEYDOWN and e.key == pygame.K_F10:
                deck.toggle_dock()
            elif e.type == pygame.KEYDOWN and e.key == pygame.K_F12:
                deck.toggle_lamps()
            elif e.type in (pygame.KEYDOWN, pygame.KEYUP):
                deck.key(e, e.type == pygame.KEYDOWN)
        deck.pump()
        deck.draw()
        if capture:
            for command in capture[0].commands():
                if command[0] == "hover" and len(command) > 1:
                    deck.mod_hover = command[1].strip()
                    deck.hover_pinned = True
                elif command[0] == "toggle" and len(command) > 1:
                    deck.mods.toggle(command[1].strip())
                elif command[0] == "page" and len(command) > 1:
                    deck.mod_page = command[1].strip() == "mods"
                elif command[0] == "slider" and len(command) > 1:      # `slider POS`: the tempo slider, 0 at the top to 1 at the foot
                    deck.slider = min(1.0, max(0.0, float(command[1])))
                    deck.link.send(f"word {L.SLIDER_WORD} {deck.slider_value()}")
                elif command[0] == "key" and len(command) > 1:         # `key NAME 1|0`: a key held down or let go, as the mouse does
                    name, _, state = command[1].partition(" ")
                    for i, key in enumerate(L.KEYS):
                        if key.name == name and key.bit:
                            if state.strip() == "1":
                                deck.held_keys.add(i)
                            else:
                                deck.held_keys.discard(i)
                            deck.link.send(f"bit {key.bit[0]} {key.bit[1]} {1 if state.strip() == '1' else 0}")
                elif command[0] == "send" and len(command) > 1:        # `send LINE`: a command line for the app, from a recording's steps
                    deck.replay(command[1].strip())
                elif command[0] == "knob" and len(command) > 1:        # `knob NAME DELTA`: turns a knob, and the picture of it, as the mouse wheel does
                    name, _, delta = command[1].partition(" ")
                    for i, knob in enumerate(L.KNOBS):
                        if knob.name == name:
                            deck.turn(i, int(delta))
            capture[0].frame(deck.win)
            if capture[0].stopped():
                running = False
        if args.snapshot and pygame.time.get_ticks() - started > 4000:
            pygame.image.save(deck.win, args.snapshot)
            running = False
        clock.tick(FPS)
    link.close()
    if deck.rec:                                 # the window is closed while recording: the file is finished first
        rec, deck.rec = deck.rec, None
        rec.finish(print, wait=True)
    if capture:
        capture[0].close()
    for dev in (master, phones, deck.recorder):
        if dev:
            dev.close()
    pygame.display.quit()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)                          # not pygame.quit(): see audio.Player.close


if __name__ == "__main__":
    main()
