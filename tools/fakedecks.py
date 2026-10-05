#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Fake CDJs on a Pro DJ Link network, for testing a client of it.

    fakedecks.py [--decks N] [--loaded DECK=SOURCE:SLOT:ID ...] [--titles FILE]
                 [--control FILE]

Runs N decks (numbered 1..N, default 4), each on its own loopback address
127.0.0.<number>, so everything stays on one machine (run it in the same
network namespace as the client: in WSL for the emulator). Each deck

- broadcasts a keep-alive on UDP 50000 every 2 s, to 127.255.255.255;
- broadcasts a CDJ status on UDP 50002 every 200 ms, naming the track it has
  loaded (the player it came from, the slot, the type and the rekordbox ID);
- answers the database server: TCP 12523 gives the port (1051), where the
  greeting, the query context setup, a track metadata request and a render
  menu request are answered with the menu items of the track, whose title is
  the first string of the item of type 4.

Deck D has by default the track with rekordbox ID 100 + D, loaded from itself
(slot 3, USB), titled "Track of deck D". --loaded DECK=SOURCE:SLOT:ID puts
another there: a track of the source player's database. --titles FILE has
lines "SOURCE:SLOT:ID=Title" (UTF-8) for the titles each deck knows.

With --control FILE the decks start off, and are switched on and off by the
file (JSON, {"1": true, "2": false, ...}), looked at twice a second: this is
how the virtual deck's side panel (app/virtual_djs.py) drives them. A deck
that is off sends nothing and closes the connections made to it.

