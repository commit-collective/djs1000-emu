# SPDX-License-Identifier: GPL-2.0-or-later
"""A scripted session with the running app: send it what the panel would,
and take its screen, lamps and sound.

    from session import Session
    s = Session()                      # connects to the shim's deck link
    s.wait_screen()                    # the app has drawn and gone quiet
    s.press((5, 5))                    # PROJECT
    s.touch(170, 285)
    s.shot("home.png")
    sound = s.record(1.0, lambda: s.pad(0))   # floats, the master's left and right

It is a client like the virtual deck (app/link.py), and works beside one.
Standard library only, but shot() needs Pillow.
"""
import os
import struct
import sys
import threading
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "app"))

from link import Link  # noqa: E402

W, H = 800, 480                          # the app's screen
ORIGIN = 1                               # where it draws it in its window
RATE = 44100


class Session:
    def __init__(self, host="127.0.0.1", port=7310, connect=30):
        self._lock = threading.Lock()
        self._sound = [[], []]           # master, headphones: interleaved floats
        self.screen = bytearray(W * H * 4)
        self.lamps = bytes(128)
        self.changed = 0.0               # when the screen last changed
        self.drawn = False
        self.link = Link(host, port, audio=self._audio)
        end = time.time() + connect
        while not self.link.connected:
            if time.time() > end:
                raise RuntimeError(f"no emulator on {host}:{port}")
            time.sleep(0.1)

    def close(self):
        self.link.close()

    # ---- what arrives ----------------------------------------------------

    def _audio(self, which, data):
        with self._lock:
            self._sound[which].append(data)

    def pump(self, seconds=0.0):
        """Takes in what has arrived, for `seconds`."""
        end = time.time() + seconds
        while True:
            for item in self.link.take():
                if item[0] == "screen":
                    _, y, rows, width, data = item
                    for r in range(rows):
                        yy = y + r - ORIGIN
                        if 0 <= yy < H:
                            src = (r * width + ORIGIN) * 4
                            n = min(width - ORIGIN, W) * 4
                            row = data[src:src + n]
                            at = yy * W * 4
                            if self.screen[at:at + n] != row:
                                self.screen[at:at + n] = row
                                self.changed = time.time()
                    self.drawn = True
                elif item[0] == "lamps":
                    self.lamps = item[1]
            if time.time() >= end:
                return
            time.sleep(0.02)

    def wait_screen(self, quiet=0.7, timeout=90):
        """Waits until the app has drawn and its screen has held still for
        `quiet` seconds. Returns False if it never did."""
        end = time.time() + timeout
        while time.time() < end:
            self.pump(0.05)
            if self.drawn and time.time() - self.changed >= quiet:
                return True
        return False

    def settle(self, quiet=0.7, timeout=10):
        """After an input: gives the app a moment, then waits for the screen
        to hold still."""
        self.pump(0.3)
        return self.wait_screen(quiet, timeout)

    # ---- what the panel would send --------------------------------------

    def send(self, line):
        self.link.send(line)

    def press(self, bit, hold=0.15):
        """A button, by its (byte, bit) in the panel's frame."""
        self.send(f"bit {bit[0]} {bit[1]} 1")
        self.pump(hold)
        self.send(f"bit {bit[0]} {bit[1]} 0")
        self.settle()

    def tap(self, bit, hold=0.1):
        """A button, without waiting for the screen afterwards."""
        self.send(f"bit {bit[0]} {bit[1]} 1")
        self.pump(hold)
        self.send(f"bit {bit[0]} {bit[1]} 0")

    def turn(self, steps, enc=0):
        self.send(f"enc {enc} {steps}")
        self.settle(0.4)

    def push(self):
        """The rotary selector's push."""
        self.press((1, 1))

    def touch(self, x, y):
        """A tap on the screen, at screen coordinates."""
        self.send(f"touch 1 {x + ORIGIN} {y + ORIGIN}")
        self.pump(0.2)
        self.send(f"touch 0 {x + ORIGIN} {y + ORIGIN}")
        self.settle()

    def pad(self, n, level=800, hold=0.15):
        """Hits pad n (0-15)."""
        self.send(f"pad {n} {level} {level}")
        self.pump(hold)
        self.send(f"pad {n} 0 0")

    # ---- taking things ---------------------------------------------------

    def record(self, seconds, action=None, which=0):
        """The sound of output `which` for `seconds` from now, as a list of
        floats (left, right, left ...); `action` is run once it has begun."""
        self.pump(0.05)
        with self._lock:
            self._sound[which] = []
        start = time.time()
        if action:
            action()
        self.pump(max(0.0, seconds - (time.time() - start)))
        with self._lock:
            data = b"".join(self._sound[which])
        return list(struct.unpack("<%df" % (len(data) // 4), data))

    def pixels(self):
        """The screen as RGB bytes, W x H."""
        s = self.screen
        out = bytearray(W * H * 3)
        out[0::3], out[1::3], out[2::3] = s[2::4], s[1::4], s[0::4]
        return bytes(out)

    def shot(self, path):
        from PIL import Image
        Image.frombytes("RGB", (W, H), self.pixels()).save(path)


def save_wav(path, floats):
    """Stereo floats to a 16-bit WAV."""
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(struct.pack("<%dh" % len(floats),
                                  *(max(-32768, min(32767, int(v * 32767))) for v in floats)))
