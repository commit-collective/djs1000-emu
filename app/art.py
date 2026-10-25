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

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

import layout as L

SS = 2                                   # supersampling factor
GLOW = 12                                # units of margin a sprite keeps for its glow

# The look of the face: "real" (the default: black gloss plastic, a bevelled
# housing, a chrome frame round the pads, brushed metal on the transport keys, shadows) or "flat" (the first one: dark grey
# plastic, flat controls). Set it once, before the first drawing,
# with set_style(): the face and the sprites are made once for the style and kept.
STYLE = "real"

BG = (5, 5, 5)
BODY = (33, 34, 37)
BODY_EDGE = (58, 59, 63)
GLOSS = (11, 11, 13)
KEY_FILL = (13, 13, 15)
PRINT = (225, 228, 232)
UNLIT_PAD = (44, 45, 50)
REAL_BIG = 0.92                          # the size of the round transport keys in the real face, as a share of their place
UNLIT_REAL = (172, 175, 181)             # a pad with its lamp off: dull translucent grey (rubber, so matte)
UNLIT_STEP = (190, 193, 199)             # a step key with its lamp off: the same, a little lighter (hard plastic, so it shines)
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
        x0, y0, x1, y1 = self.box(b)
        x1, y1 = max(x1, x0 + 1), max(y1, y0 + 1)
        # Pillow refuses corners that do not fit: keep them inside a small shape.
        radius = int(min(radius * self.k, (x1 - x0 - 3) / 2, (y1 - y0 - 3) / 2))
        line = max(1, int(round(width * self.k))) if outline else 0
        if radius >= 1:
            try:
                self.d.rounded_rectangle((x0, y0, x1, y1), radius=radius, fill=fill,
                                         outline=outline, width=min(line, radius))
                return
            except ValueError:                  # still too small for Pillow's corners
                pass
        self.d.rectangle((x0, y0, x1, y1), fill=fill, outline=outline, width=line)

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

    # What the "real" style adds. Each works on the part of the canvas it covers, not on all of it: the face is big.
    def gradient_rect(self, b, radius, a, z, direction="v"):
        """A rectangle filled with a gradient from colour a (top, left, or top-left) to z. direction: v, h or d (diagonal)."""
        x0, y0, x1, y1 = (int(round(v)) for v in self.box(b))
        w, h = max(1, x1 - x0), max(1, y1 - y0)
        g = Image.linear_gradient("L")                       # black at the top to white at the bottom
        if direction == "h":
            g = g.transpose(Image.ROTATE_90)
        elif direction == "d":
            g = ImageChops.add(g, g.transpose(Image.ROTATE_90), scale=2)
        fill = ImageOps.colorize(g.resize((w, h), Image.BILINEAR), a, z).convert("RGBA")
        mask = Image.new("L", (w, h), 0)
        r = int(min(radius * self.k, w / 2 - 1, h / 2 - 1))
        if r >= 1:
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=255)
        else:
            mask.paste(255, (0, 0, w, h))
        self.img.paste(fill, (x0, y0), mask)

    def overlay(self, draw, bbox, rgba, blur=0):
        """Blends a shape (draw(ImageDraw, offset-adjusted callback)) in colour rgba over what is there, inside bbox (face units)."""
        x0, y0, x1, y1 = (int(round(v)) for v in self.box(bbox))
        pad = int(blur * self.k * 3) + 2
        lx, ly = x0 - pad, y0 - pad                          # the layer's corner, in canvas pixels
        w, h = max(1, x1 - x0) + 2 * pad, max(1, y1 - y0) + 2 * pad
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw(ImageDraw.Draw(layer), lambda x, y: ((x - self.x0) * self.k - lx, (y - self.y0) * self.k - ly), rgba)
        if blur:
            layer = layer.filter(ImageFilter.GaussianBlur(blur * self.k))
        cw, ch = self.img.size                               # only what is inside the canvas
        sx0, sy0, dx0, dy0 = max(0, -lx), max(0, -ly), max(0, lx), max(0, ly)
        sx1, sy1 = min(w, cw - lx), min(h, ch - ly)
        if sx1 > sx0 and sy1 > sy0:
            self.img.alpha_composite(layer.crop((sx0, sy0, sx1, sy1)), (dx0, dy0))

    def shade_poly(self, pts, rgba, blur=0):
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        self.overlay(lambda d, m, col: d.polygon([m(*q) for q in pts], fill=col), (min(xs), min(ys), max(xs), max(ys)), rgba, blur)

    def shade_rect(self, b, rgba, radius=0, blur=0):
        def draw(d, m, col):
            x0, y0 = m(b[0], b[1])
            x1, y1 = m(b[2], b[3])
            x0, y0, x1, y1 = int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))
            x1, y1 = max(x1, x0 + 1), max(y1, y0 + 1)                    # at a small scale it can be less than a pixel
            r = int(min(radius * self.k, (x1 - x0 - 1) / 2.0, (y1 - y0 - 1) / 2.0))
            if r >= 1:
                try:
                    d.rounded_rectangle((x0, y0, x1, y1), radius=r, fill=col)
                    return
                except ValueError:                                       # corners that do not fit: a plain one
                    pass
            d.rectangle((x0, y0, x1, y1), fill=col)
        self.overlay(draw, b, rgba, blur)

    def shade_circle(self, cx, cy, r, rgba, blur=0):
        self.overlay(lambda d, m, col: d.ellipse((*m(cx - r, cy - r), *m(cx + r, cy + r)), fill=col),
                     (cx - r, cy - r, cx + r, cy + r), rgba, blur)


