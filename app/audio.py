# SPDX-License-Identifier: GPL-2.0-or-later
"""The app's sound on the host's sound devices: a Player plays one of its
outputs, a Recorder feeds its input.

The shim sends the sound as the app writes it (stereo float32, 44.1 kHz) over
the deck's link. feed() takes it from the link's thread and SDL's audio
thread asks for it through _fill(). The two clocks are not the same one, and
the app, being emulated, can fall behind: so playing starts only once some
sound is waiting (--audio-buffer, 150 ms by default), starts over after running
dry, and the oldest sound is dropped if too much piles up. A Player counts the
times it ran dry (the app was late with its sound) and the times SDL's thread
was itself called late (the deck was busy), which the status line shows.
"""

import array
import socket
import threading
import time

from pygame._sdl2 import audio as sdl_audio

RATE = 44100
FRAME = 8                                # bytes: two float32
BUFFER_MS = 150                          # sound waiting before playing starts (the cost is that much delay)
PERIOD = 2048                            # frames SDL asks for at a time (46 ms). Small ones (11 ms) are missed when the deck draws; --audio-block


def devices(capture=False):
    """The names of the host's playback devices, or of its recording ones."""
    return list(sdl_audio.get_audio_device_names(capture))


def pick(name, capture=False):
    """The device whose name contains `name` (any case), or None for the
    system's default."""
    if not name:
        return None
    for dev in devices(capture):
        if name.lower() in dev.lower():
            return dev
    kind = "recording" if capture else "playback"
    raise SystemExit(f"no {kind} device matches {name!r}; --list-audio names them")


class Recorder:
    """Takes sound from a recording device and hands it to `sink` as stereo
    16-bit frames, from SDL's audio thread."""

    def __init__(self, sink, device=None):
        self.name = device or "default input"
        self.gain = 1.0                  # 0 to 1: the deck's INPUT LEVEL
        self.closed = False
        self._sink = sink
        self._dev = sdl_audio.AudioDevice(device, 1, RATE, sdl_audio.AUDIO_S16, 2, 512, 0,
                                          self._take)
        self._dev.pause(0)

    def _take(self, dev, view):
        if self.closed:
            return
        data = bytes(memoryview(view).cast("B"))
        gain = self.gain
        if gain <= 0:
            data = bytes(len(data))
        elif gain < 1:
            samples = array.array("h", data[:len(data) - len(data) % 2])
            data = array.array("h", [int(v * gain) for v in samples]).tobytes()
        self._sink(data)

    def close(self):
        """Nothing is asked of SDL here: pausing or closing a device waits
        for its callback, the callback waits for the interpreter, and this
        thread holds it. The device goes when the program does
        (virtual_djs.py leaves with os._exit)."""
        self.closed = True


class StreamRecorder:
    """The same as a Recorder, with its sound from a TCP stream of raw stereo 16-bit samples at 44.1 kHz instead of a
    recording device: deckbench's `--audio-port`, which is a drum loop in time with its decks. It connects again when the
    stream goes away, and the deck's INPUT LEVEL works as it does for a device."""

    def __init__(self, sink, host, port):
        self.name = "tcp %s:%d" % (host, port)
        self.gain = 1.0
        self.closed = False
        self._sink = sink
        self._address = (host, port)
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while not self.closed:
            try:
                with socket.create_connection(self._address, timeout=3) as sock:
                    sock.settimeout(5)
                    pending = b""
                    while not self.closed:
                        data = sock.recv(8820)
                        if not data:
                            break
                        pending += data
                        usable = len(pending) - len(pending) % 4
                        if usable:
                            self._take(pending[:usable])
                            pending = pending[usable:]
            except OSError:
                pass
            time.sleep(1.0)

    def _take(self, data):
        gain = self.gain
        if gain <= 0:
            data = bytes(len(data))
        elif gain < 1:
            samples = array.array("h", data)
            data = array.array("h", [int(v * gain) for v in samples]).tobytes()
        self._sink(data)

    def close(self):
        self.closed = True


class Silent:
    """A main device that plays nothing: the deck shows its MASTER / PHONES switch as it does for a real one (--mute, for a recording)."""

    def __init__(self):
        self.name = "no sound card (recording)"
        self.closed = False

    def feed(self, data):
        pass

    def reset(self):
        pass

    def close(self):
        self.closed = True


class Player:
    def __init__(self, device=None, buffer_ms=BUFFER_MS, block=PERIOD):
        self.name = device or "default device"
        self.closed = False
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._playing = False
        self._start = RATE * FRAME * max(20, buffer_ms) // 1000      # waiting before playing starts
        self._most = self._start * 3 + RATE * FRAME * 100 // 1000    # more than this waiting: drop the oldest
        self._last = 0.0
        self._period = block / RATE
        self.dry = 0                     # times the sound ran out while playing (the app was late)
        self.late = 0                    # times SDL's thread was called more than twice its period late (the deck was busy)
        self._dev = sdl_audio.AudioDevice(device, 0, RATE, sdl_audio.AUDIO_F32, 2, block, 0,
                                          self._fill)
        self._dev.pause(0)

    def feed(self, data):
        with self._lock:
            self._buf += data
            if len(self._buf) > self._most:
                del self._buf[:len(self._buf) - self._start]

    def reset(self):
        with self._lock:
            self._buf.clear()
            self._playing = False

    def waiting_ms(self):
        """Sound waiting to be played, in milliseconds."""
        return len(self._buf) * 1000 // (RATE * FRAME)

    @property
    def wait_ms(self):
        """How much sound waits before playing starts (--audio-buffer)."""
        return self._start * 1000 // (RATE * FRAME)

    def set_wait(self, ms):
        """Changes it while playing: more is steadier and later."""
        ms = max(20, min(2000, int(ms)))
        with self._lock:
            self._start = RATE * FRAME * ms // 1000
            self._most = self._start * 3 + RATE * FRAME * 100 // 1000

    def _fill(self, dev, view):
        view = memoryview(view).cast("B")   # SDL's buffer, to be filled
        want = len(view)
        now = time.monotonic()
        if self._last and now - self._last > 2.0 * self._period and self._playing:
            self.late += 1
        self._last = now
        with self._lock:
            if not self._playing and len(self._buf) >= self._start:
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
        """Nothing is asked of SDL here: pausing or closing a device waits
        for its callback, the callback waits for the interpreter, and this
        thread holds it. The device goes when the program does
        (virtual_djs.py leaves with os._exit)."""
        self.closed = True
