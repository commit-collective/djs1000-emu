#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Writes a small kit of synthetic drum samples to try the app with.

    make_test_kit.py [folder]

The folder defaults to "PIONEER DJ SAMPLER/Samples/Test Kit" on the
emulator's USB drive ($DJS_USB, or $DJS_HOME/usb, or ~/djs/usb), where the
app's BROWSE finds it under Samples [USB]. Standard library only. The
samples are 44.1 kHz, 16-bit, stereo, and always come out the same.
"""
import math
import os
import random
import struct
import sys
import wave

RATE = 44100
FADE = 0.03          # seconds: every sample ends on silence, not on a step


def save(folder, name, fn, seconds):
    n = int(RATE * seconds)
    fade = int(RATE * FADE)
    out = bytearray()
    for i in range(n):
        v = max(-1.0, min(1.0, fn(i / RATE))) * 0.9
        if n - i <= fade:
            v *= (n - i - 1) / fade
        s = int(v * 32767)
        out += struct.pack("<hh", s, s)
    with wave.open(os.path.join(folder, name), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(out))


def main():
    usb = os.environ.get("DJS_USB") or os.path.join(
        os.environ.get("DJS_HOME") or os.path.expanduser("~/djs"), "usb")
    folder = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        usb, "PIONEER DJ SAMPLER", "Samples", "Test Kit")
    os.makedirs(folder, exist_ok=True)
    rng = random.Random(1)
    phase = [0.0]
    last = [0.0]

    def kick(t):                # a sine falling from 165 Hz to 45 Hz
        phase[0] += 2 * math.pi * (45 + 120 * math.exp(-t * 28)) / RATE
        return math.sin(phase[0]) * math.exp(-t * 7)

    def snare(t):               # noise over a short 190 Hz body
        return (rng.uniform(-1, 1) * 0.7 * math.exp(-t * 18)
                + math.sin(2 * math.pi * 190 * t) * 0.5 * math.exp(-t * 25))

    def hat(t):                 # noise with the low end taken out
        x = rng.uniform(-1, 1)
        y, last[0] = x - last[0], x
        return y * 0.6 * math.exp(-t * 60)

    def clap(t):                # three short bursts, then a tail
        env = sum(math.exp(-(t - o) * 90) for o in (0, 0.012, 0.024) if t >= o)
        if t >= 0.036:
            env += math.exp(-(t - 0.036) * 22)
        return rng.uniform(-1, 1) * 0.45 * env

    def tone(t):                # a plain 220 Hz note
        return math.sin(2 * math.pi * 220 * t) * 0.6 * math.exp(-t * 3)

    for name, fn, seconds in (("Kick.wav", kick, 0.6), ("Snare.wav", snare, 0.35),
                              ("Hat.wav", hat, 0.12), ("Clap.wav", clap, 0.4),
                              ("Tone.wav", tone, 1.0)):
        save(folder, name, fn, seconds)
    print(folder)


if __name__ == "__main__":
    main()