def _key_shape(c, key, fill, inset=0):
    if key.circle:
        cx, cy, r = key.circle
        c.circle(cx, cy, r - inset, fill=fill)
    else:
        x0, y0, x1, y1 = key.box
        radius = {"pad": 9, "step": 7, "dome": (y1 - y0) / 2, "led": 3}.get(key.kind, 4)
        c.rect((x0 + inset, y0 + inset, x1 - inset, y1 - inset), radius=radius, fill=fill)


def _symbol(c, key, color, s=1.0):
    """The sign on a round key, s times its size."""
    cx, cy, r = key.circle
    if key.symbol == "play":
        c.poly([(cx - 20 * s, cy - 11 * s), (cx - 20 * s, cy + 11 * s), (cx - 3 * s, cy)], color)
        c.rect((cx + 4 * s, cy - 10 * s, cx + 9 * s, cy + 10 * s), fill=color)
        c.rect((cx + 14 * s, cy - 10 * s, cx + 19 * s, cy + 10 * s), fill=color)
    elif key.symbol == "stop":
        c.rect((cx - 7 * s, cy - 7 * s, cx + 7 * s, cy + 7 * s), radius=1, fill=color)
    elif key.symbol == "rec":
        c.circle(cx, cy, 8 * s, fill=color)


def _brushed(c, cx, cy, r, dark, light, pressed=False):
    """A disc of brushed metal: two bright lobes across it, as a conic highlight, in wedges."""
    steps = 120
    for i in range(steps):
        a0, a1 = i * 360.0 / steps, (i + 1) * 360.0 / steps
        mid = math.radians((a0 + a1) / 2)
        t = 0.5 + 0.5 * math.sin(2 * mid + 0.9)
        color = _mix(dark, light, (t ** 1.3) * (0.8 if pressed else 1.0))
        c.d.pieslice(c.box((cx - r, cy - r, cx + r, cy + r)), a0, a1 + 0.6, fill=color)


