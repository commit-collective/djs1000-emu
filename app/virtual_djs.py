#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""The virtual DJS-1000: the running app drawn as the machine, in one window.

    python app/virtual_djs.py [--host 127.0.0.1] [--port 7310]
                              [--audio NAME | --no-audio] [--list-audio]

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

The master output plays on the system's default sound device, or on the
one whose name contains --audio's NAME (--list-audio prints them).

Controls whose place in the panel's frame is not known yet are drawn but do
nothing. The frame's button bits that no control uses are in the grid under
the large screen, with every two-level lamp beside them: press one and see
what the app does, to find out which control it is (docs/panel-protocol.md).

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

TITLE = "Virtual DJS-1000"
BG = (5, 5, 5)
DOCK_PAD = 16
STATUS_H = 26
FPS = 60
DRAG_PX = 7                              # mouse travel for one encoder step

# Keyboard keys for controls that are not drawn as a Key or Knob.
EXTRA_KEYS = {
    pygame.K_BACKSPACE: ("bit", (1, 3)),
    pygame.K_c: ("bit", (1, 2)),         # cancel in dialogs (button id 5)
    pygame.K_RETURN: ("bit", (1, 1)),
    pygame.K_KP_ENTER: ("bit", (1, 1)),
    pygame.K_COMMA: ("enc", (0, -1)),
    pygame.K_PERIOD: ("enc", (0, 1)),
}
KEYCAPS = {"Esc": pygame.K_ESCAPE, "-": pygame.K_MINUS}


def surface(img):
    mode = "RGBA" if img.mode == "RGBA" else "RGB"
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    surf = pygame.image.frombytes(img.tobytes(), img.size, mode)
    return surf.convert_alpha() if mode == "RGBA" else surf.convert()


