# SPDX-License-Identifier: GPL-2.0-or-later
"""Where everything sits on the DJS-1000's face, and what each control is.

Pure data. The face is laid out in UNITS of a 1500 x 1950 grid, the top panel
seen from straight above. Everything is drawn from scratch by art.py; no photo
or artwork is used, and the manufacturer's logo and model name are left off.

A control's `bit` is its place in the frame the panel sends the app
(docs/panel-protocol.md): (byte, bit). `lamp` is the id of its two-level lamp
in the frame the app sends back, `rgb` the index of its colour lamp. A control
with no `bit` is drawn but does nothing yet: its bit has not been identified.
A lamp's id is not its button's: each was matched by pressing the button
and seeing which lamp answered.
"""

from dataclasses import dataclass

W, H = 1500, 1950

LCD = (388, 88, 1100, 515)              # 712 x 427: the panel's 5:3
LCD_W, LCD_H = 800, 480                 # the app's screen
LCD_ORIGIN = (1, 1)                     # where the app draws it in its window
TOP_BLOCK = (182, 28, 1310, 528)
BODY = (0, 80, 1492, 1930)
KNOB_TRAY = ((305, 532), (1185, 532), (1128, 668), (362, 668))
PAD_FRAME = (370, 773, 1123, 1500)
SLIDER_FRAME = (1265, 800, 1360, 1380)
SLIDER = (1313, 860, 1320)              # x, top and bottom of the cap's travel
# The tempo slider in the panel's frame: its position, 0 at the top (-) to
# 1023 at the bottom (+), and the reading it is compared with, which the
# panel sends as the centre's.
SLIDER_WORD, SLIDER_REF, SLIDER_CENTRE = 0x58, 0x56, 512
STRIP = (122, 886, 238, 1296)           # the touch strip's well
USB_PORT = (36, 160, 128, 245)

WHITE = (235, 238, 245)
GREEN = (150, 255, 40)
LIME = (190, 255, 30)
BLUE = (40, 150, 255)
RED = (255, 40, 50)
ORANGE = (255, 150, 30)
AMBER = (255, 190, 60)


@dataclass
class Key:
    """One pressable control.

    kind picks the look (art.py): rect (a framed key with its name on it),
    dome (round, black), big (round, chrome), pad, step, bar, led (a lamp
    only). A key has a box (x0, y0, x1, y1) or a circle (cx, cy, r).
    """
    name: str
    kind: str
    box: tuple = None
    circle: tuple = None
    label: str = ""
    bit: tuple | None = None            # (byte, bit) in the panel's frame
    lamp: int | None = None             # two-level lamp id
    rgb: int | None = None              # colour lamp index, 0-31
    pad: int | None = None              # pad number, 0-15
    color: tuple = WHITE                # its light
    font: int = 17
    keycap: str = ""                    # the keyboard key that presses it too
    symbol: str = ""

    def bounds(self):
        if self.box:
            return self.box
        cx, cy, r = self.circle
        return (cx - r, cy - r, cx + r, cy + r)

    def hit(self, x, y):
        if self.circle:
            cx, cy, r = self.circle
            return (x - cx) ** 2 + (y - cy) ** 2 <= (r + 3) ** 2
        x0, y0, x1, y1 = self.box
        return x0 - 2 <= x <= x1 + 2 and y0 - 2 <= y <= y1 + 2


@dataclass
class Knob:
    """A rotary control. enc is its encoder number in the panel's frame
    (0 the rotary selector, 1-6 the knobs under the screen); None for the
    analogue ones, whose values in the frame are not identified yet."""
    name: str
    circle: tuple
    enc: int | None = None
    push: tuple | None = None           # the bit its push switch sets
    keycap: str = ""
    word: int | None = None             # a pot's 0-1023 value in the frame
    look: str = "knob"                  # knob (an encoder), selector, pot
    at: int = 0                         # a pot's position at start, 0-POT_STEPS

    def hit(self, x, y):
        cx, cy, r = self.circle
        return (x - cx) ** 2 + (y - cy) ** 2 <= (r + 4) ** 2

    def bounds(self):
        cx, cy, r = self.circle
        return (cx - r, cy - r, cx + r, cy + r)


@dataclass
class Text:
    """Printed on the panel."""
    x: float
    y: float
    text: str
    size: int = 17
    anchor: str = "mm"
    bold: bool = True
    color: tuple = (225, 228, 232)


