#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Launcher ownership checks without firmware or a running emulator."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import start
import bench_process
from app.bench import request


class BenchOwnership(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.run = Path(self.folder.name)
        (self.run / 'deckbench-owned.json').write_text(json.dumps({'pid': 1234, 'start': 'original'}))

    def command(self):
        return b'python3\0-m\0deckbench\0--ready-file\0' + bytes(str(self.run / 'deckbench-ready.json'), 'utf-8') + b'\0'

    def test_recycled_pid_is_not_owned(self):
        with patch.object(bench_process, 'identity', return_value='another'), patch.object(Path, 'read_bytes', return_value=self.command()):
            self.assertIsNone(bench_process.owned(self.run))

    def test_matching_pid_with_another_command_is_not_owned(self):
        with patch.object(bench_process, 'identity', return_value='original'), patch.object(Path, 'read_bytes', return_value=b'python3\0-m\0deckbench\0'):
            self.assertIsNone(bench_process.owned(self.run))

    def test_matching_identity_and_ready_path_are_owned(self):
        with patch.object(bench_process, 'identity', return_value='original'), patch.object(Path, 'read_bytes', return_value=self.command()):
            self.assertEqual(bench_process.owned(self.run), 1234)

    def test_stop_does_not_signal_an_unowned_bench(self):
        with patch.object(bench_process, 'owned', return_value=None), patch.object(bench_process.os, 'kill') as kill:
            bench_process.stop(self.run)
            kill.assert_not_called()

    def test_failed_start_does_not_adopt_or_kill_an_external_bench(self):
        process = Mock(pid=4321)
        process.poll.return_value = 1
        with patch.object(bench_process, 'owned', return_value=None), patch.object(bench_process, 'identity', return_value=None), patch.object(bench_process.subprocess, 'Popen', return_value=process) as launch, patch.object(bench_process.os, 'kill') as kill:
            with self.assertRaisesRegex(RuntimeError, '--bench-url'):
                bench_process.ensure(self.run, self.run, 7320)
            kill.assert_not_called()
            self.assertIn('--ready-file', launch.call_args.args[0])

    def test_with_a_dj_adapter_the_bench_only_watches_it(self):
        ready = self.run / 'deckbench-ready.json'
        line = bench_process.command(7320, ready, {'address': '169.254.10.5', 'netmask': '255.255.0.0',
                                                   'broadcast': '169.254.255.255'})
        self.assertIn('--observe', line)
        self.assertEqual(line[line.index('--bind') + 1], '169.254.10.5')
        self.assertEqual(line[line.index('--broadcast') + 1], '169.254.255.255')
        self.assertNotIn('--numbers', line)
        self.assertIn('--numbers', bench_process.command(7320, ready))
        feed = bench_process.command(7320, ready, feed='127.0.0.1:7330')
        self.assertEqual(feed[feed.index('--feed') + 1], '127.0.0.1:7330')
        self.assertNotIn('--bind', feed)
        self.assertNotEqual(bench_process.mode_of(None, '127.0.0.1:7330'), bench_process.mode_of(None))

    def test_the_launcher_asks_for_a_watching_bench_on_another_address(self):
        emu = start.Emulator(None, 7310)
        emu._repo = '/tmp/emulator'
        emu.network = {'DJSDEV_INTERFACE': 'eth1', 'DJSDEV_ADDRESS': '169.254.10.5', 'DJSDEV_NETMASK': '255.255.0.0',
                       'DJSDEV_BROADCAST': '169.254.255.255'}
        emu.sh = Mock(return_value=(0, 'http://127.0.0.1:8750/'))
        with patch.object(start, 'WINDOWS', False), patch.object(start.os.path, 'isfile', return_value=True):
            self.assertEqual(emu.deckbench(), 'http://127.0.0.1:8750/')  # no second address: through the feed
            self.assertIn('--feed ' + start.FEED, emu.sh.call_args.args[0])
            self.assertNotIn('--observe', emu.sh.call_args.args[0])
            emu.bench_row = {'interface': 'eth1', 'address': '169.254.10.6', 'netmask': '255.255.0.0',
                             'broadcast': '169.254.255.255'}
            self.assertEqual(emu.deckbench(), 'http://127.0.0.1:8750/')
        self.assertIn('--observe 169.254.10.6 255.255.0.0 169.254.255.255', emu.sh.call_args.args[0])
        emu.network = {}                                             # local testing: the simulated decks, as before
        with patch.object(start, 'WINDOWS', False), patch.object(start.os.path, 'isfile', return_value=True):
            emu.deckbench()
        self.assertNotIn('--observe', emu.sh.call_args.args[0])

    def test_the_benchs_address_is_another_one_on_the_same_network(self):
        environment = {'DJSDEV_INTERFACE': 'eth1', 'DJSDEV_ADDRESS': '169.254.10.5', 'DJSDEV_NETMASK': '255.255.0.0'}
        row = lambda name, address, prefix=16: {'interface': name, 'address': address, 'prefix': prefix,
                                                'netmask': '255.255.0.0', 'broadcast': '169.254.255.255'}
        self.assertIsNone(start.bench_address([row('eth1', '169.254.10.5'), row('eth0', '192.168.1.4')], environment))
        self.assertEqual(start.bench_address([row('eth2', '169.254.7.7'), row('eth1', '169.254.10.5'),
                                              row('eth1', '169.254.10.6')], environment)['address'], '169.254.10.6')
        self.assertEqual(start.bench_address([row('eth2', '169.254.7.7')], environment)['address'], '169.254.7.7')
        self.assertIsNone(start.bench_address([], {'DJSDEV_INTERFACE': ''}))

    def test_stop_invokes_only_the_owned_bench_helper(self):
        emu = start.Emulator(None, 7310)
        emu._repo = '/tmp/emulator'
        emu.sh = Mock(return_value=(0, ''))
        emu.stop()
        commands = '\n'.join(call.args[0] for call in emu.sh.call_args_list)
        self.assertIn('bench_process.py stop', commands)
        self.assertNotIn("pkill -f '[d]eckbench", commands)

    def test_external_bench_token_stays_out_of_request_urls(self):
        result = request('http://localhost:8750/#token=test-token', 'api/state')
        self.assertEqual(result.full_url, 'http://127.0.0.1:8750/api/state')
        self.assertEqual(result.get_header('Authorization'), 'Bearer test-token')

    def test_external_mode_does_not_stop_a_local_bench_either(self):
        emu = start.Emulator(None, 7310)
        emu.manage_bench = False
        emu.sh = Mock(return_value=(0, ''))
        emu.stop()
        commands = '\n'.join(call.args[0] for call in emu.sh.call_args_list)
        self.assertNotIn('bench_process.py stop', commands)

    def test_external_url_validation(self):
        for url in ('file:///tmp/bench', 'http://user:password@localhost:8750/', 'not a URL'):
            with self.assertRaises(ValueError):
                request(url, 'api/state')


class NetworkSelection(unittest.TestCase):
    def test_network_command_uses_backend_home_and_distro(self):
        emu = start.Emulator('Test Linux', 7310)
        emu._repo = '/tmp/emulator'
        emu.sh = Mock(return_value=(0, '/home/test/djs-s7'))
        with patch.object(start, 'WINDOWS', True):
            command = emu.network_command()
        self.assertEqual(command[:4], ['wsl.exe', '-d', 'Test Linux', '--'])
        self.assertEqual(command[-2:], ['--home', '/home/test/djs-s7'])

    def test_configuration_is_explicit_and_running_match_is_checked(self):
        emu = start.Emulator(None, 7310)
        with patch.object(start, 'network_query', return_value={'DJSDEV_INTERFACE': '', 'DJSDEV_ADDRESS': ''}) as query:
            self.assertFalse(emu.configure_network(['helper']))
            self.assertIn("DJSDEV_INTERFACE=''", emu.env)
        with patch.object(start, 'network_query', return_value={'DJSDEV_INTERFACE': 'eth2', 'DJSDEV_ADDRESS': '169.254.10.5'}):
            self.assertTrue(emu.configure_network(['helper']))
            self.assertIn('DJSDEV_INTERFACE=eth2', emu.env)
        emu.sh = Mock(return_value=(0, '123'))
        with patch.object(start, 'network_query', return_value=False) as query:
            self.assertFalse(emu.network_matches(['helper']))
            query.assert_called_once_with(['helper'], 'matches', '123')


@unittest.skipUnless(sys.platform.startswith('linux'), 'needs Linux process identity')
class LinuxOwnership(unittest.TestCase):
    def test_start_reuse_and_stop_only_the_recorded_child(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder) / 'repo'
            package = repo / 'deckbench'
            package.mkdir(parents=True)
            (package / '__init__.py').write_text('')
            (package / '__main__.py').write_text(
                'import json,sys,time\nfrom pathlib import Path\n'
                "ready=Path(sys.argv[sys.argv.index('--ready-file')+1])\n"
                "ready.write_text(json.dumps({'http':'http://127.0.0.1:8750/'}))\n"
                'while True: time.sleep(.1)\n')
            run = Path(folder) / 'run'
            pid = None
            try:
                self.assertEqual(bench_process.ensure(repo, run, 0), 'http://127.0.0.1:8750/')
                pid = bench_process.owned(run)
                self.assertIsNotNone(pid)
                bench_process.ensure(repo, run, 0)
                self.assertEqual(bench_process.owned(run), pid)
                observe = {'address': '127.0.0.5', 'netmask': '255.0.0.0', 'broadcast': '127.255.255.255'}
                bench_process.ensure(repo, run, 0, observe)          # another mode: started again
                os.waitpid(pid, 0)
                pid = bench_process.owned(run)
                self.assertIsNotNone(pid)
                bench_process.ensure(repo, run, 0, observe)
                self.assertEqual(bench_process.owned(run), pid)
                bench_process.stop(run)
                self.assertIsNone(bench_process.owned(run))
            finally:
                bench_process.stop(run)
                if pid:
                    os.waitpid(pid, 0)


if __name__ == '__main__':
    unittest.main()