class Deck:
    def __init__(self, link, size, player=None):
        self.link = link
        self.player = player
        self.win = pygame.display.set_mode(size, pygame.RESIZABLE)
        pygame.display.set_caption(TITLE)
        self.font = pygame.font.SysFont("arial", 14)
        self.small = pygame.font.SysFont("arial", 11)
        self.screen = pygame.Surface((L.LCD_W, L.LCD_H)).convert()
        self.screen.fill((0, 0, 0))
        self.lamps = bytes(128)
        self.down = None                 # what the mouse holds: (kind, ...)
        self.keys_down = {}              # keyboard key -> bit held
        self.knob_step = [knob.at for knob in L.KNOBS]
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
        if room >= 360:
            k = min(1.0, room / L.LCD_W)
            self.dock = pygame.Rect(self.face_w + DOCK_PAD, DOCK_PAD, int(L.LCD_W * k),
                                    int(L.LCD_H * k))
            self._grid(self.dock.left, self.dock.bottom + 34, self.dock.width)

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
        self.lamp_y = y + rows * (30 + gap) + 30
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
        for r, bit in self.grid:
            if r.collidepoint(pos):
                return ("bit", bit)
        if pos[0] >= self.face_w:
            return None
        x, y = self.to_units(pos)
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
        if what[0] == "bit":
            byte, bit = what[1]
            return f"unknown button  id {L.BUTTON_IDS[what[1]]:#04x}  frame byte {byte} bit {bit}"
        if what[0] == "knob":
            knob = L.KNOBS[what[1]]
            how = f"encoder {knob.enc}" if knob.enc is not None else "not identified yet"
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
        if knob.enc is not None:
            self.link.send(f"enc {knob.enc} {delta}")

    def press(self, pos):
        what = self.find(pos)
        if not what:
            return
        self.down = what
        if what[0] == "lcd":
            self.link.send(f"touch 1 {what[1]} {what[2]}")
        elif what[0] == "bit":
            self.link.send(f"bit {what[1][0]} {what[1][1]} 1")
        elif what[0] == "knob":
            self.drag_y = pos[1]
            self.moved = False
        else:
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
        elif what[0] == "knob":
            knob = L.KNOBS[what[1]]
            if knob.push and not self.moved:
                self.link.send(f"tap {knob.push[0]} {knob.push[1]}")
        else:
            key = L.KEYS[what[1]]
            if key.pad is not None:
                self.link.send(f"pad {key.pad} 0 0")
            elif key.bit:
                self.link.send(f"bit {key.bit[0]} {key.bit[1]} 0")

    def motion(self, pos):
        if self.down and self.down[0] == "lcd":
            p = self.lcd_point(pos)
            if p:
                self.link.send(f"touch 2 {p[0]} {p[1]}")
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
                delta = -arg[1] if (event.mod & pygame.KMOD_SHIFT) else arg[1]
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
        for item in self.link.take():
            if item[0] == "screen":
                _, y, rows, width, data = item
                strip = pygame.image.frombuffer(data, (width, rows), "BGRA")
                self.screen.blit(strip, (-L.LCD_ORIGIN[0], y - L.LCD_ORIGIN[1]))
            elif item[0] == "lamps":
                self.lamps = item[1]
            elif item[0] == "down":
                self.lamps = bytes(128)
                if self.player:
                    self.player.reset()

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
        win.blit(pygame.transform.smoothscale(self.screen, self.lcd_rect.size), self.lcd_rect)
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
        cap = self.cap
        sx, st, sb = L.SLIDER
        win.blit(cap, cap.get_rect(center=(int(sx * self.scale), int((st + sb) / 2 * self.scale))))
        if self.dock:
            self.draw_dock()
        self.draw_status()
        pygame.display.flip()

    def draw_dock(self):
        win = self.win
        if self.dock.size == self.screen.get_size():
            win.blit(self.screen, self.dock)
        else:
            win.blit(pygame.transform.smoothscale(self.screen, self.dock.size), self.dock)
        pygame.draw.rect(win, (46, 47, 51), self.dock.inflate(2, 2), 1)
        if not self.grid:
            return
        label = self.font.render("Buttons not identified yet (id, frame byte.bit) "
                                 "— hold one and watch the screen", True, (170, 172, 178))
        win.blit(label, (self.dock.left, self.grid_y - 22))
        held = self.down[1] if self.down and self.down[0] == "bit" else None
        for r, bit in self.grid:
            pygame.draw.rect(win, (70, 72, 80) if bit == held else (26, 27, 30), r, border_radius=4)
            pygame.draw.rect(win, (90, 92, 98), r, 1, border_radius=4)
            t = self.small.render(f"{L.BUTTON_IDS[bit]:02x}  {bit[0]}.{bit[1]}", True,
                                  (225, 228, 232))
            win.blit(t, t.get_rect(center=r.center))
        label = self.font.render("Two-level lamps by id, as the app sets them", True,
                                 (170, 172, 178))
        win.blit(label, (self.dock.left, self.lamp_y - 22))
        for r, lamp in self.lamp_cells:
            level = L.lamp_level(self.lamps, lamp)
            fill = ((26, 27, 30), (90, 80, 20), (170, 150, 30), (255, 225, 60))[level]
            pygame.draw.rect(win, fill, r, border_radius=4)
            t = self.small.render(f"{lamp:02x}", True, (10, 10, 10) if level > 1 else (200, 203, 208))
            win.blit(t, t.get_rect(center=r.center))

    def draw_status(self):
        w, h = self.win.get_size()
        bar = pygame.Rect(0, h - STATUS_H, w, STATUS_H)
        pygame.draw.rect(self.win, (18, 18, 20), bar)
        state = "connected" if self.link.connected else \
            f"waiting for the app on {self.link.addr[0]}:{self.link.addr[1]} (scripts/run.sh)"
        color = (150, 220, 120) if self.link.connected else (240, 180, 70)
        if self.link.connected:
            state += f"  \u00b7  sound: {self.player.name}" if self.player else "  \u00b7  no sound"
        t = self.font.render(state, True, color)
        self.win.blit(t, (10, bar.top + 5))
        t = self.font.render(self.hover, True, (225, 228, 232))
        self.win.blit(t, (max(self.face_w * 3 // 5, 460), bar.top + 5))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7310)
    ap.add_argument("--height", type=int, default=0, help="window height in pixels")
    ap.add_argument("--audio", metavar="NAME", help="play on the device whose name has NAME in it")
    ap.add_argument("--no-audio", action="store_true", help="do not play the app's sound")
    ap.add_argument("--list-audio", action="store_true", help="print the playback devices and quit")
    ap.add_argument("--snapshot", metavar="PNG",
                    help="draw one frame after a few seconds, save it and quit")
    args = ap.parse_args()

    pygame.init()
    if args.list_audio:
        print("\n".join(audio.devices()))
        return
    player = None if args.no_audio else audio.Player(audio.pick(args.audio))
    desk_w, desk_h = pygame.display.get_desktop_sizes()[0]
    h = args.height or min(desk_h - 110, 1060)
    face_w = int(L.W * (h - STATUS_H) / L.H)
    w = min(desk_w - 40, face_w + L.LCD_W + 2 * DOCK_PAD)
    link = Link(args.host, args.port, audio=player.feed if player else None)
    deck = Deck(link, (w, h), player)
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
            elif e.type == pygame.MOUSEMOTION:
                deck.motion(e.pos)
            elif e.type == pygame.MOUSEWHEEL:
                deck.wheel(pygame.mouse.get_pos(), e.y)
            elif e.type in (pygame.KEYDOWN, pygame.KEYUP):
                deck.key(e, e.type == pygame.KEYDOWN)
        deck.pump()
        deck.draw()
        if args.snapshot and pygame.time.get_ticks() - started > 4000:
            pygame.image.save(deck.win, args.snapshot)
            running = False
        clock.tick(FPS)
    link.close()
    if player:
        player.close()
    pygame.quit()


if __name__ == "__main__":
    main()