POT_STEPS = 30                          # a pot's travel from MIN to MAX

PAD_X = (484, 659, 833, 1008)
PAD_Y = (1398, 1223, 1048, 873)         # rows from pad 1's upwards
STEP_X = (418, 512, 606, 700, 794, 887, 981, 1075)
STEP_Y = (1625, 1803)
STEP_KEYS = "12345678QWERTYUI"

# The 32 colour lamps: the pads first, then the step keys (a step switched on
# from HOME lights lamp 16 + its number).
PAD_RGB, STEP_RGB = 0, 16

KEYS = [
    # The display block.
    Key("project", "rect", box=(222, 126, 330, 172), label="PROJECT", bit=(5, 5),
        lamp=0x01, color=LIME, keycap="P"),
    Key("sampling", "rect", box=(222, 248, 330, 292), label="SAMPLING", bit=(5, 6),
        lamp=0x02, color=WHITE, keycap="L"),
    Key("fx", "rect", box=(226, 330, 330, 372), label="FX", bit=(5, 7), lamp=0x03,
        color=BLUE, keycap="X"),
    Key("back", "dome", box=(1150, 131, 1212, 166), bit=(1, 2), keycap="Esc"),
    Key("home", "dome", circle=(1268, 149, 19), bit=(1, 3), color=RED, keycap="H"),
    Key("standby", "dome", circle=(1379, 104, 9), bit=(5, 4)),
    Key("usb_stop", "dome", circle=(80, 346, 24), bit=(1, 0)),
    Key("usb_lamp", "led", box=(150, 88, 164, 102), lamp=0x00, color=WHITE),
    # FX and the strip. FX ON/OFF's lamp blinks while the effect is off.
    Key("fx_on", "dome", circle=(258, 666, 40), bit=(6, 7), lamp=0x06, color=BLUE),
    Key("mute", "rect", box=(415, 698, 553, 736), label="MUTE", bit=(1, 4), lamp=0x17),
    Key("hot_slice", "rect", box=(589, 698, 729, 736), label="HOT SLICE", bit=(1, 5),
        lamp=0x18),
    Key("slice", "rect", box=(763, 698, 903, 736), label="SLICE", bit=(1, 6), lamp=0x19),
    Key("scale", "rect", box=(938, 698, 1078, 736), label="SCALE", bit=(1, 7), lamp=0x1A),
    Key("mode", "rect", box=(98, 796, 192, 835), label="MODE", bit=(2, 5), keycap="M"),
    Key("hold", "dome", circle=(312, 1090, 20), bit=(2, 4), lamp=0x0B, color=WHITE),
    Key("shift", "rect", box=(133, 1343, 225, 1378), label="SHIFT", bit=(2, 0),
        keycap="Left Shift"),
    Key("rec", "dome", circle=(179, 1472, 30), bit=(2, 1), lamp=0x14, color=RED,
        symbol="rec", keycap="N"),
    Key("stop", "big", circle=(179, 1625, 64), bit=(2, 2), lamp=0x15, symbol="stop",
        keycap="B"),
    Key("play", "big", circle=(179, 1803, 64), bit=(2, 3), lamp=0x16, symbol="play",
        color=GREEN, keycap="Space"),
    # The right column. No lamp has been matched to SYNC and MASTER.
    Key("sync", "dome", circle=(1272, 611, 27), label="SYNC", bit=(6, 5), font=12,
        keycap="S"),
    Key("master", "dome", circle=(1355, 611, 27), label="MASTER", bit=(6, 6),
        color=ORANGE, font=11),
    Key("tempo_range", "dome", circle=(1313, 727, 19), bit=(6, 4), keycap="-"),
    Key("tempo_reset", "dome", circle=(1179, 1090, 23), bit=(6, 3)),
    Key("tempo_reset_lamp", "led", box=(1222, 1086, 1238, 1094), lamp=0x1D, color=LIME),
    Key("nudge_minus", "rect", box=(1222, 1452, 1302, 1494), label="\u2013", bit=(6, 2),
        color=AMBER, font=30),
    Key("nudge_plus", "rect", box=(1326, 1452, 1406, 1494), label="+", bit=(6, 1),
        color=AMBER, font=30),
    Key("scene", "rect", box=(1187, 1608, 1278, 1644), label="SCENE", bit=(2, 6),
        lamp=0x47),
    Key("pattern", "rect", box=(1349, 1608, 1440, 1644), label="PATTERN", bit=(2, 7),
        lamp=0x48),
]
# The four bar keys and the lamp over each (0x43 is lit on bar 1 of a one-bar
# pattern). The keys' bits and own lamps are taken in order, not seen to act.
KEYS += [Key(f"bar_{i + 1}", "bar", box=(x - 23, 1785, x + 23, 1855), bit=(5, i),
             lamp=0x3F + i, color=BLUE)
         for i, x in enumerate((1205, 1277, 1350, 1422))]
