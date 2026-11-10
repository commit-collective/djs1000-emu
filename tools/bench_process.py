#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Manage only the local Deckbench process recorded by this emulator installation."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def identity(pid):
    """Linux start time protects against a recycled PID, without broad process matching."""
    try:
        fields = Path('/proc/%d/stat' % pid).read_text().rsplit(')', 1)[1].split()
        return None if fields[0] == 'Z' else fields[19]
    except (OSError, IndexError):
        return None


PAGE = 'http://127.0.0.1:8750/'


def other_bench():
    """Whether a Deckbench answers on its page's port: its state, or its refusal without the token."""
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(PAGE + 'api/state', timeout=2) as reply:
            return 'decks' in json.load(reply)
    except urllib.error.HTTPError as error:
        return error.code == 401 and b'token' in error.read()
    except (OSError, ValueError):
        return False


def owned(run):
    try:
        state = json.loads((run / 'deckbench-owned.json').read_text())
        pid = int(state['pid'])
        args = Path('/proc/%d/cmdline' % pid).read_bytes().split(b'\0')
        if (pid > 1 and identity(pid) == state['start'] and
                b'deckbench' in args and b'--ready-file' in args and
                os.fsencode(str(run / 'deckbench-ready.json')) in args):
            return pid
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def stop(run):
    pid = owned(run)
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 3
        while owned(run) and time.monotonic() < deadline:
            time.sleep(.05)
        if owned(run):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    for name in ('deckbench-owned.json', 'deckbench-ready.json'):
        (run / name).unlink(missing_ok=True)


def command(audio_port, ready, observe=None, feed=None, http_port=None):
    """Deckbench's command line. With `observe` (an address of the DJ adapter's network other than the unit's, its
    netmask and broadcast), a bench that only watches that network from there: no simulated decks on a real link.
    With `feed` (address:port), one that watches it through the copy the emulator sends there, binding nothing of the
    link. Otherwise the usual simulated decks on the loopback, switched off until the page turns them on."""
    page = ['--http-port', str(http_port)] if http_port is not None else []
    if feed:
        return [sys.executable, '-m', 'deckbench', '--feed', feed, '--ready-file', str(ready)] + page
    if observe:
        return [sys.executable, '-m', 'deckbench', '--observe', '--bind', observe['address'],
                '--netmask', observe['netmask'], '--broadcast', observe['broadcast'], '--ready-file', str(ready)] + page
    return [sys.executable, '-m', 'deckbench', '--numbers', '1,2,3,4', '--audio-port', str(audio_port),
            '--ready-file', str(ready)] + page


def mode_of(observe, feed=None):
    return 'feed %s' % feed if feed else 'observe %s' % observe['address'] if observe else 'decks'


def ensure(repo, run, audio_port, observe=None, feed=None):
    run.mkdir(parents=True, exist_ok=True)
    ready = run / 'deckbench-ready.json'
    mode = mode_of(observe, feed)
    pid = owned(run)
    if pid:
        began = (run / 'deckbench-owned.json').stat().st_mtime
        try:
            was = json.loads((run / 'deckbench-owned.json').read_text()).get('mode', 'decks')
        except (OSError, ValueError, AttributeError):
            was = None
        if (was != mode or not ready.exists() or
                any(path.stat().st_mtime > began for path in (repo / 'deckbench').rglob('*.py'))):
            stop(run)
            pid = None
    # Its page on 8750, as always. A port a bench closed a moment ago can stay held for two minutes or so (Windows
    # keeps a closed connection's port, and with mirrored networking that holds the port in WSL too, whatever
    # wsl --shutdown does): when nothing answers there, the page goes on any free port, which the deck is given.
    for http_port in (None, 0):
        if pid:
            break
        ready.unlink(missing_ok=True)
        log_path = run / 'deckbench.log'
        with log_path.open('ab') as log:
            began_at = log.tell()                   # what this start writes, for the message if it fails
            process = subprocess.Popen(command(audio_port, ready, observe, feed, http_port),
                                       cwd=repo, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       start_new_session=True)
        state = {'pid': process.pid, 'start': identity(process.pid), 'mode': mode}
        (run / 'deckbench-owned.json').write_text(json.dumps(state))
        # A checkout on a Windows drive (/mnt/c) loads slowly in WSL: give the first start time.
        deadline = time.monotonic() + 30
        while not ready.exists() and time.monotonic() < deadline and process.poll() is None:
            time.sleep(.05)
        if ready.exists():
            break
        gone = process.poll() is not None
        stop(run)
        if gone and other_bench():
            raise RuntimeError('A Deckbench this emulator did not start already answers at %s (with mirrored WSL '
                               'networking a Windows one counts too). Use it with --bench-url %s (add '
                               '#token=... if it has one), stop it, or use --no-bench.' % (PAGE, PAGE))
        with log_path.open('rb') as log:
            log.seek(began_at)
            said = [line for line in log.read().decode('utf-8', 'replace').splitlines() if line.strip()][-4:]
        if gone and http_port is None and any('page cannot listen' in line for line in said):
            continue                                # 8750 still held by a closed one: any free port
        raise RuntimeError('The local bench %s. %s'
                           'Use --bench-url for an existing bench or --no-bench for hardware-only use. See %s'
                           % ('stopped before it was ready' if gone else 'was not ready after 30 s',
                              ('It said: ' + ' / '.join(said).rstrip('.') + '. ') if said else '', log_path))
    return json.loads(ready.read_text())['http'].replace('0.0.0.0', '127.0.0.1')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('ensure', 'stop'))
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--repo', type=Path)
    parser.add_argument('--audio-port', type=int, default=7320)
    parser.add_argument('--observe', nargs=3, metavar=('ADDRESS', 'NETMASK', 'BROADCAST'),
                        help="watch the chosen DJ adapter's network instead of simulating decks")
    parser.add_argument('--feed', metavar='ADDRESS:PORT', help="watch the link through the emulator's copy of it")
    args = parser.parse_args()
    observe = dict(zip(('address', 'netmask', 'broadcast'), args.observe)) if args.observe else None
    try:
        import fcntl
        run = args.run.resolve()
        run.mkdir(parents=True, exist_ok=True)
        with (run / 'deckbench-manager.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if args.action == 'stop':
                stop(run)
            else:
                print(ensure(args.repo.resolve(), run, args.audio_port, observe, args.feed))
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
