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


def ensure(repo, run, audio_port):
    run.mkdir(parents=True, exist_ok=True)
    ready = run / 'deckbench-ready.json'
    pid = owned(run)
    if pid:
        began = (run / 'deckbench-owned.json').stat().st_mtime
        if not ready.exists() or any(path.stat().st_mtime > began for path in (repo / 'deckbench').rglob('*.py')):
            stop(run)
            pid = None
    if not pid:
        ready.unlink(missing_ok=True)
        log_path = run / 'deckbench.log'
        with log_path.open('ab') as log:
            began_at = log.tell()                   # what this start writes, for the message if it fails
            process = subprocess.Popen([sys.executable, '-m', 'deckbench', '--numbers', '1,2,3,4',
                                        '--audio-port', str(audio_port), '--ready-file', str(ready)],
                                       cwd=repo, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       start_new_session=True)
        state = {'pid': process.pid, 'start': identity(process.pid)}
        (run / 'deckbench-owned.json').write_text(json.dumps(state))
        # A checkout on a Windows drive (/mnt/c) loads slowly in WSL: give the first start time.
        deadline = time.monotonic() + 30
        while not ready.exists() and time.monotonic() < deadline and process.poll() is None:
            time.sleep(.05)
        if not ready.exists():
            gone = process.poll() is not None
            stop(run)
            with log_path.open('rb') as log:
                log.seek(began_at)
                said = [line for line in log.read().decode('utf-8', 'replace').splitlines() if line.strip()][-4:]
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
    args = parser.parse_args()
    try:
        import fcntl
        run = args.run.resolve()
        run.mkdir(parents=True, exist_ok=True)
        with (run / 'deckbench-manager.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if args.action == 'stop':
                stop(run)
            else:
                print(ensure(args.repo.resolve(), run, args.audio_port))
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