def _draw_key(c, key, level, rgb, down):
    """One key on a canvas. level is its lamp (0 off, 1 dim, 2 bright), rgb
    its colour lamp's (r, g, b) or None."""
    lit = _mix((0, 0, 0), key.color, (0, 0.5, 1.0)[level]) if level else None
    kind = key.kind
    if kind in ("pad", "step"):
        color = lamp_color(rgb) if rgb else None
        base = color or ((UNLIT_STEP if kind == "step" else UNLIT_REAL) if STYLE == "real" else UNLIT_PAD)
        if color:
            c.glow(lambda g, f: _key_shape(g, key, f), color, 6, 0.55)
        x0, y0, x1, y1 = key.box
        if STYLE == "real" and kind == "step":      # a step key is flat: one plain edge, no bevel
            _key_shape(c, key, _mix(base, (0, 0, 0), 0.16))
            _key_shape(c, key, base, inset=1.5)
        else:
            if STYLE == "real":                      # a pad stands proud: it casts a shade below
                c.shade_rect((x0 + 2, y0 + 4, x1 + 2, y1 + 7), (0, 0, 0, 120), radius=10, blur=3)
            _key_shape(c, key, _mix(base, (0, 0, 0), 0.35))
            _key_shape(c, key, base, inset=3)
        if color:                                  # the soft bloom in the middle
            c.glow(lambda g, f: g.rect((x0 + 18, y0 + 18, x1 - 18, y1 - 18), radius=12, fill=f),
                   _mix(color, (255, 255, 255), 0.6), 14, 0.2 + 0.5 * max(rgb) / 255)
        if down:
            _key_shape(c, key, (255, 255, 255, 70), inset=3)
    elif kind == "rect" and STYLE == "real" and key.name in ("project", "sampling", "fx"):
        x0, y0, x1, y1 = key.box
        if lit:
            c.glow(lambda g, f: _key_shape(g, key, f), lit, 6, 0.9)
        _key_shape(c, key, (176, 178, 184))                                  # the bezel
        _key_shape(c, key, (8, 8, 10), inset=2.5)
        _key_shape(c, key, lit or (84, 86, 92), inset=4)                     # the lamp, a line
        _key_shape(c, key, (22, 22, 25) if not down else (62, 64, 70), inset=7)
        c.shade_rect((x0 + 9, y0 + 9, x1 - 9, y0 + (y1 - y0) * 0.45), (255, 255, 255, 12), radius=3)       # the gloss of its face
        c.text((x0 + x1) / 2, (y0 + y1) / 2, key.label, key.font, fill=lit or PRINT)
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
    elif kind == "big" and STYLE == "real":
        cx, cy, r = key.circle
        r *= REAL_BIG                                                         # a little smaller than the place it holds
        if lit:
            c.glow(lambda g, f: g.circle(cx, cy, r + 2, fill=f), lit, 7, 0.9)
        c.circle(cx, cy, r, fill=(6, 6, 7))                                  # a black ring round the metal
        c.circle(cx, cy, r - 1.5, outline=(58, 59, 64), width=1)
        _brushed(c, cx, cy, r - 6, (30, 31, 35), (150, 152, 158), down)      # metal right through: no centre part, dark enough for the lamp
        c.circle(cx, cy, r - 6, outline=(112, 114, 120), width=1)
        size = 0.85 if key.symbol == "play" else 0.8                         # the sign is about a quarter of the width of the metal
        if lit:
            c.glow(lambda g, f: _symbol(g, key, f, size), lit, 4, 1.0)
        _symbol(c, key, lit or (16, 16, 18), size)                           # engraved in it, dark when its lamp is off
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
        dot = STYLE == "real" and key.circle is not None and not key.label and not key.symbol
        if lit and dot:
            cx, cy, r = key.circle
            c.glow(lambda g, f: g.circle(cx, cy, r * 0.3, fill=f), lit, 4, 1.0)
        elif lit:
            c.glow(lambda g, f: _key_shape(g, key, f), lit, 5, 0.9)
        _key_shape(c, key, (74, 75, 80) if dot else (lit or (74, 75, 80)))
        fill = (20, 20, 22) if not down else (58, 60, 66)
        if key.name == "fx_on":
            fill = _mix(fill, key.color, 0.3 if not lit else 1.0)
        _key_shape(c, key, fill, inset=3)
        if key.label:
            cx, cy, _ = key.circle
            c.text(cx, cy, key.label, key.font, fill=lit or PRINT)
        elif key.symbol:
            _symbol(c, key, lit or _mix(key.color, (0, 0, 0), 0.35))
        elif STYLE == "real" and key.circle is None:                        # a pill: a light along its top edge
            x0, y0, x1, y1 = key.box
            c.shade_rect((x0 + 8, y0 + 4, x1 - 8, y0 + 9), (255, 255, 255, 40), radius=2, blur=1)
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
    if knob.look == "selector" and STYLE == "real":
        c.circle(cx, cy, r + 26, fill=(7, 7, 8))
        c.circle(cx, cy, r, fill=(120, 122, 128))                              # the chrome ring, the same all the way round
        c.circle(cx, cy, r - 1.5, fill=(226, 228, 233))
        c.circle(cx, cy, r - 6, fill=(196, 198, 204))
        c.circle(cx, cy, r - 9, fill=(11, 11, 13) if not down else (44, 45, 50))
        for i in range(48):                                                    # the knurl of the knob, which turns with it
            a = angle + i * math.tau / 48
            c.line([(cx + (r - 23) * math.cos(a), cy + (r - 23) * math.sin(a)), (cx + (r - 11) * math.cos(a), cy + (r - 11) * math.sin(a))],
                   (74, 75, 80) if i % 2 else (22, 22, 25), 2.4)
        c.circle(cx, cy, r - 24, fill=(16, 16, 18))
        c.circle(cx, cy, r - 30, fill=(26, 27, 30))
        c.circle(cx, cy, r - 38, fill=(18, 18, 20))
        return
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
    if STYLE == "real":                     # a ring that catches the light, a cap lit from the top left
        c.circle(cx, cy, r, fill=(132, 134, 140))
        c.circle(cx, cy, r - 1.5, fill=(70, 72, 77))
        c.circle(cx, cy, r - 3.5, fill=(9, 9, 11))
        c.circle(cx - r * 0.05, cy - r * 0.07, r * 0.68, fill=(44, 45, 50))
        c.circle(cx + r * 0.01, cy + r * 0.02, r * 0.58, fill=(18, 18, 21))
    else:
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
    if STYLE == "real":                       # a very dark cap, longer than the first, with a rounded grip across its middle
        c = _Canvas(-44, -38, 88, 76, scale)
        c.gradient_rect((-40, -36, 40, 36), 6, (34, 35, 39), (9, 9, 11), "v")
        c.rect((-40, -36, 40, 36), radius=6, outline=(52, 54, 59), width=1.2)
        c.gradient_rect((-42, -17, 42, 9), 6, (88, 90, 96), (28, 29, 33), "v")           # the grip, a bar across the cap that the light runs along
        c.rect((-42, -17, 42, 9), radius=6, outline=(12, 12, 14), width=1.5)
        c.line([(-36, -5), (36, -5)], (236, 238, 242), 3.2)                              # and the bright line on it
        return c.done()
    c = _Canvas(-42, -26, 84, 52, scale)
    c.rect((-40, -24, 40, 24), radius=4, fill=(20, 20, 22), outline=(96, 98, 104), width=2)
    for y in (-14, -8, 8, 14):
        c.line([(-34, y), (34, y)], (62, 63, 68), 2)
    c.line([(-38, 0), (38, 0)], (240, 242, 246), 3)
    return c.done()


