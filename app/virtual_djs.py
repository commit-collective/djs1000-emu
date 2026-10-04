#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""The virtual DJS-1000: the running app drawn as the machine, in one window.

    python app/virtual_djs.py [--host 127.0.0.1] [--port 7310]
                              [--audio NAME | --no-audio] [--headphones NAME]
                              [--input NAME | --no-input] [--list-audio]

Start the app first (scripts/run.sh); the window shows it as soon as it is
there, and again after a restart. The face's screen is the app's own, its
lamps are the ones the app lights, and its controls go to the app as the
panel's would:

  keys, pads       hold the mouse button; a pad plays harder the lower you
                   press it
  knobs, selector  mouse wheel, or drag up and down; a click pushes the
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
(--compact starts without it); F12 swaps the reminder for every two-level
lamp by id, as the app sets it (docs/panel-protocol.md).

Needs pygame-ce and Pillow (requirements.txt).
"""

import argparse
import os
import sys

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

TITLE = "Virtual DJS-1000"
BG = (5, 5, 5)
DOCK_PAD = 16
STATUS_H = 26
FPS = 60
MIN_HOLD = 120                           # ms a clicked key or pad stays down at least
BOOT_S = 24                              # about how long the app takes to draw its first screen
HELP = (                                 # the side panel's reminder: (keys, what they do)
    ("Mouse", "press keys and pads, drag or wheel knobs, touch the screen"),
    ("Right-click", "strip: leave a finger on it   \u00b7   tempo slider: centre"),
    ("Space  B  N", "PLAY/PAUSE   STOP   REC"),
    ("\u2191 \u2193   Enter   \u2190", "selector: turn, push   \u00b7   BACK (also Esc)"),
    ("F1 \u2013 F6", "the six knobs (Right Shift: the other way)"),
    ("1\u20138   Q\u2013I", "step keys 1\u20138 and 9\u201316"),
    ("P  L  X  H  M", "PROJECT   SAMPLING   FX   HOME   MODE"),
    ("Left Shift", "SHIFT"),
    ("Tab", "main sound device: MASTER / PHONES"),
    ("F10   F12", "hide this panel   \u00b7   lamp diagnostics"),
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


def surface(img):
    mode = "RGBA" if img.mode == "RGBA" else "RGB"
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    surf = pygame.image.frombytes(img.tobytes(), img.size, mode)
    return surf.convert_alpha() if mode == "RGBA" else surf.convert()


class Deck:
    def __init__(self, link, size, players=(None, None), recorder=None, listen=None, mods=None):
        self.link = link
        self.mods = mods or Mods(None)   # what a patch on the USB drive carries
        self.mod_rects = []              # (where, name): the switches drawn in the side panel
        self.master, self.phones = players
        self.recorder = recorder
        self.show_dock = True            # the large screen beside the face (F10)
        self.show_lamps = False          # under it, the lamps by id instead of the keys (F12)
        self.have_screen = False         # the app has drawn something
        self.up_at = None                # when the link came up, for the start-up bar
        self.big = pygame.font.SysFont("arial", 22, bold=True)
        self.listen = listen if listen is not None else [0]   # the output the main device plays
        self.listen_rect = pygame.Rect(0, 0, 0, 0)
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
        self.face = surface(art.face(self.scale))
        self.cap = surface(art.slider_cap(self.scale))
        self.sprites.clear()
        x0, y0, x1, y1 = (int(v * self.scale) for v in L.LCD)
        self.lcd_rect = pygame.Rect(x0, y0, x1 - x0, y1 - y0)
        room = w - self.face_w - 2 * DOCK_PAD
        self.dock = None
        self.grid = []
        self.lamp_cells = []
        if self.show_dock and room >= 360:
            k = min(1.0, room / L.LCD_W)
            self.dock = pygame.Rect(self.face_w + DOCK_PAD, DOCK_PAD, int(L.LCD_W * k),
                                    int(L.LCD_H * k))
            if self.show_lamps:
                self._grid(self.dock.left, self.dock.bottom + 34, self.dock.width)

    def toggle_dock(self):
        """Shows or hides the side panel, and sizes the window to what is left."""
        self.show_dock = not self.show_dock
        _, h = self.win.get_size()
        face_w = int(L.W * max(0.2, (h - STATUS_H) / L.H))
        w = face_w + (L.LCD_W + 2 * DOCK_PAD if self.show_dock else 0)
        w = min(w, pygame.display.get_desktop_sizes()[0][0] - 40)
        self.win = pygame.display.set_mode((w, h), pygame.RESIZABLE)
        self.layout()

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
        return pos[0] / self.scale, pos[1] / self.scale

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
        if pos[0] >= self.face_w:
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
        if what[0] == "lcd":
            return f"screen  {what[1] - 1}, {what[2] - 1}"
        if what[0] == "listen":
            return "which output the main sound device plays  \u00b7  click, or Tab"
        if what[0] == "mod":
            return f"mod {what[1]}  ·  click to switch it on or off, as the app runs"
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
            self.link.send(f"enc {knob.enc} {delta}")

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

    def press(self, pos):
        what = self.find(pos)
        if not what:
            return
        if what[0] == "listen":
            self.switch_output()
            return
        if what[0] == "mod":
            self.mods.toggle(what[1])
            return
        self.down = what
        self.down_at = pygame.time.get_ticks()
        self.flush(now=True)
        if what[0] == "slider":
            self.slide(pos)
        elif what[0] == "strip":
            self.stroke(pos)
        elif what[0] == "lcd":
            self.link.send(f"touch 1 {what[1]} {what[2]}")
        elif what[0] == "bit":
            self.link.send(f"bit {what[1][0]} {what[1][1]} 1")
        elif what[0] == "knob":
            self.drag_y = pos[1]
            self.moved = False
        elif what[0] == "key":
            key = L.KEYS[what[1]]
            if key.pad is not None:
                # How hard, of 1023: a hit begins at the pad's calibration
                # (336) and is at full velocity near 840. Harder towards the
                # bottom of the pad.
                _, y = self.to_units(pos)
                y0, y1 = key.box[1], key.box[3]
                v = int(460 + 400 * min(1.0, max(0.0, (y - y0) / (y1 - y0))))
                self.link.send(f"pad {key.pad} {v} {v}")
            elif key.bit:
                self.link.send(f"bit {key.bit[0]} {key.bit[1]} 1")

    def release(self, pos):
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
        on the unit; here its panel cycle runs at about 10 ms, slower while it
        plays, and a quick click was over before it counted."""
        self.later.append((self.down_at + MIN_HOLD, line))
        self.flush()

    def flush(self, now=False):
        t = pygame.time.get_ticks()
        for when, line in self.later:
            if now or when <= t:
                self.link.send(line)
        self.later = [(w, l) for w, l in self.later if not now and w > t]

    def motion(self, pos):
        if self.down and self.down[0] == "lcd":
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
            elif item[0] == "lamps":
                self.lamps = item[1]
            elif item[0] == "up":
                self.up_at = pygame.time.get_ticks()
                self.analogue()
            elif item[0] == "down":
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

    def draw(self):
        win = self.win
        win.fill(BG)
        win.blit(self.face, (0, 0))
        if self.have_screen:
            win.blit(pygame.transform.smoothscale(self.screen, self.lcd_rect.size), self.lcd_rect)
        else:
            self.draw_boot(self.lcd_rect)
        held_bits = set(self.keys_down.values())
        held = self.down[1] if self.down and self.down[0] == "key" else None
        if self.down and self.down[0] == "bit":
            held_bits.add(self.down[1])
        for i, key in enumerate(L.KEYS):
            level = L.lamp_level(self.lamps, key.lamp) if key.lamp is not None else 0
            rgb = L.rgb_lamp(self.lamps, key.rgb) if key.rgb is not None else None
            if rgb and not any(rgb):
                rgb = None
            down = i == held or (key.bit in held_bits and key.bit is not None)
            if level or rgb or down:
                surf, x, y = self.sprite(art.key_sprite, i, self.scale, level, rgb, down)
                win.blit(surf, (x, y))
        for i, knob in enumerate(L.KNOBS):
            down = bool(self.down and self.down == ("knob", i)) or \
                (knob.push in held_bits and knob.push is not None)
            if knob.look != "knob":
                surf, x, y = self.sprite(art.knob_sprite, i, self.scale, self.knob_step[i], down)
                win.blit(surf, (x, y))
        if self.strip is not None:      # the finger on the strip
            sx0, sy0, _, sy1 = L.STRIP
            y = sy1 - 20 - (sy1 - sy0 - 40) * self.strip / 127
            r = pygame.Rect(int((sx0 + 26) * self.scale), int((y - 5) * self.scale),
                            int(58 * self.scale), max(3, int(10 * self.scale)))
            pygame.draw.rect(win, (255, 190, 60) if self.pinned else (150, 200, 255), r,
                             border_radius=3)
        cap = self.cap
        sx, st, sb = L.SLIDER
        win.blit(cap, cap.get_rect(center=(int(sx * self.scale),
                                           int((st + (sb - st) * self.slider) * self.scale))))
        if self.dock:
            self.draw_dock()
        self.draw_status()
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
        if not self.have_screen:
            self.draw_boot(self.dock)
        elif self.dock.size == self.screen.get_size():
            win.blit(self.screen, self.dock)
        else:
            win.blit(pygame.transform.smoothscale(self.screen, self.dock.size), self.dock)
        pygame.draw.rect(win, (46, 47, 51), self.dock.inflate(2, 2), 1)
        self.mod_rects = []
        if not self.show_lamps:
            y = self.draw_mods(self.dock.left, self.dock.bottom + 22)
            self.draw_help(self.dock.left, y)
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

    def draw_mods(self, x, y):
        """Under the large screen, if the patch on the USB drive carries mods:
        a switch for each. Returns where the next thing goes."""
        win = self.win
        items = self.mods.items
        if not items:
            return y
        t = self.font.render("Installed mods (USB)", True, (225, 228, 232))
        win.blit(t, (x, y))
        t2 = self.font.render("click to switch - takes effect as the app runs", True, (150, 152, 158))
        win.blit(t2, (x + t.get_width() + 14, y))
        y += 26
        for name, on, about in items:
            t = self.small.render("ON" if on else "OFF", True, (10, 10, 10) if on else (150, 152, 158))
            r = pygame.Rect(x, y - 1, 40, 20)
            pygame.draw.rect(win, (150, 220, 120) if on else (40, 41, 45), r, border_radius=4)
            win.blit(t, t.get_rect(center=r.center))
            t = self.font.render(name, True, (225, 228, 232))
            win.blit(t, (x + 52, y))
            t2 = self.font.render(about, True, (150, 152, 158))
            win.blit(t2, (x + 52 + t.get_width() + 14, y))
            self.mod_rects.append((pygame.Rect(x, y - 3, 52 + t.get_width(), 24), name))
            y += 26
        return y + 10

    def draw_help(self, x, y):
        """Under the large screen: what the mouse and the keyboard do."""
        win = self.win
        bottom = win.get_size()[1] - STATUS_H - 8
        for keys, what in HELP:
            if y + 20 > bottom:
                break
            t = self.font.render(keys, True, (225, 228, 232))
            win.blit(t, (x, y))
            t = self.font.render(what, True, (150, 152, 158))
            win.blit(t, (x + 130, y))
            y += 24

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
        else:
            text = "no sound"
        if self.phones:
            text += f"  \u00b7  phones also on {self.phones.name}"
        if self.recorder:
            text += f"  \u00b7  in: {self.recorder.name}"
        t = self.font.render(text, True, (150, 220, 120))
        win.blit(t, (x + 8, top + 5))
        return x + 8 + t.get_width()


    def draw_status(self):
        w, h = self.win.get_size()
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
        t = self.font.render(self.hover, True, (225, 228, 232))
        self.win.blit(t, (max(self.face_w, 10 + self.status_w + 30), bar.top + 5))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7310)
    ap.add_argument("--height", type=int, default=0, help="window height in pixels")
    ap.add_argument("--audio", metavar="NAME", help="play on the device whose name has NAME in it")
    ap.add_argument("--no-audio", action="store_true", help="do not play the app's sound")
    ap.add_argument("--listen", choices=("master", "phones"), default="master",
                    help="the output the main device plays at start (Tab switches)")
    ap.add_argument("--headphones", metavar="NAME",
                    help="play the headphone output on the device whose name has NAME in it")
    ap.add_argument("--input", metavar="NAME",
                    help="feed the app's input from the recording device whose name has NAME in it")
    ap.add_argument("--no-input", action="store_true", help="feed the app's input silence")
    ap.add_argument("--list-audio", action="store_true", help="print the sound devices and quit")
    ap.add_argument("--compact", action="store_true",
                    help="start without the side panel (the large screen; F10 shows it)")
    ap.add_argument("--usb", metavar="DIR",
                    help="the emulator's USB folder, to show and switch the mods of a patch on it")
    ap.add_argument("--snapshot", metavar="PNG",
                    help="draw one frame after a few seconds, save it and quit")
    args = ap.parse_args()

    pygame.init()
    if args.list_audio:
        print("Playback:\n  " + "\n  ".join(audio.devices()))
        print("Recording:\n  " + "\n  ".join(audio.devices(True)))
        return
    master = None if args.no_audio else audio.Player(audio.pick(args.audio))
    phones = audio.Player(audio.pick(args.headphones)) if args.headphones else None
    outputs = (master, phones)

    listen = [1 if args.listen == "phones" else 0]

    def play(which, data):
        if master and which == listen[0]:
            master.feed(data)
        if phones and which == 1:
            phones.feed(data)
    desk_w, desk_h = pygame.display.get_desktop_sizes()[0]
    h = args.height or min(desk_h - 110, 1060)
    face_w = int(L.W * (h - STATUS_H) / L.H)
    w = face_w if args.compact else min(desk_w - 40, face_w + L.LCD_W + 2 * DOCK_PAD)
    link = Link(args.host, args.port, audio=play)
    recorder = None
    if not args.no_input:
        try:
            recorder = audio.Recorder(link.send_input, audio.pick(args.input, True))
        except Exception as e:           # no recording device, or it is refused
            print(f"no input: {e}", file=sys.stderr)
    deck = Deck(link, (w, h), outputs, recorder, listen, Mods(args.usb))
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
            elif e.type == pygame.MOUSEMOTION:
                deck.motion(e.pos)
            elif e.type == pygame.MOUSEWHEEL:
                deck.wheel(pygame.mouse.get_pos(), e.y)
            elif e.type == pygame.KEYDOWN and e.key == pygame.K_TAB:
                deck.switch_output()
            elif e.type == pygame.KEYDOWN and e.key == pygame.K_F10:
                deck.toggle_dock()
            elif e.type == pygame.KEYDOWN and e.key == pygame.K_F12:
                deck.toggle_lamps()
            elif e.type in (pygame.KEYDOWN, pygame.KEYUP):
                deck.key(e, e.type == pygame.KEYDOWN)
        deck.pump()
        deck.draw()
        if args.snapshot and pygame.time.get_ticks() - started > 4000:
            pygame.image.save(deck.win, args.snapshot)
            running = False
        clock.tick(FPS)
    link.close()
    for dev in (master, phones, recorder):
        if dev:
            dev.close()
    pygame.display.quit()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)                          # not pygame.quit(): see audio.Player.close


if __name__ == "__main__":
    main()
