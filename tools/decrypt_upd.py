#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Decrypt a DJS-1000 .UPD into the ISO 9660 image it holds.

The update is a Linux cryptoloop image (key and cipher from earlier
notes): AES-256-CBC per 512-byte sector, IV = sector number as a
little-endian 32-bit value padded with zeros ("plain" IV). The file ends with
a 20-byte trailer: b"LIVESAMPLER<ver>\\0" and the CRC32 of the encrypted body.

Needs only openssl on PATH (one AES-ECB pass; the CBC chaining is done here).

    decrypt_upd.py DJS1000.UPD djs.iso
"""
import os
import struct
import subprocess
import sys
import tempfile
import zlib

KEY = b"(removed: supply the unit's aes256.key)\0"
SECTOR = 512
TRAILER = 20


def main():
    src, dst = sys.argv[1], sys.argv[2]
    data = open(src, "rb").read()
    body, trailer = data[:-TRAILER], data[-TRAILER:]
    tag = trailer[:-4].rstrip(b"\0").decode("ascii", "replace")
    crc_ok = zlib.crc32(body) & 0xFFFFFFFF in struct.unpack("<I", trailer[-4:]) + struct.unpack(">I", trailer[-4:])
    print("trailer: %s, CRC32 %s" % (tag, "ok" if crc_ok else "MISMATCH"))
    if len(body) % SECTOR:
        sys.exit("body is not a whole number of sectors")

    with tempfile.NamedTemporaryFile(delete=False) as t:
        t.write(body)
    try:
        ecb = subprocess.run(["openssl", "enc", "-d", "-aes-256-ecb", "-nopad", "-K", KEY.hex(),
                              "-in", t.name], check=True, capture_output=True).stdout
    finally:
        os.unlink(t.name)

    out = bytearray(len(body))
    for s in range(len(body) // SECTOR):
        o = s * SECTOR
        prev = struct.pack("<I", s & 0xFFFFFFFF) + bytes(12) + body[o:o + SECTOR - 16]
        x = int.from_bytes(ecb[o:o + SECTOR], "little") ^ int.from_bytes(prev, "little")
        out[o:o + SECTOR] = x.to_bytes(SECTOR, "little")
    open(dst, "wb").write(out)
    ok = out[0x8001:0x8006] == b"CD001"
    print("wrote %s (%d bytes), ISO 9660 signature %s" % (dst, len(out), "found" if ok else "NOT FOUND"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
