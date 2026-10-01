# SPDX-License-Identifier: GPL-2.0-or-later
"""Plays the app's master output on one of the host's sound devices.

The shim sends the sound as the app writes it (stereo float32, 44.1 kHz) over
the deck's link; feed() takes it from the link's thread and SDL's audio
thread asks for it through _fill(). The two clocks are not the same one, and
the app, being emulated, can fall behind: so playing starts only once a
little sound is waiting, starts over after running dry, and the oldest sound
is dropped if too much piles up.
"""

import threading

from pygame._sdl2 import audio as sdl_audio

RATE = 44100
FRAME = 8                                # bytes: two float32
START = RATE * FRAME * 60 // 1000        # sound waiting before playing starts: 60 ms
MOST = RATE * FRAME * 250 // 1000        # more than this waiting: drop the oldest


def devices():
    """The names of the host's playback devices."""
    return list(sdl_audio.get_audio_device_names(False))


def pick(name):
    """The device whose name contains `name` (any case), or None for the
    system's default."""
    if not name:
        return None
    for dev in devices():
        if name.lower() in dev.lower():
            return dev
    raise SystemExit(f"no playback device matches {name!r}; --list-audio names them")


class Player:
    def __init__(self, device=None):
        self.name = device or "default device"
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._playing = False
        self.dry = 0                     # times the sound ran out while playing
        self._dev = sdl_audio.AudioDevice(device, 0, RATE, sdl_audio.AUDIO_F32, 2, 512, 0,
                                          self._fill)
        self._dev.pause(0)

    def feed(self, data):
        with self._lock:
            self._buf += data
            if len(self._buf) > MOST:
                del self._buf[:len(self._buf) - START]

    def reset(self):
        with self._lock:
            self._buf.clear()
            self._playing = False

    def _fill(self, dev, view):
        view = memoryview(view).cast("B")   # SDL's buffer, to be filled
        want = len(view)
        with self._lock:
            if not self._playing and len(self._buf) >= START:
                self._playing = True
            have = min(want, len(self._buf)) if self._playing else 0
            have -= have % FRAME
            if have:
                view[:have] = self._buf[:have]
                del self._buf[:have]
            if self._playing and have < want:
                self._playing = False
                self.dry += 1
        if have < want:
            view[have:] = bytes(want - have)

    def close(self):
        self._dev.pause(1)
        self._dev.close()
