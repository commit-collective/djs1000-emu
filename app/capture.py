# SPDX-License-Identifier: GPL-2.0-or-later
"""A recording of the virtual deck: its window as video and the master output as sound, for a demonstration.

The deck gives `Capture` its window after each drawing and the master's sound as it arrives. The video goes to ffmpeg at a
fixed rate (a frame is repeated when the drawing was late, so that the video keeps the real time), the sound to a raw
file beside it. tools/demo.py joins them.

A script that drives the app while this records talks to the deck through files beside the recording:

    FILE.start   written when the first frame is taken: the time (time.time()) it began
    FILE.stop    when this file exists, the deck ends the recording and closes
    FILE.cmd     lines appended to it are run as they come: `hover MOD` (the mod's text under the list), `toggle MOD`,
                 `page mods` (the face's small screen shows the list of mods as a page of the unit) and `page off`,
                 `knob NAME DELTA` (turns a knob of the face, as the mouse wheel does: fx_level, knob_1 to knob_6 ...),
                 `slider POS` (the tempo slider, 0 at the top to 1 at the foot, 0.5 the centre) and `key NAME 1|0` (a key of the face
                 down or up, as the mouse holds it: shift, mute, nudge_plus ...)
"""
import os
import subprocess
import time

import pygame

RATE = 44100


class Capture:
    def __init__(self, path, size, fps=25):
        self.path = path
        self.fps = fps
        w, h = size
        self.proc = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (w, h),
             "-r", str(fps), "-i", "-", "-an", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264",
             "-preset", "ultrafast", "-crf", os.environ.get("DJS_CAPTURE_CRF", "20"), "-pix_fmt", "yuv420p", path],
            stdin=subprocess.PIPE)
        self.audio = open(path + ".f32", "wb")
        self.audio_phones = open(path + ".f32p", "wb")     # the headphones, which carry what the input monitor plays
        self.began = None                # time.perf_counter() of the first frame
        self.next = None
        self.frames = 0
        self._cmd_read = 0
        for suffix in (".start", ".stop", ".cmd"):
            if os.path.exists(path + suffix):
                os.remove(path + suffix)

    def frame(self, surface):
        """Takes the window as it is now: as many frames as the time since the last one asks for."""
        now = time.perf_counter()
        if self.began is None:
            self.began, self.next = now, now
            with open(self.path + ".start", "w") as f:
                f.write(repr(time.time()))
        if self.next > now:
            return                       # not yet time for another frame
        raw = pygame.image.tostring(surface, "RGB")
        while self.next <= now:
            self.proc.stdin.write(raw)
            self.next += 1.0 / self.fps
            self.frames += 1

    def sound(self, data, which=0):
        """The master's frames (stereo float32, which 0) or the headphones' (1), from the moment the first picture was taken."""
        if self.began is not None:
            (self.audio_phones if which else self.audio).write(data)

    def stopped(self):
        return os.path.exists(self.path + ".stop")

    def commands(self):
        """The new lines of FILE.cmd."""
        try:
            with open(self.path + ".cmd", "rb") as f:     # in bytes: a text file written on Windows has two for each line end
                f.seek(self._cmd_read)
                data = f.read()
        except OSError:
            return []
        end = data.rfind(b"\n") + 1
        self._cmd_read += end
        return [line.split(None, 1) for line in data[:end].decode("utf-8").splitlines() if line.strip()]

    def close(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        self.proc.wait()
        self.audio.close()
        self.audio_phones.close()
