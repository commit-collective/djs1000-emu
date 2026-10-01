# SPDX-License-Identifier: GPL-2.0-or-later
"""Draws the DJS-1000's face: every pixel of the app's chrome is made here.

Nothing is loaded from disk except a system font. Shapes are drawn with
Pillow at SS times the target size and scaled down, which gives the curves
their anti-aliasing.

The face is a static body (face()) with every control in its unlit look, plus
small sprites for whatever changes (key_sprite(), knob_sprite(),
slider_cap()): a key lit at some level or colour, a key held down, a knob at
an angle. The view stacks them on the body and redraws a sprite only when
its state changes.
"""

import math
import os
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import layout as L

SS = 2                                   # supersampling factor
GLOW = 12                                # units of margin a sprite keeps for its glow

BG = (5, 5, 5)
BODY = (33, 34, 37)
BODY_EDGE = (58, 59, 63)
GLOSS = (11, 11, 13)
KEY_FILL = (13, 13, 15)
PRINT = (225, 228, 232)
UNLIT_PAD = (44, 45, 50)
CHROME = (196, 198, 204)

_FONTS = {
    True: ("arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"),
    False: ("arial.ttf", "Arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"),
}
_FONT_DIRS = (os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
              "/System/Library/Fonts/Supplemental", "/Library/Fonts",
              "/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/liberation")


@lru_cache(maxsize=None)
def _font_file(bold):
    for name in _FONTS[bold]:
        for folder in _FONT_DIRS:
            path = os.path.join(folder, name)
            if os.path.exists(path):
                return path
    return None


@lru_cache(maxsize=256)
def font(px, bold=True):
    path = _font_file(bold)
    if path:
        return ImageFont.truetype(path, max(6, int(round(px))))
    return ImageFont.load_default()


