# SPDX-License-Identifier: GPL-2.0-or-later
"""The link to the running app: the djsdev shim's TCP port (shim/djsdev.c,
"The virtual deck's link").

Out: the shim's command lines (bit, enc, pad, touch ...). In, each with an
8-byte header: 'S' rows of the screen that changed, 'L' the 128-byte frame
the app sends its panel, which holds the lamps, 'A' an output's sound.
Toolkit-free. The window polls take() for what has arrived, and the sound
goes straight to the `audio` callable as (output, data), output 0 the master
and 1 the headphones, from this module's thread. send_input() sends the
input's sound the other way.
"""

import socket
import struct
import threading
import time


class Link:
    def __init__(self, host="127.0.0.1", port=7310, audio=None):
        self.addr = (host, port)
        self.audio = audio
        self.connected = False
        self._sock = None
        self._lock = threading.Lock()
        self._out = threading.Lock()     # one sender at a time: lines and sound
        self._in = []
        self._stop = False
        threading.Thread(target=self._run, daemon=True).start()

    audio_pos = [0, 0]          # of the last sound message, per output

    def send(self, line):
        """One command line. Dropped while the app is not there."""
        sock = self._sock
        if sock is None:
            return
        try:
            with self._out:
                sock.sendall(line.encode() + b"\n")
        except OSError:
            pass

    def send_input(self, data):
        """Sound for the app's input: stereo 16-bit frames at 44.1 kHz."""
        sock = self._sock
        if sock is None or len(data) < 4:
            return
        data = data[:len(data) - len(data) % 4]
        try:
            with self._out:
                sock.sendall(b"in %d\n" % (len(data) // 4) + data)
        except OSError:
            pass

    def take(self):
        """What has arrived since the last call: ("screen", y, rows, width,
        bgrx bytes), ("lamps", frame bytes), ("up",) and ("down",)."""
        with self._lock:
            got, self._in = self._in, []
        return got

    def close(self):
        self._stop = True
        sock = self._sock
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _put(self, item):
        with self._lock:
            self._in.append(item)

    @staticmethod
    def _read(sock, n):
        buf = bytearray()
        while len(buf) < n:
            part = sock.recv(min(n - len(buf), 1 << 20))
            if not part:
                raise ConnectionError("closed")
            buf += part
        return bytes(buf)

    def _run(self):
        while not self._stop:
            try:
                sock = socket.create_connection(self.addr, timeout=2)
            except OSError:
                time.sleep(1)
                continue
            sock.settimeout(None)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._sock, self.connected = sock, True
            self._put(("up",))
            try:
                while True:
                    kind, which, y, rows, width = struct.unpack("<BBHHH", self._read(sock, 8))
                    if kind == ord("S"):
                        self._put(("screen", y, rows, width, self._read(sock, rows * width * 4)))
                    elif kind == ord("L"):
                        self._put(("lamps", self._read(sock, 128)))
                    elif kind == ord("A"):
                        data = self._read(sock, y * 8)
                        # Where the frames are in the output: frames written to
                        # it since the start (low 32 bits), the same moment on
                        # both outputs for the same position.
                        self.audio_pos[which & 1] = rows | width << 16
                        if self.audio:
                            self.audio(which, data)
                    else:
                        raise ConnectionError("unknown message")
            except (OSError, ConnectionError, struct.error):
                pass
            self._sock, self.connected = None, False
            self._put(("down",))
            try:
                sock.close()
            except OSError:
                pass
            time.sleep(0.5)
