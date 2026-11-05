#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Firmware-free adapter configuration and Linux routing checks."""
import json
import importlib.util
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

import network_backend as backend

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@unittest.skipUnless(importlib.util.find_spec('pygame'), 'needs pygame-ce')
class Picker(unittest.TestCase):
    def exercise(self, save):
        os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
        os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
        import pygame
        from app import network_picker
        row = {'interface': 'eth2', 'address': '169.254.10.5', 'prefix': 16}
        data = {'interfaces': [row], 'selected': {'interface': '', 'address': ''}}
        events = [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN),
                  pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN if save else pygame.K_ESCAPE)]
        with patch.object(network_picker, 'query', side_effect=[data, {}]) as query, patch.object(pygame.event, 'get', return_value=events):
            self.assertEqual(network_picker.choose(['helper']), save)
            if save:
                query.assert_called_with(['helper'], 'select', 'eth2', '169.254.10.5')
            else:
                self.assertEqual(query.call_count, 1)
        self.assertFalse(pygame.display.get_init())

    def test_picker_saves_only_selected_address(self):
        self.exercise(True)

    def test_cancel_does_not_save(self):
        self.exercise(False)


@unittest.skipUnless(importlib.util.find_spec('pygame'), 'needs pygame-ce')
class Submenu(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
        os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
        import pygame
        import deck_selftest
        pygame.display.init()
        pygame.font.init()
        self.addCleanup(pygame.display.quit)
        self.deck = deck_selftest.virtual_djs.Deck(deck_selftest.FakeLink(), (420, 500),
                                                  (deck_selftest.FakePlayer(), None), None, [0])
        self.deck.network_command = ['helper']
        self.data = {'interfaces': [{'interface': 'eth2', 'address': '169.254.10.5', 'prefix': 16}],
                     'selected': {'interface': '', 'address': ''}}

    def test_menu_selects_without_replacing_the_window(self):
        import pygame
        # The frontend imports the same helper by its script-local module name.
        import network_picker as frontend_picker
        with patch.object(frontend_picker, 'query', side_effect=[self.data, {'interface': 'eth2', 'address': '169.254.10.5'}]) as query:
            surface = self.deck.win
            self.deck.choose_network()
            self.deck.draw_menu()
            self.assertIs(self.deck.win, surface)
            self.assertLess(self.deck.menu_panel.height, 160)
            self.assertTrue(self.deck.win.get_rect().contains(self.deck.menu_panel))
            index = next(i for i, item in enumerate(self.deck.menu_items) if item[0].startswith('eth2'))
            self.deck.press(self.deck.menu_rects[index][0].center)
            query.assert_called_with(['helper'], 'select', 'eth2', '169.254.10.5')
            self.assertEqual(self.deck.network_menu['selected']['interface'], 'eth2')
            self.deck.key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0), True)
            self.assertIsNone(self.deck.network_menu)
            self.assertTrue(self.deck.menu_open)

    def test_many_adapters_are_paged_inside_the_window(self):
        self.data['interfaces'] *= 40
        self.deck.network_menu = self.data
        self.deck.menu_open = True
        self.deck.draw_menu()
        self.assertTrue(self.deck.win.get_rect().contains(self.deck.menu_panel))
        more = next(item for item in self.deck.menu_items if item[0] == 'More adapters')
        more[3]()
        self.deck.draw_menu()
        self.assertGreater(self.deck.network_offset, 0)
        self.assertTrue(self.deck.win.get_rect().contains(self.deck.menu_panel))
        self.deck.press((0, 0))
        self.assertFalse(self.deck.menu_open)

    def test_failed_save_preserves_the_checkmark(self):
        import network_picker
        self.deck.network_menu = self.data
        with patch.object(network_picker, 'query', side_effect=ValueError('Adapter is unavailable')):
            self.deck.select_network(self.data['interfaces'][0])
        self.assertEqual(self.deck.network_menu['selected'], {'interface': '', 'address': ''})


class Configuration(unittest.TestCase):
    def test_nat_mode_says_where_the_windows_adapters_are(self):
        from app import network_picker
        self.assertIn('mirrored', network_picker.hint({'wsl_mode': 'nat'}))
        for mode in ('mirrored', '', None):
            self.assertEqual(network_picker.hint({'wsl_mode': mode}), '')

    def test_reset_can_recover_invalid_saved_json(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'network.json').write_text('invalid json')
            with patch.object(sys, 'argv', ['network_backend', '--home', folder, 'select']), patch('builtins.print'):
                backend.main()
            self.assertEqual(backend.read(Path(folder)), {'interface': '', 'address': ''})

    def test_lists_ipv4_aliases_but_not_loopback_or_down(self):
        raw = [{'ifname': 'eth2', 'ifindex': 4, 'flags': ['UP'], 'addr_info': [
            {'family': 'inet', 'local': '169.254.10.5', 'prefixlen': 16},
            {'family': 'inet', 'local': '169.254.10.6', 'prefixlen': 16}]},
            {'ifname': 'lo', 'flags': ['UP'], 'addr_info': [
                {'family': 'inet', 'local': '127.0.0.1', 'prefixlen': 8}]},
            {'ifname': 'eth3', 'flags': [], 'addr_info': []}]
        with patch.object(backend.subprocess, 'run', return_value=Mock(stdout=json.dumps(raw))):
            rows = backend.interfaces()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['broadcast'], '169.254.255.255')
        self.assertEqual(rows[0]['netmask'], '255.255.0.0')
        self.assertEqual(backend.resolve({'interface': 'eth2', 'address': '169.254.10.6'}, rows), rows[1])
        with self.assertRaisesRegex(ValueError, 'unavailable'):
            backend.resolve({'interface': 'eth2', 'address': '169.254.10.7'}, rows)

    def test_save_and_reset_are_outside_checkout(self):
        row = {'interface': 'eth2', 'address': '169.254.10.5'}
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            self.assertEqual(backend.read(home), {'interface': '', 'address': ''})
            with patch.object(backend, 'interfaces', return_value=[row]):
                backend.save(home, **row)
                self.assertEqual(backend.read(home), row)
            backend.save(home, '', '')
            self.assertEqual(backend.resolve(backend.read(home), []), {})
            (home / 'network.json').write_text('[]')
            with self.assertRaises(ValueError):
                backend.read(home)

    @unittest.skipUnless(sys.platform.startswith('linux'), 'needs Linux sockets and ioctl')
    def test_native_identity_and_source_routing(self):
        with tempfile.TemporaryDirectory() as folder:
            binary = str(Path(folder) / 'network-test')
            subprocess.run(['gcc', '-Wall', '-Wextra', str(Path(__file__).with_name('network_test.c')),
                            '-ldl', '-o', binary], check=True)
            subprocess.run([binary], check=True, timeout=5)

    @unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('arm-linux-gnueabihf-gcc') and shutil.which('qemu-arm-static'), 'needs Linux ARM cross compiler and QEMU')
    def test_arm_identity_and_source_routing(self):
        with tempfile.TemporaryDirectory() as folder:
            binary = str(Path(folder) / 'network-test-arm')
            subprocess.run(['arm-linux-gnueabihf-gcc', '-static', str(Path(__file__).with_name('network_test.c')),
                            '-ldl', '-o', binary], check=True)
            subprocess.run(['qemu-arm-static', binary], check=True, timeout=10)


if __name__ == '__main__':
    unittest.main()
