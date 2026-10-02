#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Decrypt a DJS-1000 .UPD into the ISO 9660 image it holds.

The update is a Linux cryptoloop image: AES-256-CBC per 512-byte sector,
IV = sector number as a little-endian 32-bit value padded with zeros ("plain"
IV). The file ends with a 20-byte trailer: b"LIVESAMPLER<ver>\\0" and the
CRC32 of the encrypted body.

The key is not part of this project. It is the unit's own, the text file
/usr/local/pdj/aes256.key in its root filesystem (the passphrase the unit
gives losetup): supply a copy from a unit you own.

Needs only openssl on PATH (one AES-ECB pass; the CBC chaining is done here).

    decrypt_upd.py DJS1000.UPD djs.iso [aes256.key]
    decrypt_upd.py --raw autoexec.bin out.img [aes256.key]

--raw is for a file with no trailer, encrypted the same way: the autoexec.bin
the unit runs from a USB stick (decrypt_autoexec.sh). Without the last argument the key file is $DJS_KEY, else
$DJS_HOME/aes256.key (~/djs/aes256.key), where scripts/setup.sh keeps it.
"""
import os
import struct
import subprocess
import sys
import tempfile
import zlib

SECTOR = 512
TRAILER = 20


def key_file(given=None):
    """The path of the key file: the one given, $DJS_KEY, or the copy
    setup.sh keeps in $DJS_HOME."""
    home = os.environ.get("DJS_HOME") or os.path.expanduser("~/djs")
    path = given or os.environ.get("DJS_KEY") or os.path.join(home, "aes256.key")
    if not os.path.isfile(path):
        sys.exit("no key file at %s: give the unit's aes256.key as the last argument, "
                 "or set DJS_KEY (see the README)" % path)
    return path


def read_key(path):
    """The AES-256 key in a key file. The file is the passphrase the unit
    hands losetup, which takes its first 31 characters and a zero byte."""
    text = open(path, "rb").read().split(b"\n")[0].rstrip(b"\r")
    if len(text) < 31:
        sys.exit("%s does not look like the unit's aes256.key (its first line is too short)" % path)
    return text[:31] + b"\0"


def main():
    args = sys.argv[1:]
    raw = args[:1] == ["--raw"]
    if raw:
        del args[0]
    if len(args) not in (2, 3):
        sys.exit(__doc__)
    src, dst = args[0], args[1]
    key = read_key(key_file(args[2] if len(args) == 3 else None))
    data = open(src, "rb").read()
    if raw:
        body = data
    else:
        body, trailer = data[:-TRAILER], data[-TRAILER:]
        tag = trailer[:-4].rstrip(b"\0").decode("ascii", "replace")
        crc_ok = zlib.crc32(body) & 0xFFFFFFFF in struct.unpack("<I", trailer[-4:]) + struct.unpack(">I", trailer[-4:])
        print("trailer: %s, CRC32 %s" % (tag, "ok" if crc_ok else "MISMATCH"))
    if len(body) % SECTOR:
        sys.exit("body is not a whole number of sectors")

    with tempfile.NamedTemporaryFile(delete=False) as t:
        t.write(body)
    try:
        ecb = subprocess.run(["openssl", "enc", "-d", "-aes-256-ecb", "-nopad", "-K", key.hex(),
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
    if not ok:
        print("(a wrong key gives this: check the key file)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