def _real_body(c):
    """The case in black gloss plastic with a rim that catches the light, and the screen's housing, bevelled."""
    c.gradient_rect(L.BODY, 14, (37, 37, 40), (27, 27, 30), "v")           # about 33 in the middle, as the unit measures
    c.rect(L.BODY, radius=14, outline=(66, 67, 72), width=2)
    bx0, by0, bx1, by1 = L.BODY
    c.line([(bx0 + 16, by0 + 3), (bx1 - 16, by0 + 3)], (104, 105, 110), 2)
    c.gradient_rect(L.TOP_BLOCK, 8, (13, 13, 15), (3, 3, 4), "v")                      # glass: black, as the pads' surround
    c.rect(L.TOP_BLOCK, radius=8, outline=(98, 99, 104), width=3)
    tx0, ty0, tx1, ty1 = L.TOP_BLOCK
    c.rect((tx0 + 5, ty0 + 5, tx1 - 5, ty1 - 5), radius=6, outline=(18, 18, 20), width=2)
    c.line([(tx0 + 12, ty0 + 2), (tx1 - 12, ty0 + 2)], (150, 151, 156), 2)
    c.poly(L.KNOB_TRAY, (3, 3, 4))
    c.shade_poly([(tx1 - 150, ty0 + 4), (tx1 - 4, ty0 + 4), (tx1 - 4, ty0 + 200), (tx0 + 150, ty1 - 4), (tx0 + 4, ty1 - 4), (tx0 + 4, ty1 - 200)],
                 (255, 255, 255, 9), blur=5)                                  # and its streak of reflection
    # The unit's sides have a raised rail below the encoders, chamfered at both ends, its inner edge bright and a shade beside it.
    y0, y1 = 730, 1500
    for left in (True, False):
        def X(dx, left=left):
            return bx0 + dx if left else bx1 - dx
        c.shade_poly([(X(1), y0), (X(26), y0 + 26), (X(26), y1 - 26), (X(1), y1)], (255, 255, 255, 22))
        c.line([(X(26), y0 + 26), (X(26), y1 - 26)], (104, 105, 110), 2)
        c.line([(X(1), y0), (X(26), y0 + 26)], (92, 93, 98), 2)
        c.line([(X(1), y1), (X(26), y1 - 26)], (62, 63, 68), 2)
        c.line([(X(28), y0 + 28), (X(28), y1 - 28)], (10, 10, 12), 2)


