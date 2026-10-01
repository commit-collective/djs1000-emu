#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Take a screenshot of the running DJS-1000 app.

Asks the djsdev shim for its copy of the screen (the "shot" command on
~/djs/root/tmp/djspanel), waits for ~/djs/root/tmp/djsshot.raw, and writes it
as a PNG. Standard library only.

    shot.py out.png [command ...]

Any commands given are sent to the panel pipe first, each followed by a
short wait: e.g.  shot.py a.png "tap 1 0"
"""
import os
import struct
import sys
import time
import zlib

TMP = os.path.join(os.environ.get("DJS_HOME") or os.path.expanduser("~/djs"), "root", "tmp")
PIPE, RAW = TMP + "/djspanel", TMP + "/djsshot.raw"


def send(cmd):
    with open(PIPE, "w") as f:
        f.write(cmd + "\n")


def png(path, w, h, bgrx):
    rows = bytearray()
    for y in range(h):
        row = bgrx[y * w * 4:(y + 1) * w * 4]
        rgb = bytearray(w * 3)
        rgb[0::3], rgb[1::3], rgb[2::3] = row[2::4], row[1::4], row[0::4]
        rows += b"\0" + rgb

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(bytes(rows), 6)) + chunk(b"IEND", b""))


def main():
    out = sys.argv[1]
    for cmd in sys.argv[2:]:
        send(cmd)
        time.sleep(1.0)
    if os.path.exists(RAW):
        os.remove(RAW)
    send("shot")
    for _ in range(100):
        if os.path.exists(RAW):
            break
        time.sleep(0.1)
    else:
        sys.exit("no screenshot: is the app running?")
    d = open(RAW, "rb").read()
    if d[:4] != b"DJS1":
        sys.exit("bad screenshot file")
    w, h = struct.unpack_from("<II", d, 4)
    if not w or not h:
        sys.exit("the app has not drawn anything yet")
    png(out, w, h, d[12:])
    print("%s: %dx%d" % (out, w, h))


if __name__ == "__main__":
    main()