def _mix(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def lamp_color(rgb):
    """A colour lamp's value as it looks: the app sends small numbers for dim
    lamps, which a screen would show as black."""
    m = max(rgb)
    if m == 0:
        return None
    k = (m / 255.0) ** 0.45 * 255.0 / m
    return tuple(min(255, int(c * k)) for c in rgb)


class _Canvas:
    """A drawing surface in face units: (x0, y0) is its top-left corner."""

    def __init__(self, x0, y0, w, h, scale, fill=(0, 0, 0, 0)):
        self.k = scale * SS
        self.x0, self.y0 = x0, y0
        self.size = (max(1, int(math.ceil(w * scale))), max(1, int(math.ceil(h * scale))))
        self.img = Image.new("RGBA", (self.size[0] * SS, self.size[1] * SS), fill)
        self.d = ImageDraw.Draw(self.img)

    def p(self, x, y):
        return ((x - self.x0) * self.k, (y - self.y0) * self.k)

    def box(self, b):
        return (*self.p(b[0], b[1]), *self.p(b[2], b[3]))

    def rect(self, b, radius=0, fill=None, outline=None, width=0):
        self.d.rounded_rectangle(self.box(b), radius=radius * self.k, fill=fill, outline=outline,
                                 width=max(1, int(round(width * self.k))) if outline else 0)

    def circle(self, cx, cy, r, fill=None, outline=None, width=0):
        self.d.ellipse(self.box((cx - r, cy - r, cx + r, cy + r)), fill=fill, outline=outline,
                       width=max(1, int(round(width * self.k))) if outline else 0)

    def line(self, pts, fill, width):
        self.d.line([self.p(*q) for q in pts], fill=fill, width=max(1, int(round(width * self.k))))

    def poly(self, pts, fill):
        self.d.polygon([self.p(*q) for q in pts], fill=fill)

    def text(self, x, y, s, size, fill=PRINT, anchor="mm", bold=True):
        self.d.text(self.p(x, y), s, font=font(size * self.k, bold), fill=fill, anchor=anchor)

    def glow(self, draw, color, radius=5, strength=1.0):
        """Draws a shape with draw(canvas, fill) and lays its blur under what follows."""
        layer = _Canvas(self.x0, self.y0, 1, 1, 1)
        layer.k, layer.size = self.k, self.size
        layer.img = Image.new("RGBA", self.img.size, (0, 0, 0, 0))
        layer.d = ImageDraw.Draw(layer.img)
        draw(layer, (*color, int(255 * min(1.0, strength))))
        self.img.alpha_composite(layer.img.filter(ImageFilter.GaussianBlur(radius * self.k)))
        self.d = ImageDraw.Draw(self.img)

    def done(self):
        return self.img.resize(self.size, Image.LANCZOS)


def _key_shape(c, key, fill, inset=0):
    if key.circle:
        cx, cy, r = key.circle
        c.circle(cx, cy, r - inset, fill=fill)
    else:
        x0, y0, x1, y1 = key.box
        radius = {"pad": 9, "step": 7, "dome": (y1 - y0) / 2, "led": 3}.get(key.kind, 4)
        c.rect((x0 + inset, y0 + inset, x1 - inset, y1 - inset), radius=radius, fill=fill)


def _symbol(c, key, color):
    cx, cy, r = key.circle
    if key.symbol == "play":
        c.poly([(cx - 20, cy - 11), (cx - 20, cy + 11), (cx - 3, cy)], color)
        c.rect((cx + 4, cy - 10, cx + 9, cy + 10), fill=color)
        c.rect((cx + 14, cy - 10, cx + 19, cy + 10), fill=color)
    elif key.symbol == "stop":
        c.rect((cx - 7, cy - 7, cx + 7, cy + 7), radius=1, fill=color)
    elif key.symbol == "rec":
        c.circle(cx, cy, 8, fill=color)


def _draw_key(c, key, level, rgb, down):
    """One key on a canvas. level 0-3 is its lamp, rgb its colour lamp's
    (r, g, b) or None."""
    lit = _mix((0, 0, 0), key.color, (0, 0.45, 0.75, 1.0)[level]) if level else None
    kind = key.kind
    if kind in ("pad", "step"):
        color = lamp_color(rgb) if rgb else None
        base = color or UNLIT_PAD
        if color:
            c.glow(lambda g, f: _key_shape(g, key, f), color, 6, 0.55)
        _key_shape(c, key, _mix(base, (0, 0, 0), 0.35))
        _key_shape(c, key, base, inset=3)
        x0, y0, x1, y1 = key.box
        if color:
            c.glow(lambda g, f: g.rect((x0 + 18, y0 + 18, x1 - 18, y1 - 18), radius=12, fill=f),
                   _mix(color, (255, 255, 255), 0.6), 14, 0.2 + 0.5 * max(rgb) / 255)
        if down:
            _key_shape(c, key, (255, 255, 255, 70), inset=3)
    elif kind == "rect":
        edge = lit or CHROME
        if lit:
            c.glow(lambda g, f: _key_shape(g, key, f), lit, 5, 0.8)
        _key_shape(c, key, edge)
        _key_shape(c, key, _mix(KEY_FILL, lit, 0.25) if lit else KEY_FILL, inset=3)
        x0, y0, x1, y1 = key.box
        c.text((x0 + x1) / 2, (y0 + y1) / 2, key.label, key.font, fill=lit or PRINT)
        if down:
            _key_shape(c, key, (255, 255, 255, 60), inset=3)
    elif kind == "bar":
        edge = lit or _mix(key.color, (0, 0, 0), 0.25)
        if lit:
            c.glow(lambda g, f: _key_shape(g, key, f), lit, 5, 0.8)
        _key_shape(c, key, edge)
        _key_shape(c, key, (6, 6, 8) if not down else (60, 62, 70), inset=3)
    elif kind == "led":
        if lit:
            c.glow(lambda g, f: _key_shape(g, key, f), lit, 4, 0.9)
        _key_shape(c, key, lit or _mix(key.color, (0, 0, 0), 0.72))
    elif kind == "big":
        cx, cy, r = key.circle
        if lit:
            c.glow(lambda g, f: g.circle(cx, cy, r + 2, fill=f), lit, 7, 0.9)
        c.circle(cx, cy, r, fill=(12, 12, 13))
        c.circle(cx, cy, r - 5, fill=lit or (120, 122, 128))
        c.circle(cx, cy, r - 12, fill=(70, 72, 77) if not down else (104, 106, 112))
        c.circle(cx, cy, r - 12, outline=(150, 152, 158), width=1.5)
        _symbol(c, key, lit or (228, 230, 235))
    else:                                   # dome
        if lit:
            c.glow(lambda g, f: _key_shape(g, key, f), lit, 5, 0.9)
        _key_shape(c, key, lit or (74, 75, 80))
        fill = (20, 20, 22) if not down else (58, 60, 66)
        if key.name == "fx_on":
            fill = _mix(fill, key.color, 0.55 if not lit else 1.0)
        _key_shape(c, key, fill, inset=3)
        if key.label:
            cx, cy, _ = key.circle
            c.text(cx, cy, key.label, key.font, fill=lit or PRINT)
        elif key.symbol:
            _symbol(c, key, lit or _mix(key.color, (0, 0, 0), 0.35))
        elif key.circle and key.circle[2] > 12:
            cx, cy, r = key.circle
            c.circle(cx, cy, r * 0.28, fill=lit or (48, 49, 53))


@lru_cache(maxsize=2048)
def _key_sprite(index, scale, level, rgb, down):
    key = L.KEYS[index]
    x0, y0, x1, y1 = key.bounds()
    c = _Canvas(x0 - GLOW, y0 - GLOW, x1 - x0 + 2 * GLOW, y1 - y0 + 2 * GLOW, scale)
    _draw_key(c, key, level, rgb, down)
    return c.done()


def key_sprite(index, scale, level=0, rgb=None, down=False):
    """(image, x, y): key `index` in a state, and where it goes, in pixels."""
    if rgb:                                 # nearby colours share a sprite
        rgb = tuple(c & 0xFC for c in rgb)
        if not any(rgb):
            rgb = None
    key = L.KEYS[index]
    x0, y0, _, _ = key.bounds()
    return (_key_sprite(index, scale, level, rgb, down),
            int((x0 - GLOW) * scale), int((y0 - GLOW) * scale))


def _draw_knob(c, knob, angle, down=False):
    cx, cy, r = knob.circle
    if knob.look == "selector":
        c.circle(cx, cy, r + 26, fill=(7, 7, 8))
        c.circle(cx, cy, r, fill=(238, 240, 245))
        c.circle(cx, cy, r - 9, fill=(24, 24, 27) if not down else (50, 51, 56))
        for i in range(12):
            a = angle + i * math.pi / 6
            c.circle(cx + (r - 9) * math.cos(a), cy + (r - 9) * math.sin(a), 6, fill=(238, 240, 245))
        c.circle(cx, cy, r - 14, fill=(24, 24, 27) if not down else (50, 51, 56))
        c.circle(cx, cy, r - 26, fill=(34, 35, 39))
        return
    c.circle(cx, cy, r, fill=(70, 71, 76))
    c.circle(cx, cy, r - 3, fill=(8, 8, 9))
    c.circle(cx, cy, r * 0.62, fill=(40, 41, 45))
    c.circle(cx, cy, r * 0.5, fill=(22, 22, 25))
    if knob.look != "pot":                  # an encoder turns without end: no mark
        return
    c.line([(cx + r * 0.2 * math.cos(angle), cy + r * 0.2 * math.sin(angle)),
            (cx + r * 0.6 * math.cos(angle), cy + r * 0.6 * math.sin(angle))], (235, 238, 245), 3)


@lru_cache(maxsize=512)
def _knob_sprite(index, scale, step, down):
    knob = L.KNOBS[index]
    cx, cy, r = knob.circle
    m = r + 28 if knob.look == "selector" else r + 2
    c = _Canvas(cx - m, cy - m, 2 * m, 2 * m, scale)
    if knob.look == "selector":
        angle = -math.pi / 2 + step * (2 * math.pi / 12 / 4)
    else:                                   # a pot: 270 degrees from MIN to MAX
        angle = math.radians(135 + 270 * step / L.POT_STEPS)
    _draw_knob(c, knob, angle, down)
    return c.done()


def knob_sprite(index, scale, step=0, down=False):
    knob = L.KNOBS[index]
    cx, cy, r = knob.circle
    m = r + 28 if knob.look == "selector" else r + 2
    step = step % 4 if knob.look == "selector" else max(0, min(L.POT_STEPS, step))
    return (_knob_sprite(index, scale, step, down),
            int((cx - m) * scale), int((cy - m) * scale))


@lru_cache(maxsize=8)
def slider_cap(scale):
    c = _Canvas(-42, -26, 84, 52, scale)
    c.rect((-40, -24, 40, 24), radius=4, fill=(20, 20, 22), outline=(96, 98, 104), width=2)
    for y in (-14, -8, 8, 14):
        c.line([(-34, y), (34, y)], (62, 63, 68), 2)
    c.line([(-38, 0), (38, 0)], (240, 242, 246), 3)
    return c.done()


@lru_cache(maxsize=4)
def face(scale):
    """The whole panel with every control unlit, as an RGB image."""
    c = _Canvas(0, 0, L.W, L.H, scale, fill=(*BG, 255))
    c.rect(L.BODY, radius=14, fill=BODY, outline=BODY_EDGE, width=2)
    c.rect(L.TOP_BLOCK, radius=8, fill=GLOSS, outline=(70, 71, 76), width=3)
    c.poly(L.KNOB_TRAY, GLOSS)
    x0, y0, x1, y1 = L.LCD
    c.rect((x0 - 20, y0 - 8, x1 + 26, y1 + 8), radius=4, fill=(4, 4, 5), outline=(46, 47, 51),
           width=2)
    c.rect(L.LCD, fill=(0, 0, 0))
    # The selector's panel and the FX strip of hatching.
    c.rect((1128, 82, 1304, 522), radius=6, fill=(17, 17, 19))
    c.rect((46, 566, 294, 588), fill=(46, 47, 51))
    c.rect((200, 316, 354, 384), fill=(30, 31, 34))
    # USB port.
    c.rect(L.USB_PORT, radius=5, fill=(190, 192, 198))
    ux0, uy0, ux1, uy1 = L.USB_PORT
    c.rect((ux0 + 7, uy0 + 7, ux1 - 7, uy1 - 14), radius=2, fill=(16, 16, 18))
    c.rect((ux0 + 20, uy0 + 34, ux1 - 20, uy1 - 22), fill=(60, 61, 66))
    # MODE block.
    c.rect((82, 766, 276, 864), radius=6, fill=(10, 10, 12), outline=(52, 53, 57), width=2)
    # Touch strip and its LEDs.
    c.rect(L.STRIP, radius=6, fill=(12, 12, 14), outline=(52, 53, 57), width=2)
    sx0, sy0, sx1, sy1 = L.STRIP
    c.rect((sx0 + 20, sy0 + 12, sx0 + 90, sy1 - 12), radius=3, fill=(40, 41, 45))
    c.rect((sx0 + 26, sy0 + 20, sx0 + 84, sy1 - 20), radius=2, fill=(26, 27, 30))
    for i in range(8):
        y = 928 + i * 42
        c.rect((224, y, 231, y + 32), radius=2, fill=(18, 60, 104))
    for y in (922, 1006, 1090, 1174):
        c.line([(248, y + 6), (258, y + 6), (258, y + 30)], (200, 203, 208), 2)
        c.line([(258, y + 52), (258, y + 76), (248, y + 76)], (200, 203, 208), 2)
    c.line([(262, 1090), (286, 1090)], (200, 203, 208), 2)
    # Pads.
    c.rect(L.PAD_FRAME, radius=6, fill=(190, 192, 198))
    px0, py0, px1, py1 = L.PAD_FRAME
    c.rect((px0 + 9, py0 + 9, px1 - 9, py1 - 9), radius=3, fill=(3, 3, 4))
    # Tempo slider.
    c.rect(L.SLIDER_FRAME, radius=8, fill=(22, 22, 25), outline=(60, 61, 66), width=2)
    sx, st, sb = L.SLIDER
    c.rect((sx - 4, st - 18, sx + 4, sb + 18), radius=3, fill=(4, 4, 5))
    for i in range(41):
        y = st + (sb - st) * i / 40
        half = 40 if i % 10 == 0 else 30
        c.line([(sx - half, y), (sx - 8, y)], (150, 152, 158), 1.5)
        c.line([(sx + 8, y), (sx + half, y)], (150, 152, 158), 1.5)
    for i in range(21):
        c.circle(1250, st + (sb - st) * i / 20, 1.6, fill=(170, 172, 178))
    c.rect((1222, 1086, 1238, 1094), radius=2, fill=(150, 200, 30))
    # NUDGE's bezel, step marks and frames.
    c.rect((1216, 1446, 1412, 1500), radius=22, fill=(12, 12, 14), outline=(52, 53, 57), width=2)
    c.rect((1238, 566, 1392, 656), radius=40, fill=(24, 24, 27))
    for n in (0, 4, 8, 12):
        x, y = L.STEP_X[n % 8], L.STEP_Y[n // 8] - 71
        c.rect((x - 31, y - 10, x + 31, y + 10), outline=PRINT, width=1.5)
    for t in L.TEXTS:
        c.text(t.x, t.y, t.text, t.size, fill=t.color, anchor=t.anchor, bold=t.bold)
    for knob in L.KNOBS:
        if knob.look == "knob":
            _draw_knob(c, knob, 0)
    for key in L.KEYS:
        _draw_key(c, key, 0, None, False)
    return c.done().convert("RGB")