KEYS += [Key(f"bar_led_{i + 1}", "led", box=(x - 24, 1746, x + 24, 1756), lamp=0x43 + i,
             color=LIME)
         for i, x in enumerate((1205, 1277, 1350, 1422))]
# MODE's four lamps, in the order MODE steps through them.
KEYS += [Key(f"mode_led_{name}", "led", box=(198, y - 5, 204, y + 5), lamp=0x07 + i,
             color=LIME)
         for i, (name, y) in enumerate((("pitch", 781), ("repeat", 804), ("user1", 827),
                                        ("user2", 850)))]
# The strip's eight lamps, 0x0c at the bottom (the strip's 0) to 0x13 at the
# top (its 127).
KEYS += [Key(f"strip_led_{i + 1}", "led", box=(224, 1222 - i * 42, 231, 1254 - i * 42),
             lamp=0x0C + i, color=BLUE)
         for i in range(8)]
KEYS += [Key(f"step_{n + 1}", "step",
             box=(STEP_X[n % 8] - 29, STEP_Y[n // 8] - 55, STEP_X[n % 8] + 29, STEP_Y[n // 8] + 55),
             bit=(3 + n // 8, n % 8), rgb=STEP_RGB + n, keycap=STEP_KEYS[n])
         for n in range(16)]
KEYS += [Key(f"pad_{n + 1}", "pad",
             box=(PAD_X[n % 4] - 73, PAD_Y[n // 4] - 73, PAD_X[n % 4] + 73, PAD_Y[n // 4] + 73),
             pad=n, rgb=PAD_RGB + n)
         for n in range(16)]

KNOBS = [
    Knob("selector", (1215, 298, 62), enc=0, push=(1, 1), keycap=", . Enter", look="selector"),
    Knob("input_level", (1400, 204, 28), look="pot"),
    Knob("fx_level", (97, 664, 42), word=0x5A, look="pot", at=15),
] + [Knob(f"knob_{i + 1}", (x, 612, 40), enc=i + 1, keycap=f"F{i + 1}")
     for i, x in enumerate((436, 560, 684, 808, 932, 1056))]

TEXTS = [
    Text(1194, 116, "BACK", 17),
    Text(1268, 98, "UTILITY", 13), Text(1268, 116, "HOME", 17),
    Text(1268, 182, "WAKE UP", 11),
    Text(1400, 161, "INPUT LEVEL", 16),
    Text(1367, 248, "MIN", 12), Text(1437, 248, "MAX", 12),
    Text(1215, 417, "PERFORMANCE", 16), Text(1215, 435, "DJ SAMPLER", 16),
    Text(94, 308, "USB STOP", 16),
    Text(82, 260, "5V ═ 1A", 11),
    Text(170, 577, "FX", 16),
    Text(102, 606, "LEVEL/DEPTH", 16), Text(258, 606, "ON/OFF", 16),
    Text(65, 718, "MIN", 12), Text(138, 718, "MAX", 12),
    Text(236, 781, "PITCH", 15, color=LIME), Text(236, 804, "REPEAT", 15, color=LIME),
    Text(236, 827, "USER1", 15, color=LIME), Text(236, 850, "USER2", 15, color=LIME),
    Text(257, 901, "+", 18), Text(257, 1279, "–", 18),
    Text(257, 964, "1/8", 12), Text(257, 1048, "1/4", 12),
    Text(257, 1132, "1/2", 12), Text(257, 1216, "1/1", 12),
    Text(312, 1049, "HOLD", 16),
    Text(179, 1424, "REC / UNDO", 16),
    Text(179, 1536, "STOP/GATE", 16), Text(179, 1715, "PLAY/PAUSE", 16),
    Text(1313, 559, "BEAT SYNC", 16),
    Text(1313, 675, "TEMPO", 16), Text(1313, 692, "±6/±10/±16/WIDE", 11),
    Text(1180, 1033, "TEMPO", 16), Text(1180, 1051, "RESET", 16),
    Text(1180, 1131, "SET", 14),
    Text(1250, 1090, "0", 14),
    Text(1250, 858, "–", 16), Text(1250, 1324, "+", 16),
    Text(1313, 1357, "TEMPO", 16),
    Text(1313, 1433, "NUDGE", 16),
    Text(1232, 1663, "SCENE JUMP", 14), Text(1394, 1588, "CLEAR SEQ.", 12),
    Text(1394, 1663, "LENGTH", 12),
]
TEXTS += [Text(x, 1733, str(i + 1), 15) for i, x in enumerate((1205, 1277, 1350, 1422))]
TEXTS += [Text(STEP_X[n % 8], STEP_Y[n // 8] - 71, str(n + 1), 15) for n in range(16)]
TEXTS += [Text(PAD_X[n % 4] - 82, PAD_Y[n // 4] - 78, str(n + 1), 14, color=(170, 172, 178))
          for n in range(16)]

# Every button bit of the panel's frame with its id in the app
# (docs/panel-protocol.md). The ones no control above uses are offered as a
# grid of "unknown" keys, for finding out what they are.
BUTTON_IDS = {
    (1, 0): 1, (1, 2): 5, (1, 3): 6, (1, 4): 0x10, (1, 5): 0x11, (1, 6): 0x12, (1, 7): 0x13,
    (2, 0): 8, (2, 1): 0xB, (2, 2): 0xC, (2, 3): 0xD, (2, 4): 0xA, (2, 5): 9, (2, 6): 0xE,
    (2, 7): 0xF,
    (5, 0): 0x2A, (5, 1): 0x2B, (5, 2): 0x2C, (5, 3): 0x2D, (5, 4): 0, (5, 5): 2, (5, 6): 3,
    (5, 7): 4,
    (6, 1): 0x18, (6, 2): 0x19, (6, 3): 0x17, (6, 4): 0x16, (6, 5): 0x14, (6, 6): 0x15,
    (6, 7): 7,
}
BUTTON_IDS.update({(3, b): 0x1A + b for b in range(8)})
BUTTON_IDS.update({(4, b): 0x22 + b for b in range(8)})


def unknown_bits():
    """Button bits no control on the face is bound to, in id order."""
    used = {k.bit for k in KEYS if k.bit}
    return sorted((b for b in BUTTON_IDS if b not in used), key=lambda b: BUTTON_IDS[b])


# Two-level lamps in the app's frame: id -> (byte, shift).
LAMPS = {
    0x00: (0x69, 0), 0x01: (0x6A, 6), 0x02: (0x6B, 0), 0x03: (0x6B, 2), 0x04: (0x69, 2),
    0x05: (0x69, 4), 0x06: (0x69, 6), 0x07: (0x67, 0), 0x08: (0x67, 2), 0x09: (0x67, 4),
    0x0A: (0x67, 6), 0x0B: (0x65, 0), 0x0C: (0x63, 0), 0x0D: (0x63, 2), 0x0E: (0x63, 4),
    0x0F: (0x63, 6), 0x10: (0x64, 0), 0x11: (0x64, 2), 0x12: (0x64, 4), 0x13: (0x64, 6),
    0x14: (0x66, 4), 0x15: (0x66, 2), 0x16: (0x68, 0), 0x17: (0x66, 0), 0x18: (0x65, 2),
    0x19: (0x65, 4), 0x1A: (0x65, 6), 0x1B: (0x6A, 0), 0x1C: (0x6A, 2), 0x1D: (0x68, 6),
    0x1E: (0x6A, 4), 0x3F: (0x61, 0), 0x40: (0x61, 2), 0x41: (0x61, 4), 0x42: (0x61, 6),
    0x43: (0x62, 0), 0x44: (0x62, 2), 0x45: (0x62, 4), 0x46: (0x62, 6), 0x47: (0x68, 4),
    0x48: (0x68, 2),
}


def lamp_level(frame, lamp):
    """How a two-level lamp is lit: 0 off, 1 dim, 2 bright. The frame holds
    0 for off, 3 for dim and 1 for bright (the table at)."""
    byte, shift = LAMPS[lamp]
    return (0, 2, 2, 1)[(frame[byte] >> shift) & 3]


def rgb_lamp(frame, index):
    """(r, g, b) of colour lamp 0-31 as the app sends it."""
    o = 1 + 3 * index
    return frame[o], frame[o + 1], frame[o + 2]
