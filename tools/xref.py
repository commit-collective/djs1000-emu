#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Find where a string is used in EP113_Main_R and show the code before it.

    xref.py <binary> "<string>" [instructions-before=30]

For each literal-pool word holding the string's address, prints the ARM
instructions leading up to the load, and the branches that jump to it.
Needs arm-linux-gnueabihf-objdump.
"""
import re
import struct
import subprocess
import sys


def main():
    path, text = sys.argv[1], sys.argv[2].encode()
    before = int(sys.argv[3]) if len(sys.argv) > 3 else 30
    d = open(path, "rb").read()
    phoff, phnum = struct.unpack_from("<I", d, 0x1C)[0], struct.unpack_from("<H", d, 0x2C)[0]
    segs = [struct.unpack_from("<IIIIIIII", d, phoff + i * 32) for i in range(phnum)]

    def va(o):
        for t, off, v, _, fs, _, _, _ in segs:
            if t == 1 and off <= o < off + fs:
                return v + o - off

    s = d.find(text)
    if s < 0:
        sys.exit("string not found")
    sv = va(s)
    pools = [va(i) for i in range(0, len(d) - 3, 4) if struct.unpack_from("<I", d, i)[0] == sv]
    print("string at %#x, %d literal-pool reference(s)" % (sv, len(pools)))
    for p in pools:
        out = subprocess.run(["arm-linux-gnueabihf-objdump", "-d", "--start-address=%#x" % (p - 0x1000),
                              "--stop-address=%#x" % (p + 4), path], capture_output=True, text=True).stdout
        lines = [l for l in out.splitlines() if ":\t" in l]
        loads = [i for i, l in enumerate(lines) if ("@ %x " % p) in l]
        for i in loads:
            at = lines[i].split(":")[0].strip()
            print("\n== load at %s" % at)
            print("\n".join(l[:90] for l in lines[max(0, i - before):i + 2]))
            for j, l in enumerate(lines):
                if re.search(r"\sb\w*\s+%s <" % at, l):
                    print("-- branch from %s" % l.split(":")[0].strip())
                    print("\n".join(x[:90] for x in lines[max(0, j - before):j + 1]))


if __name__ == "__main__":
    main()
