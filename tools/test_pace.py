#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""The deck's correction of the app's clock (Player.pace, "pace <ppm>" in the shim), in a simulation with no sound
device: a sound card that takes SDL's blocks at its own rate, an app that gives its sound at the rate the correction
sets. The correction must settle on the difference of the two clocks and then hold still, as a crystal does, while
what waits stays near what is wanted. A DJS synced to a CDJ follows each move of its clock: one that moved with what
waits (a block of 46 ms more or less at each call) made it swing by 3 BPM.

    python tools/test_pace.py       (needs pygame-ce, as the deck does)
"""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import audio  # noqa: E402


def player(buffer_ms=audio.BUFFER_MS):
    """A Player without its SDL device: what pace() and the sound card's calls need."""
    p = audio.Player.__new__(audio.Player)
    p.closed = False
    p._buf = bytearray()
    p._lock = threading.Lock()
    p._playing = False
    p._start = audio.RATE * audio.FRAME * buffer_ms // 1000
    p._most = p._start * 3 + audio.RATE * audio.FRAME * 100 // 1000
    p._last = 0.0
    p._period = audio.PERIOD / audio.RATE
    p.dry = p.late = p.dropped = p.dropped_ms = 0
    p._stats = None
    p._fed = p._played = 0
    p._pace_state()
    return p


def run(card_speed, seconds, app_block=512, dt=0.5, jitter=False):
    """The sound card runs `card_speed` times the host's clock. Gives the corrections and what waited, each dt. With
    `jitter`, SDL's calls come up to 30 ms late, and one in twenty 120 ms late (the deck busy drawing)."""
    import random
    rng = random.Random(1)
    p, now, card_due, app_due, pace_due = player(), 0.0, 0.0, 0.0, dt
    late_by = 0.0
    clock = [0.0]
    p._clock = lambda: clock[0]
    ppm, history = 0, []
    view = bytearray(audio.PERIOD * audio.FRAME)
    step = 1.0 / audio.RATE * 64
    while now < seconds:
        if app_due <= now:                      # the app writes a block, at the pace the correction sets
            p.feed(bytes(app_block * audio.FRAME))
            app_due += app_block / audio.RATE * (1 + ppm / 1e6)
        if card_due + late_by <= now:           # SDL takes a block at the sound card's rate, its call late or not
            p._fill(None, view)
            card_due += audio.PERIOD / (audio.RATE * card_speed)
            late_by = (0.12 if rng.random() < 0.05 else rng.uniform(0, 0.03)) if jitter else 0.0
        if pace_due <= now:
            got = p.pace(dt, now)
            if got is not None:
                ppm = got
                history.append((now, ppm, p.waiting_ms()))
            pace_due += dt
        now += step
        clock[0] = now
    return p, history


class Pace(unittest.TestCase):
    def test_the_clock_settles_on_the_sound_cards_and_holds_still(self):
        for speed in (1.07, 1.0, 0.98):
            with self.subTest(card=speed):
                p, history = run(speed, 180, jitter=True)
                truth = (1 / speed - 1) * 1e6
                late = [ppm for t, ppm, _ in history if t >= 90]
                self.assertLess(abs(sum(late) / len(late) - truth), 1500, (speed, late[:5]))
                # 600 ppm is 0.08 BPM at 126, under the real unit's own swing (0.1 BPM synced to a CDJ)
                self.assertLess(max(late) - min(late), 600, "the app's clock still moves: %s" % late[-10:])
                waits = [w for t, _, w in history if t >= 90]       # a late call of SDL's makes it jump: its mean
                self.assertLess(abs(sum(waits) / len(waits) - audio.BUFFER_MS), 100, waits[-10:])
                self.assertEqual((p.dry, p.dropped), (0, 0))

    def test_the_old_correction_swung_by_3_bpm(self):
        """What the DJS showed synced to a CDJ: a correction that follows what waits moves the app's clock 2 %."""
        def old(self, dt, now=None):
            with self._lock:
                n, total = self._count, self._sum
                self._sum = self._count = 0
            if not n:
                return None
            error_ms = (total / n - self._start) * 1000.0 / (audio.RATE * audio.FRAME)
            self._integral = max(-150000.0, min(150000.0, getattr(self, "_integral", 0.0) + 100.0 * error_ms * dt))
            self.ppm = int(max(-200000.0, min(200000.0, self._integral + 300.0 * error_ms)))
            return self.ppm
        saved = audio.Player.pace
        audio.Player.pace = old
        try:
            _, history = run(1.0, 180, jitter=True)
        finally:
            audio.Player.pace = saved
        late = [ppm for t, ppm, _ in history if t >= 90]
        self.assertGreater(max(late) - min(late), 15000)            # 2 BPM at 126: what the new one is not

    def test_nothing_playing_asks_nothing(self):
        self.assertIsNone(player().pace(0.5, 1.0))


if __name__ == "__main__":
    unittest.main()
