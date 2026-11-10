# SPDX-License-Identifier: GPL-2.0-or-later
"""The app's sound on the host's sound devices: a Player plays one of its
outputs, a Recorder feeds its input.

The shim sends the sound as the app writes it (stereo float32, 44.1 kHz) over
the deck's link. feed() takes it from the link's thread and SDL's audio
thread asks for it through _fill(). The two clocks are not the same one, and
the app, being emulated, can fall behind: so playing starts only once some
sound is waiting (--audio-buffer, 250 ms by default), starts over after running
dry, and the oldest sound is dropped if too much piles up. A Player counts the
times it ran dry (the app was late with its sound) and the times SDL's thread
was itself called late (the deck was busy). The status line's hint for the
sound device says them, and the device's name turns orange once either happens.
"""

import array
import os
import socket
import sys
import threading
import time

from pygame._sdl2 import audio as sdl_audio

RATE = 44100
FRAME = 8                                # bytes: two float32
BUFFER_MS = 250                          # sound waiting before playing starts (the cost is that much delay)
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
        self.dropped = 0                 # times too much waited and the oldest was dropped (the app was ahead of the device)
        self.dropped_ms = 0
        self._stats = os.environ.get("DJS_AUDIO_STATS")   # a line on stderr every 10 s: what waits, what came and went
        self._stats_at = time.monotonic()
        self._fed = self._played = 0
        self._pace_state()
        self._dev = sdl_audio.AudioDevice(device, 0, RATE, sdl_audio.AUDIO_F32, 2, block, 0,
                                          self._fill)
        self._dev.pause(0)

    def feed(self, data):
        with self._lock:
            self._buf += data
            self._fed += len(data) // FRAME
            if len(self._buf) > self._most:
                gone = len(self._buf) - self._start
                del self._buf[:gone]
                self.dropped += 1
                self.dropped_ms += gone * 1000 // (RATE * FRAME)
        if self._stats:
            now = time.monotonic()
            if now - self._stats_at >= 10.0:
                span, fed, played = now - self._stats_at, self._fed, self._played
                self._stats_at, self._fed, self._played = now, 0, 0
                print(f"audio: came x{fed / RATE / span:.4f}, played x{played / RATE / span:.4f}, waits {self.waiting_ms()} ms, "
                      f"pace {self.ppm:+d} ppm, slips {self.slip_ppm:+d} ppm ({self.slips}), dry {self.dry}, late {self.late}, "
                      f"dropped {self.dropped} ({self.dropped_ms} ms)",
                      file=sys.stderr, flush=True)

    def reset(self):
        with self._lock:
            self._buf.clear()
            self._playing = False

    # How the deck keeps what waits where it is wanted, by default: by itself, a frame of sound left out or played twice
    # now and then (a few hundredths of a percent, which is not heard), and the app keeps the host's clock. The unit has
    # one clock for its sound and for the link: an app whose sound followed the sound card while the link's beats came
    # on the host's clock had two, and a DJS synced to a CDJ never settled. (--pace instead: pace() below.)
    # How many: from what waits, at its lowest of each second (SDL's late calls only raise it), smoothed, by a slow
    # control that settles in a minute or two without overshooting it. What waits moves by a few frames a second at
    # the clocks' difference, so there is no hurry, and a quick one would slip back and forth with each late call.
    SLIP_LOW = 1.0                       # seconds over which the lowest of what waits is taken
    SLIP_SMOOTH = 10.0                   # seconds over which those lows are smoothed
    SLIP_PPM_PER_MS = 15.0               # ppm for each millisecond more (or less) than wanted waiting
    SLIP_PPM_PER_MS_S = 0.1              # and for each millisecond held a second: no difference is left, slowly
    SLIP_LIMIT = 4000                    # ppm at most in all: a few frames in each of SDL's blocks

    # With --pace, the correction is the app's clock: it must move as little as a crystal does. An app that follows another player's
    # tempo (SYNC) corrects its own for each change of it, and a correction that followed what waits, which comes and goes
    # by a block of SDL's (46 ms) at each call, made a DJS synced to a CDJ swing by 3 BPM. So its main part is the sound
    # card's own rate, measured over a minute (what SDL takes, at that rate, whatever waits), and what waits is kept
    # where it is wanted by a small, slow trim.
    RATE_WINDOW = 60.0                   # seconds of the sound card's pace measured
    TRIM_PPM_PER_MS = 5.0                # the trim for each millisecond more (or less) than wanted waiting, smoothed
    TRIM_LIMIT = 500                     # ppm: at most 0.05 %
    TRIM_SMOOTH = 20.0                   # seconds over which what waits is smoothed for the trim

    def _pace_state(self):
        self._sum = self._count = 0      # what waited, summed at each call of SDL's thread while playing (for pace())
        self._taken = 0                  # frames SDL has taken, all told: the sound card's clock
        self._taken_at = 0.0             # when it last took some: a measure is between two of its calls, not of pace()'s
        self._clock = time.monotonic
        self._marks = []                 # (time, frames taken) at each pace(), over RATE_WINDOW
        self._waits_ms = None            # what waits beyond what is wanted, smoothed (ms)
        self.ppm = 0                     # the last correction
        self.slipping = True             # the deck keeps what waits by slipping frames (off with --pace)
        self._level = None               # what waits, smoothed (bytes), for the slips
        self._slip = 0.0                 # frames owed: + to leave out, - to play twice
        self._low = None                 # the lowest of what waits this second (bytes), and when that second began
        self._low_at = 0.0
        self._slip_i = 0.0               # the slow part of slip_ppm (the clocks' steady difference)
        self.slip_ppm = 0
        self.slips = 0

    def pace(self, dt, now=None):
        """How much longer (ppm, + or -) the app's blocks are to take for its sound to come at the sound card's pace,
        what waits staying at what is wanted: the sound card is the clock, as the DAC is on the unit. Called every dt
        seconds. None while nothing plays."""
        now = self._clock() if now is None else now
        with self._lock:
            n, total, taken, taken_at = self._count, self._sum, self._taken, self._taken_at
            self._sum = self._count = 0
            target = self._start
        if not n:
            return None
        self._marks.append((taken_at, taken))
        while len(self._marks) > 2 and taken_at - self._marks[1][0] >= self.RATE_WINDOW:
            del self._marks[0]
        base = self.ppm
        if len(self._marks) >= 4 and taken_at - self._marks[0][0] >= 2.0:
            # the sound card's rate: the slope of what it took against when, fitted to all the marks, so that one call
            # of SDL's that came late (the deck drawing) moves it little
            ts = [t for t, _ in self._marks]
            fs = [f for _, f in self._marks]
            mt, mf = sum(ts) / len(ts), sum(fs) / len(fs)
            spread = sum((t - mt) ** 2 for t in ts)
            if spread > 0:
                rate = sum((t - mt) * (f - mf) for t, f in zip(ts, fs)) / spread
                if rate > 0:
                    base = (RATE / rate - 1.0) * 1e6
        error_ms = (total / n - target) * 1000.0 / (RATE * FRAME)     # + : too much waits, the app is ahead
        smooth = min(1.0, dt / self.TRIM_SMOOTH)
        self._waits_ms = error_ms if self._waits_ms is None else self._waits_ms + (error_ms - self._waits_ms) * smooth
        trim = max(-self.TRIM_LIMIT, min(self.TRIM_LIMIT, self.TRIM_PPM_PER_MS * self._waits_ms))
        self.ppm = int(max(-200000.0, min(200000.0, base + trim)))
        return self.ppm

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
        now = self._clock()
        if self._last and now - self._last > 2.0 * self._period and self._playing:
            self.late += 1
        self._last = now
        with self._lock:
            if not self._playing and len(self._buf) >= self._start:
                self._playing = True
            if self._playing and self.slipping:
                self._slip_frames(want // FRAME)
            have = min(want, len(self._buf)) if self._playing else 0
            have -= have % FRAME
            if have:
                view[:have] = self._buf[:have]
                del self._buf[:have]
            self._played += want // FRAME
            self._taken += want // FRAME
            self._taken_at = now
            if self._playing:
                self._sum += len(self._buf)
                self._count += 1
            if self._playing and have < want:
                self._playing = False
                self.dry += 1
        if have < want:
            view[have:] = bytes(want - have)

    def _slip_frames(self, frames):
        """Leaves a frame out, or plays one twice, as often as keeps what waits where it is wanted (with the lock)."""
        now = self._clock()
        level = len(self._buf)
        self._low = level if self._low is None else min(self._low, level)
        if now - self._low_at >= self.SLIP_LOW:
            span, self._low_at = (now - self._low_at if self._low_at else self.SLIP_LOW), now
            smooth = min(1.0, span / self.SLIP_SMOOTH)
            self._level = self._low if self._level is None else self._level + (self._low - self._level) * smooth
            self._low = None
            error_ms = (self._level - self._start) * 1000.0 / (RATE * FRAME)
            self._slip_i = max(-self.SLIP_LIMIT, min(self.SLIP_LIMIT, self._slip_i + self.SLIP_PPM_PER_MS_S * error_ms * span))
            self.slip_ppm = int(max(-self.SLIP_LIMIT, min(self.SLIP_LIMIT, self._slip_i + self.SLIP_PPM_PER_MS * error_ms)))
        self._slip = max(-8.0, min(8.0, self._slip + self.slip_ppm * frames / 1e6))
        while self._slip >= 1 and len(self._buf) > (frames + 1) * FRAME:      # too much waits: one frame left out
            del self._buf[:FRAME]
            self._slip -= 1
            self.slips += 1
        while self._slip <= -1 and len(self._buf) >= FRAME:                   # too little: one played twice
            self._buf[:0] = self._buf[:FRAME]
            self._slip += 1
            self.slips += 1

    def close(self):
        """Nothing is asked of SDL here: pausing or closing a device waits
        for its callback, the callback waits for the interpreter, and this
        thread holds it. The device goes when the program does
        (virtual_djs.py leaves with os._exit)."""
        self.closed = True
