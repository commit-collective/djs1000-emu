#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Fake CDJs on a Pro DJ Link network, for testing a client of it.

    fakedecks.py [--decks N | --numbers N,N,...] [--loaded DECK=SOURCE:SLOT:ID ...]
                 [--titles FILE] [--control FILE]

Runs decks (numbered 1..N, default 4, or the --numbers), each on its own
loopback address 127.0.0.<number>, so everything stays on one machine (run it
in the same network namespace as the client: in WSL for the emulator). Each
deck

- broadcasts a keep-alive on UDP 50000 every 2 s, to 127.255.255.255;
- broadcasts a CDJ status on UDP 50002 every 200 ms: the track it has loaded
  (the player it came from, the slot, the type and the rekordbox ID), whether
  it plays, is synced, is the tempo master, its tempo, and while it hands the
  master role over to another player, which one;
- while it plays, broadcasts a beat packet on UDP 50001 at each beat of its
  tempo (its own, or the master's when it is synced);
- answers the database server: TCP 12523 gives the port (1051), where the
  greeting, the query context setup, a track metadata request and a render
  menu request are answered with the menu items of the track, whose title is
  the first string of the item of type 4;
- takes the tempo master role from a player that asks (a master hand-off
  request, UDP 50001), answering that it yields, and obeys the sync commands
  (sync on/off, become master) sent to it.

Deck D has by default the track with rekordbox ID 100 + D, loaded from itself
(slot 3, USB), titled "Track of deck D", at 128 BPM less 2 for each deck after
the first. --loaded DECK=SOURCE:SLOT:ID puts another there: a track of the
source player's database. --titles FILE has lines "SOURCE:SLOT:ID=Title"
(UTF-8) for the titles each deck knows.

Without --control the decks are on and not playing. With --control FILE they
start off, and are driven by the file (JSON {"2": {"on": 0, "play": 0,
"sync": 0, "master": 0}, ...}) looked at twice a second: a number that changes
is a click on that switch, which toggles it (an "on" click switches the deck
on or off, the others change what it does). This is how the virtual deck's
side panel (app/virtual_djs.py) drives them. What each deck really is then
(the master role can pass to another player by itself) is written to FILE.state
(JSON {"2": {"on": true, "play": ..., "sync": ..., "master": ..., "bpm": ...}}).
A deck that is off sends nothing and closes the connections made to it.

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
BEAT_PORT, UPDATE_PORT, ANNOUNCE_PORT = 50001, 50002, 50000
PITCH_NORMAL = 0x100000
LOCK = threading.RLock()


def log(text):
    sys.stderr.write("fakedecks: %s\n" % text)
    sys.stderr.flush()


def header(ptype, name):
    p = bytearray(0x1F)
    p[0:10] = MAGIC
    p[0x0A] = ptype
    p[0x0B:0x0B + len(name)] = name
    return p


MODEL = None                            # a model name for every deck (--model)


def device_name(number):
    return (MODEL or "CDJ-FAKE%d" % number).encode()


def keepalive(number):
    p = bytearray(0x36)
    p[0:10] = MAGIC
    p[0x0A] = 0x06
    name = device_name(number)
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


# ---- the network as the decks share it ----------------------------------------

class World:
    """What the decks need to know of each other and of the unit under test:
    who is the tempo master and at what tempo."""

    def __init__(self):
        self.decks = {}
        self.dj = {"number": 0, "ip": None, "master": False, "bpm": None}   # the DJS, as heard
        self.state_path = None

    def master_deck(self):
        for deck in self.decks.values():
            if deck.enabled and deck.master:
                return deck
        return None

    def master_bpm(self):
        deck = self.master_deck()
        if deck:
            return deck.tempo()
        if self.dj["master"] and self.dj["bpm"]:
            return self.dj["bpm"]
        return None

    def settle(self, change):
        """Runs `change`, which alters what the decks are (who is the master,
        who syncs, who plays), keeping every deck's place in its bar through
        the change, and then putting the synced ones on the master's beat."""
        with LOCK:
            now = time.time()
            for deck in self.decks.values():
                deck.reanchor(now)
            change()
            now = time.time()
            master = self.master_deck()
            for deck in self.decks.values():
                if deck.enabled and deck.playing and deck.sync and master and master is not deck \
                        and master.playing:
                    deck.anchor_t = now
                    deck.anchor_pos = master.position(now)

    def save(self):
        """What the decks are, for the deck window to show."""
        if not self.state_path:
            return
        with LOCK:
            state = {str(n): {"on": d.enabled, "play": d.playing, "sync": d.sync,
                              "master": d.master and d.enabled, "bpm": round(d.tempo(), 2),
                              # Where the beat was when: t, beats into the bar, tempo; the
                              # deck window counts on from there, for its beat squares.
                              "phase": [d.anchor_t, d.anchor_pos, round(d.tempo(), 2)]
                              if d.enabled and d.playing else None}
                     for n, d in self.decks.items()}
        text = json.dumps(state, sort_keys=True)
        if text != getattr(self, "_saved", None):
            tmp = self.state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            os.replace(tmp, self.state_path)
            self._saved = text

    def sniff(self):
        """Listens to the keep-alives and statuses on the network for the
        unit (it names itself DJS-1000): its number and address, and whether it
        is the tempo master and at what tempo; and passes the master role when
        the unit takes it from a deck that has agreed to yield it."""
        socks = []
        for port in (ANNOUNCE_PORT, UPDATE_PORT):
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except (AttributeError, OSError):
                pass
            s.bind(("0.0.0.0", port))
            s.settimeout(0.5)
            socks.append((s, port))
        # What the unit sends to a deck itself (its status, to port 50002 of
        # the deck's address) goes to the socket bound to that address, not to
        # the ones bound to any address: a socket for each deck.
        for number in self.decks:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.%d" % number, UPDATE_PORT))
            s.settimeout(0.5)
            socks.append((s, UPDATE_PORT))
        import select
        while True:
            ready, _, _ = select.select([s for s, _ in socks], [], [], 0.5)
            for s in ready:
                data, addr = s.recvfrom(2048)
                port = s.getsockname()[1]
                if len(data) < 0x30 or data[:10] != MAGIC:
                    continue
                if data[0x0B:0x0F] == b"DJS-" or data[0x0C:0x10] == b"DJS-":
                    with LOCK:
                        if port == ANNOUNCE_PORT and data[0x0A] == 0x06:
                            if self.dj["number"] != data[0x24]:
                                self.dj["number"] = data[0x24]
                                log("the unit under test is player %d" % data[0x24])
                            self.dj["ip"] = ".".join(str(b) for b in data[0x2C:0x30])
                        elif port == UPDATE_PORT and data[0x0A] == 0x0A and len(data) > 0x93:
                            master = bool(data[0x89] & 0x20)
                            self.dj["syncn"] = struct.unpack(">I", data[0x84:0x88])[0]
                            now = (data[0x89], data[0x9E], data[0x9F], self.dj["syncn"])
                            if now != self.dj.get("flags"):
                                self.dj["flags"] = now
                                log("the unit's status: flags %#04x, master meaningful %d, hand-off to %#04x, "
                                    "sync counter %d" % now)
                            if master != self.dj["master"]:
                                log("the unit under test %s the tempo master"
                                    % ("is now" if master else "is no longer"))
                            self.dj["master"] = master
                            self.dj["bpm"] = struct.unpack(">H", data[0x92:0x94])[0] / 100.0
                            if master:
                                for deck in self.decks.values():
                                    if deck.master and deck.handing_to == data[0x21]:
                                        deck.finish_handoff()
                            for deck in self.decks.values():
                                if deck.pending and data[0x9F] == deck.number:
                                    threading.Thread(target=deck.take_after_handoff).start()
                    self.save()


class Deck:
    def __init__(self, world, number, loaded, titles, bpm):
        self.world = world
        self.number = number
        self.source, self.slot, self.rbid = loaded
        self.titles = titles                # {(slot, id): title} this deck knows
        self.queries = []
        self.base_bpm = bpm
        self.enabled = True
        self.playing = False
        self.sync = False
        self.master = False
        self.handing_to = 0xFF
        self.pending = False                # has asked the unit for the master role
        self.sync_number = 0
        self.counter = 0
        self.anchor_t = time.time()         # where it was in its bar at this time ...
        self.anchor_pos = 0.0               # ... in beats (0.0 is the first beat of the bar)
        self.name = device_name(number)

    def position(self, now):
        """Beats since the bar line, counting on from the anchor at the tempo
        it plays at (a stopped deck stays where it stopped)."""
        if not self.playing:
            return self.anchor_pos
        return self.anchor_pos + (now - self.anchor_t) * self.tempo() / 60.0

    def reanchor(self, now):
        self.anchor_pos = self.position(now)
        self.anchor_t = now

    @property
    def beat_in_bar(self):
        return int(self.position(time.time())) % 4 + 1

    # -- what the deck is --
    def tempo(self):
        """The tempo it plays at: its own, or the master's if it is synced."""
        if self.master or not self.sync:
            return self.base_bpm
        return self.world.master_bpm() or self.base_bpm

    def flags(self):
        # Bit 2 is set on a CDJ that is on the link (not explained in the
        # analysis); the unit's own choice of the tempo master looks for
        # playing + synced + on air + that bit (flags & 0x5c == 0x5c).
        f = 0x84                                         # bits 7 and 2, as a real player has them
        if self.playing:
            f |= 0x40 | 0x08                             # playing, on air
        if self.master:
            f |= 0x20
        # While it waits for the unit to hand the master role over, its status
        # says it is synced: the unit only hands over to a deck that is (its
        # SYNC switch is not touched).
        if self.sync or self.pending:
            f |= 0x10
        return f

    def status(self):
        p = bytearray(max(STATUS_LENGTH, 0xD4))
        p[0:10] = MAGIC
        p[0x0A] = 0x0A
        p[0x0B:0x0B + len(self.name)] = self.name
        # The header a CDJ's status has after its name: 01, the subtype (03),
        # the player, and the number of bytes that follow (lenr).
        p[0x1F], p[0x20], p[0x21] = 0x01, 0x03, self.number
        p[0x22:0x24] = struct.pack(">H", len(p) - 0x24)
        p[0x24] = self.number
        p[0x27] = 1 if self.playing else 0               # activity
        p[0x28], p[0x29], p[0x2A] = self.source, self.slot, 1
        p[0x2C:0x30] = struct.pack(">I", self.rbid)
        p[0x7B] = 3 if self.playing else 5               # playing / paused
        p[0x7C:0x80] = b"1.00"
        p[0x84:0x88] = struct.pack(">I", self.sync_number)
        p[0x89] = self.flags()
        p[0x8B] = 0x7A if self.playing else 0x7E
        pitch = struct.pack(">I", PITCH_NORMAL)
        for at in (0x8C, 0x98, 0xC0, 0xC4):              # the four copies of the pitch
            p[at:at + 4] = pitch
        p[0x90:0x92] = struct.pack(">H", 0x8000)         # a rekordbox track: its tempo counts
        p[0x92:0x94] = struct.pack(">H", int(round(self.tempo() * 100)))
        p[0x94:0x98] = bytes((0x7F, 0xFF, 0xFF, 0xFF))   # no slip play
        p[0x9D] = 0x0D if self.playing else 0x01         # forward, CDJ jog / paused
        p[0x9E] = 1 if self.master else 0                # "master meaningful"
        p[0x9F] = self.handing_to
        p[0xA0:0xA4] = struct.pack(">I", int(self.position(time.time())) + 1)   # the beat in the track
        p[0xA4:0xA6] = bytes((0x01, 0xFF))               # no cue point ahead
        p[0xA6] = self.beat_in_bar
        self.counter += 1
        p[0xC8:0xCC] = struct.pack(">I", self.counter)
        p[0xCC] = 0x0F                                   # a nexus
        return bytes(p)

    def beat(self):
        """The beat packet at the beginning of a beat."""
        period = 60000.0 / self.tempo()
        beat = self.beat_in_bar
        left = 5 - beat                                  # beats to the next bar line
        p = bytearray(0x60)
        p[0:0x1F] = header(0x28, self.name)
        p[0x1F], p[0x21], p[0x23] = 0x01, self.number, 0x3C
        for i, beats in enumerate((1, 2, left, 4, left + 4, 8)):
            p[0x24 + 4 * i:0x28 + 4 * i] = struct.pack(">I", int(period * beats))
        p[0x55:0x58] = struct.pack(">I", PITCH_NORMAL)[1:]
        p[0x5A:0x5C] = struct.pack(">H", int(round(self.tempo() * 100)))
        p[0x5C] = beat
        p[0x5F] = self.number
        return bytes(p)

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
                s.sendto(keepalive(self.number), (BROADCAST, ANNOUNCE_PORT))
                last_keep = now
            if now - last_status >= 0.2:
                with LOCK:
                    packet = self.status()
                s.sendto(packet, (BROADCAST, UPDATE_PORT))
                last_status = now
            time.sleep(0.05)

    def beats(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.bind(("127.0.0.%d" % self.number, 0))
        sent = None                         # the beat (counted from the anchor) last sent
        while True:
            if not (self.enabled and self.playing):
                sent = None
                time.sleep(0.05)
                continue
            with LOCK:
                now = time.time()
                pos = self.position(now)
                tempo = self.tempo()
                beat = int(pos)
                due = (beat + 1 - pos) * 60.0 / tempo
                packet = self.beat() if sent != beat else None
            if packet:
                s.sendto(packet, (BROADCAST, BEAT_PORT))
                sent = beat
            time.sleep(min(max(due, 0.002), 0.02))

    def control(self):
        """Master hand-off requests and sync commands, sent to this deck."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.%d" % self.number, BEAT_PORT))
        out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        out.bind(("127.0.0.%d" % self.number, 0))
        while True:
            data, addr = s.recvfrom(2048)
            if not self.enabled or len(data) < 0x25 or data[:10] != MAGIC:
                continue
            kind, sender = data[0x0A], data[0x21]
            if kind not in (0x26, 0x2A):
                log("deck %d: packet type %#04x from %d, %d bytes: %s"
                    % (self.number, kind, sender, len(data), data[0x1F:].hex()))
            if kind == 0x26:                                     # master hand-off request
                with LOCK:
                    if not self.master:
                        log("deck %d: hand-off request from %d, but it is not the master"
                            % (self.number, sender))
                        continue
                    log("deck %d: yields the master role to %d" % (self.number, sender))
                    self.handing_to = sender
                reply = header(0x27, self.name) + bytes([
                    0x01, 0x00, self.number, 0x00, 0x08, 0x00, 0x00, 0x00, self.number,
                    0x00, 0x00, 0x00, 0x01])
                out.sendto(bytes(reply), (addr[0], UPDATE_PORT))
                threading.Timer(4.0, self.finish_handoff, args=(sender,)).start()
                self.world.save()
            elif kind == 0x2A:                                   # a sync command
                command = data[0x2B] if len(data) > 0x2B else 0
                log("deck %d: sync command %#x from %d" % (self.number, command, sender))
                if command == 0x10:
                    self.set_sync(True)
                elif command == 0x20:
                    self.set_sync(False)
                elif command == 0x01:
                    self.set_master(True)

    # -- what clicks and commands do --
    def set_sync(self, on):
        def change():
            self.sync = on
        self.world.settle(change)
        log("deck %d sync %s: %.1f BPM" % (self.number, "on" if on else "off", self.tempo()))
        self.world.save()

    def set_play(self, on):
        def change():
            self.playing = on
            if on:                                  # from the first beat of a bar
                self.anchor_t = time.time()
                self.anchor_pos = 0.0
        self.world.settle(change)
        log("deck %d %s" % (self.number, "plays" if on else "stops"))
        self.world.save()

    def set_enabled(self, on):
        def change():
            self.enabled = on
            if not on:
                self.master = False
                self.handing_to = 0xFF
        self.world.settle(change)
        log("deck %d %s" % (self.number, "on" if on else "off"))
        self.world.save()

    def finish_handoff(self, to=None):
        """The deck stops being the master (the new one has said it is, or
        the time is up)."""
        def change():
            if self.master and self.handing_to != 0xFF and (to is None or to == self.handing_to):
                self.master = False
                self.handing_to = 0xFF
                log("deck %d is no longer the master" % self.number)
        self.world.settle(change)
        self.world.save()

    def set_master(self, on):
        """Takes the master role (from whoever has it), or lets go of it."""
        world = self.world

        def change():
            if not on:
                self.master = False
                self.handing_to = 0xFF
            else:
                dj = dict(world.dj)
                # The role is a fake deck's, if one has it (the unit's own flag
                # can be a stale one: it does not always let go): pass it on
                # between fake decks. Only when none has it, the unit might.
                fake_master = any(o is not self and o.enabled and o.master
                                  for o in world.decks.values())
                if dj["master"] and dj["ip"] and not fake_master:
                    # The unit has the role: ask it (to port 50001), and take the
                    # role when its status names this deck as the one to get it
                    # (Mh): see take_after_handoff().
                    request = header(0x26, self.name) + bytes([
                        0x01, 0x00, self.number, 0x00, 0x04, 0x00, 0x00, 0x00, self.number])
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.bind(("127.0.0.%d" % self.number, 0))
                    s.sendto(bytes(request), (dj["ip"], BEAT_PORT))
                    s.close()
                    self.pending = True
                    log("deck %d asks the unit under test to yield the master role" % self.number)
                    threading.Timer(3.0, self.give_up).start()
                    return
                for other in world.decks.values():
                    if other is not self and other.enabled and other.master:
                        other.handing_to = self.number
                        threading.Timer(1.0, other.finish_handoff, args=(self.number,)).start()
                self.master = True
                self.sync_number += 1
        world.settle(change)
        if on and self.pending:
            return
        log("deck %d is %s the master" % (self.number, "now" if on else "no longer"))
        world.save()

    def take_after_handoff(self):
        """The unit's status names this deck as the next master: it is."""
        if not self.pending:
            return

        def change():
            self.pending = False
            self.master = True
            self.sync_number = max(self.sync_number, self.world.dj.get("syncn", 0)) + 1
        self.world.settle(change)
        log("deck %d is now the master (the unit handed it over)" % self.number)
        self.world.save()

    def give_up(self):
        """The unit did not hand the role over in time (it plays no part, or
        is not syncing a playing deck): the deck takes it anyway, so the
        master of the fake decks can always be changed."""
        if self.pending:
            log("deck %d: the unit under test did not hand over the master role; taking it" % self.number)
            self.take_after_handoff()

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


STATUS_LENGTH = 0x124


def main():
    global STATUS_LENGTH, MODEL
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--decks", type=int, default=4)
    ap.add_argument("--numbers", metavar="N,N,...",
                    help="the decks' player numbers (default 1..DECKS)")
    ap.add_argument("--loaded", action="append", default=[], metavar="DECK=SOURCE:SLOT:ID")
    ap.add_argument("--titles", metavar="FILE")
    ap.add_argument("--init", action="append", default=[], metavar="DECK=play,sync,master",
                    help="start this deck playing, synced and/or the master")
    ap.add_argument("--model", help="the device name every deck announces (default CDJ-FAKEn)")
    ap.add_argument("--status-length", type=lambda x: int(x, 0), default=0x124, metavar="N",
                    help="the length of the status packets (default 0x124)")
    ap.add_argument("--control", metavar="FILE",
                    help="drive the decks from this JSON file, starting off")
    a = ap.parse_args()
    STATUS_LENGTH = a.status_length
    MODEL = a.model
    numbers = [int(x) for x in a.numbers.split(",")] if a.numbers else list(range(1, a.decks + 1))
    loaded = {d: (d, 3, 100 + d) for d in numbers}
    for item in a.loaded:
        d, rest = item.split("=")
        loaded[int(d)] = tuple(int(x) for x in rest.split(":"))
    known = {d: {(3, 100 + d): "Track of deck %d" % d} for d in numbers}
    if a.titles:
        for line in open(a.titles, encoding="utf-8"):
            line = line.rstrip("\n")
            if "=" in line and ":" in line.split("=")[0]:
                key, title = line.split("=", 1)
                src, slot, rbid = (int(x) for x in key.split(":"))
                known.setdefault(src, {})[(slot, rbid)] = title
    world = World()
    if a.control:
        world.state_path = a.control + ".state"
    for i, d in enumerate(numbers):
        deck = world.decks[d] = Deck(world, d, loaded[d], known.get(d, {}), 128.0 - 2 * i)
        deck.enabled = not a.control
        for item in a.init:
            which, _, what = item.partition("=")
            if int(which) == d:
                deck.playing = "play" in what
                deck.sync = "sync" in what
                deck.master = "master" in what
        for target in (deck.announce, deck.beats, deck.control, deck.serve_port, deck.serve_db):
            threading.Thread(target=target, daemon=True).start()
        log("deck %d on 127.0.0.%d: track %d:%d:%d at %.0f BPM"
            % ((d, d) + loaded[d] + (deck.base_bpm,)))
    threading.Thread(target=world.sniff, daemon=True).start()
    seen = {}
    first = True
    while True:
        if a.control:
            try:
                wanted = json.load(open(a.control, encoding="utf-8"))
            except (OSError, ValueError):
                wanted = None
            if isinstance(wanted, dict):
                for d, deck in world.decks.items():
                    clicks = wanted.get(str(d))
                    if not isinstance(clicks, dict):
                        clicks = {}
                    for what in ("on", "play", "sync", "master"):
                        n = int(clicks.get(what, 0))
                        if first:
                            seen[(d, what)] = n             # what is there at the start is not a click
                        elif n != seen.get((d, what), 0):
                            seen[(d, what)] = n
                            if what == "on":
                                deck.set_enabled(not deck.enabled)
                            elif not deck.enabled:
                                continue
                            elif what == "play":
                                deck.set_play(not deck.playing)
                            elif what == "sync":
                                deck.set_sync(not deck.sync)
                            elif what == "master":
                                deck.set_master(not deck.master)
                first = False
        world.save()
        time.sleep(0.5)


if __name__ == "__main__":
    main()