def _stipple(c, b, base, dot, pitch=3.0, radius=0.62):
    """A rectangle of fine dots in rows, every other row shifted: the grain of the FX strip."""
    c.rect(b, fill=base)
    x0, y0, x1, y1 = b
    y, row = y0 + pitch / 2, 0
    while y < y1 - 0.3:
        x = x0 + pitch / 2 + (pitch / 2 if row % 2 else 0)
        while x < x1 - 1:
            c.circle(x, y, radius, fill=dot)
            x += pitch
        y += pitch * 0.87
        row += 1


def bg():
    """What is round the unit: pure black in the real face (the housing stands proud of the case, and nothing fills the corners
    beside it), a hair lighter in the flat one."""
    return (0, 0, 0) if STYLE == "real" else BG


def set_style(name):
    """"flat" or "real". Call it before anything is drawn: what was made in the other style is forgotten."""
    global STYLE
    if name not in ("flat", "real"):
        raise ValueError("no such face: %s" % name)
    STYLE = name
    for fn in (face, face_alpha, _key_sprite, _knob_sprite, slider_cap):
        fn.cache_clear()


@lru_cache(maxsize=4)
def face(scale):
    """The whole panel with every control unlit, as an RGB image."""
    return _face(scale, bg())


@lru_cache(maxsize=4)
def face_alpha(scale):
    """Where the unit is in face(scale): 255 on the housing, 0 round it (grey on the edge, as the edge is drawn). Found by drawing
    the face on black and on white: only what is round it differs."""
    from PIL import ImageChops
    black = face(scale).split()[1]
    white = _face(scale, (255, 255, 255)).split()[1]
    return ImageChops.subtract(Image.new("L", black.size, 255), ImageChops.subtract(white, black))