The layouts are those of the public Pro DJ Link analysis (Deep Symmetry's
djl-analysis, Beat Link). Prints what it does to standard error. (Written for
the djs1000-mods project's tests too, which run this one.)
"""
import argparse
import json
import os
import socket
import struct
import sys
import threading
import time

MAGIC = bytes([0x51, 0x73, 0x70, 0x74, 0x31, 0x57, 0x6D, 0x4A, 0x4F, 0x4C])
BROADCAST = "127.255.255.255"
DB_PORT = 1051


def log(text):
    sys.stderr.write("fakedecks: %s\n" % text)
    sys.stderr.flush()


def keepalive(number):
    p = bytearray(0x36)
    p[0:10] = MAGIC
    p[0x0A] = 0x06
    name = ("CDJ-FAKE%d" % number).encode()
    p[0x0C:0x0C + len(name)] = name
    p[0x20], p[0x21] = 0x01, 0x02
    p[0x22:0x24] = struct.pack(">H", 0x36)
    p[0x24] = number
    p[0x25] = 0x01
    p[0x26:0x2C] = bytes([0x02, 0xFA, 0x4E, 0xDE, 0xC0, number])
    p[0x2C:0x30] = socket.inet_aton("127.0.0.%d" % number)
    p[0x30] = 1
    p[0x34] = 0x01
    return bytes(p)


def status(number, source, slot, ttype, rbid):
    p = bytearray(0x124)
    p[0:10] = MAGIC
    p[0x0A] = 0x0A
    name = ("CDJ-FAKE%d" % number).encode()
    p[0x0B:0x0B + len(name)] = name
    p[0x21] = number
    p[0x24] = number
    p[0x28], p[0x29], p[0x2A] = source, slot, ttype
    p[0x2C:0x30] = struct.pack(">I", rbid)
    return bytes(p)


# ---- the database server's fields -----------------------------------------

def num(v, size=4):
    return {1: b"\x0f", 2: b"\x10", 4: b"\x11"}[size] + v.to_bytes(size, "big")


def string(text):
    data = (text + "\0").encode("utf-16-be")
    return b"\x26" + struct.pack(">I", len(data) // 2) + data


def message(txid, mtype, args):
    """args: list of ('n', value) or ('s', text)."""
    tags = bytearray(12)
    body = b""
    for i, (kind, v) in enumerate(args):
        if kind == "n":
            tags[i] = 0x06
            body += num(v)
        else:
            tags[i] = 0x02
            body += string(v)
    return (num(0x872349AE) + num(txid) + num(mtype, 2) + num(len(args), 1)
            + b"\x14" + struct.pack(">I", 12) + bytes(tags) + body)


def read_exact(conn, n):
    data = b""
    while len(data) < n:
        chunk = conn.recv(n - len(data))
        if not chunk:
            raise EOFError
        data += chunk
    return data


def read_field(conn):
    tag = read_exact(conn, 1)[0]
    if tag in (0x0F, 0x10, 0x11):
        size = {0x0F: 1, 0x10: 2, 0x11: 4}[tag]
        return ("n", int.from_bytes(read_exact(conn, size), "big"))
    if tag == 0x14:
        length = struct.unpack(">I", read_exact(conn, 4))[0]
        return ("b", read_exact(conn, length))
    if tag == 0x26:
        length = struct.unpack(">I", read_exact(conn, 4))[0]
        return ("s", read_exact(conn, 2 * length).decode("utf-16-be").rstrip("\0"))
    raise ValueError("field tag %#x" % tag)


def read_message(conn):
    assert read_field(conn) == ("n", 0x872349AE), "no magic"
    txid = read_field(conn)[1]
    mtype = read_field(conn)[1]
    count = read_field(conn)[1]
    read_field(conn)                        # the tags
    args = [read_field(conn) for _ in range(count)]
    return txid, mtype, args


class Deck:
    def __init__(self, number, loaded, titles):
        self.number = number
        self.source, self.slot, self.rbid = loaded
        self.titles = titles                # {(slot, id): title} this deck knows
        self.queries = []
        self.enabled = True

    # -- UDP --
    def announce(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.bind(("127.0.0.%d" % self.number, 0))
        last_status = 0.0
        last_keep = 0.0
        while True:
            now = time.time()
            if not self.enabled:
                last_keep = last_status = 0.0
                time.sleep(0.1)
                continue
            if now - last_keep >= 2.0:
                s.sendto(keepalive(self.number), (BROADCAST, 50000))
                last_keep = now
            if now - last_status >= 0.2:
                s.sendto(status(self.number, self.source, self.slot, 1, self.rbid),
                         (BROADCAST, 50002))
                last_status = now
            time.sleep(0.05)

    # -- TCP --
    def serve_port(self):
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.%d" % self.number, 12523))
        srv.listen(5)
        while True:
            conn, _ = srv.accept()
            if not self.enabled:
                conn.close()
                continue
            try:
                length = struct.unpack(">I", read_exact(conn, 4))[0]
                if read_exact(conn, length) == b"RemoteDBServer\0":
                    conn.sendall(struct.pack(">H", DB_PORT))
                    log("deck %d: told the database port" % self.number)
            except (EOFError, OSError):
                pass
            conn.close()

    def serve_db(self):
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.%d" % self.number, DB_PORT))
        srv.listen(5)
        while True:
            conn, _ = srv.accept()
            if not self.enabled:
                conn.close()
                continue
            threading.Thread(target=self.session, args=(conn,), daemon=True).start()

    def session(self, conn):
        try:
            conn.sendall(read_exact(conn, 5))               # the greeting, echoed
            track = None
            while True:
                txid, mtype, args = read_message(conn)
                if mtype == 0x0000:                         # query context setup
                    conn.sendall(message(txid, 0x4000, [("n", 0), ("n", self.number)]))
                    log("deck %d: query context for device %d" % (self.number, args[0][1]))
                elif mtype == 0x2002:                       # track metadata request
                    dmst, rbid = args[0][1], args[1][1]
                    slot = (dmst >> 8) & 0xFF
                    title = self.titles.get((slot, rbid))
                    log("deck %d: metadata for id %d slot %d from device %d: %s"
                        % (self.number, rbid, slot, dmst >> 24, title))
                    self.queries.append(rbid)
                    track = (rbid, title)
                    count = 11 if title is not None else 0xFFFFFFFF
                    conn.sendall(message(txid, 0x4000, [("n", 0x2002), ("n", count)]))
                elif mtype == 0x3000 and track and track[1] is not None:   # render menu
                    rbid, title = track
                    out = message(txid, 0x4001, [("n", 1), ("n", 0)])
                    kinds = [0x04, 0x07, 0x02, 0x03, 0x0B, 0x0D, 0x0A, 0x23, 0x0F, 0x06, 0x01]
                    for i, kind in enumerate(kinds):
                        text = title if kind == 0x04 else "item %02x" % kind
                        out += message(txid, 0x4101, [
                            ("n", 7), ("n", rbid), ("n", 2 * (len(text) + 1)), ("s", text),
                            ("n", 2), ("s", " "), ("n", kind), ("n", 0), ("n", 0),
                            ("n", 0), ("n", 0), ("n", 0)])
                    out += message(txid, 0x4201, [])
                    conn.sendall(out)
                else:
                    log("deck %d: unexpected message type %#x" % (self.number, mtype))
                    conn.sendall(message(txid, 0x4003, []))
        except (EOFError, OSError, ValueError, AssertionError):
            pass
        conn.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--decks", type=int, default=4)
    ap.add_argument("--loaded", action="append", default=[], metavar="DECK=SOURCE:SLOT:ID")
    ap.add_argument("--titles", metavar="FILE")
    ap.add_argument("--control", metavar="FILE",
                    help="switch the decks on and off from this JSON file, starting off")
    a = ap.parse_args()
    loaded = {d: (d, 3, 100 + d) for d in range(1, a.decks + 1)}
    for item in a.loaded:
        d, rest = item.split("=")
        loaded[int(d)] = tuple(int(x) for x in rest.split(":"))
    known = {d: {(3, 100 + d): "Track of deck %d" % d} for d in range(1, a.decks + 1)}
    if a.titles:
        for line in open(a.titles, encoding="utf-8"):
            line = line.rstrip("\n")
            if "=" in line and ":" in line.split("=")[0]:
                key, title = line.split("=", 1)
                src, slot, rbid = (int(x) for x in key.split(":"))
                known.setdefault(src, {})[(slot, rbid)] = title
    decks = {}
    for d in range(1, a.decks + 1):
        deck = decks[d] = Deck(d, loaded[d], known.get(d, {}))
        deck.enabled = not a.control
        for target in (deck.announce, deck.serve_port, deck.serve_db):
            threading.Thread(target=target, daemon=True).start()
        log("deck %d on 127.0.0.%d: track %d:%d:%d" % ((d, d) + loaded[d]))
    seen = None
    while True:
        if a.control:
            try:
                stamp = os.stat(a.control).st_mtime
                if stamp != seen:
                    wanted = json.load(open(a.control, encoding="utf-8"))
                    for d, deck in decks.items():
                        on = bool(wanted.get(str(d)))
                        if on != deck.enabled:
                            log("deck %d %s" % (d, "on" if on else "off"))
                        deck.enabled = on
                    seen = stamp
            except (OSError, ValueError):
                pass
        time.sleep(0.5)


if __name__ == "__main__":
    main()