def _face(scale, background):
    c = _Canvas(0, 0, L.W, L.H, scale, fill=(*background, 255))
    real = STYLE == "real"
    if real:
        _real_body(c)
    else:
        c.rect(L.BODY, radius=14, fill=BODY, outline=BODY_EDGE, width=2)
        c.rect(L.TOP_BLOCK, radius=8, fill=GLOSS, outline=(70, 71, 76), width=3)
        c.poly(L.KNOB_TRAY, GLOSS)
    x0, y0, x1, y1 = L.LCD
    c.rect((x0 - 20, y0 - 8, x1 + 26, y1 + 8), radius=4, fill=(4, 4, 5), outline=(84, 85, 90) if real else (46, 47, 51),
           width=3 if real else 2)
    c.rect(L.LCD, fill=(0, 0, 0))
    # The selector's panel and the FX strip of hatching (the real unit has neither plate, nor a patch round FX).
    if not real:
        c.rect((1128, 82, 1304, 522), radius=6, fill=(17, 17, 19))
    if real:
        _stipple(c, (46, 566, 294, 588), (50, 51, 55), (150, 152, 157), pitch=2.7, radius=0.8)
    else:
        c.rect((46, 566, 294, 588), fill=(46, 47, 51))
    if real:
        _stipple(c, (200, 316, 354, 384), (58, 59, 63), (92, 94, 99), pitch=2.7, radius=0.7)
    else:
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
    for y in (922, 1006, 1090, 1174):
        c.line([(248, y + 6), (258, y + 6), (258, y + 30)], (200, 203, 208), 2)
        c.line([(258, y + 52), (258, y + 76), (248, y + 76)], (200, 203, 208), 2)
    c.line([(262, 1090), (286, 1090)], (200, 203, 208), 2)
    # Pads.
    px0, py0, px1, py1 = L.PAD_FRAME
    if real:                                # a chrome frame round a glossy black surface with a streak of reflection across it
        c.gradient_rect(L.PAD_FRAME, 6, (170, 172, 178), (24, 24, 27), "d")
        c.rect((px0 + 9, py0 + 9, px1 - 9, py1 - 9), radius=3, fill=(2, 2, 3))
        c.shade_poly([(px1 - 9, py0 + 9), (px1 - 9, py0 + 150), (px0 + 9, py1 - 220), (px0 + 9, py1 - 400)], (255, 255, 255, 13), blur=4)
        c.line([(px0 + 14, py0 + 3), (px1 - 14, py0 + 3)], (250, 251, 253), 2)
    else:
        c.rect(L.PAD_FRAME, radius=6, fill=(190, 192, 198))
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
    # NUDGE's bezel, step marks and frames.
    c.rect((1216, 1446, 1412, 1500), radius=22, fill=(12, 12, 14), outline=(52, 53, 57), width=2)
    c.rect((1238, 566, 1392, 656), radius=40, fill=(24, 24, 27))
    for n in (0, 4, 8, 12):
        x, y = L.STEP_X[n % 8], L.STEP_Y[n // 8] - 71
        c.rect((x - 31, y - 10, x + 31, y + 10), outline=PRINT, width=1.5)
    if real:                                # what stands on the face casts a little shade
        for knob in L.KNOBS:
            if knob.look == "knob":                      # (the encoder is round and even, with no shade to one side)
                cx, cy, r = knob.circle
                c.shade_circle(cx, cy + 5, r + 1, (0, 0, 0, 150), blur=6)
        for key in L.KEYS:
            if key.circle:
                cx, cy, r = key.circle
                c.shade_circle(cx, cy + 4, r * (REAL_BIG if key.kind == "big" else 1), (0, 0, 0, 130), blur=5)
            elif key.kind == "rect":            # the pads and step keys keep their first look: no shade
                x0, y0, x1, y1 = key.box
                c.shade_rect((x0, y0 + 4, x1, y1 + 5), (0, 0, 0, 110), radius=8, blur=4)
    for t in L.TEXTS:
        c.text(t.x, t.y, t.text, t.size, fill=t.color, anchor=t.anchor, bold=t.bold)
    if real:
        for t in L.TEXTS:
            if t.text == "WAKE UP":                  # the unit prints it in a box
                c.rect((t.x - 31, t.y - 8, t.x + 31, t.y + 8), radius=2, outline=(225, 228, 232), width=1.4)
    for knob in L.KNOBS:
        if knob.look == "knob":
            _draw_knob(c, knob, 0)
    for key in L.KEYS:
        _draw_key(c, key, 0, None, False)
    return c.done().convert("RGB")


def icon(size=256):
    """The app's icon: the unit seen from above, a screen over a grid of sixteen pads, a few lit. Drawn like the rest, at four
    times the size and scaled down; returns a Pillow RGBA image."""
    k = 4
    n = size * k
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = n / 256.0
    d.rounded_rectangle((0, 0, n - 1, n - 1), radius=int(54 * u), fill=BODY_EDGE)
    d.rounded_rectangle((6 * u, 6 * u, n - 1 - 6 * u, n - 1 - 6 * u), radius=int(48 * u), fill=GLOSS)
    d.rounded_rectangle((24 * u, 24 * u, 232 * u, 96 * u), radius=int(12 * u), fill=(3, 4, 6), outline=(70, 72, 78), width=max(1, int(3 * u)))
    wave = [(36, 62), (62, 62), (74, 40), (88, 84), (102, 48), (116, 76), (130, 62), (150, 62), (162, 44), (176, 80), (190, 62), (220, 62)]
    d.line([(x * u, y * u) for x, y in wave], fill=(235, 62, 48), width=max(1, int(5 * u)), joint="curve")
    lit = {0: (235, 62, 48), 3: (235, 62, 48), 5: (46, 120, 235), 9: (46, 120, 235), 10: (242, 176, 48), 12: (235, 62, 48), 15: (235, 62, 48)}
    for i in range(16):
        col, row = i % 4, i // 4
        x0, y0 = (24 + col * 54) * u, (112 + row * 34) * u
        d.rounded_rectangle((x0, y0, x0 + 46 * u, y0 + 28 * u), radius=int(7 * u), fill=lit.get(i, UNLIT_PAD))
    return img.resize((size, size), Image.LANCZOS)
