import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from desktop.core import app_data_dir, load_settings, parse_response, save_settings, secure_child_env
from desktop.autostart import set_enabled, destination


class TestCore(unittest.TestCase):
    def test_fresh_response_and_missing_limit(self):
        data = parse_response({'ok': True, 'stale': False,
            'five_hour': {'remaining_percent': 31.23, 'resets_at': '2026-10-27T12:00:00Z'},
            'weekly': None})
        self.assertEqual(data['five_hour']['remaining_percent'], 31.23)
        self.assertIsNone(data['weekly'])

    def test_stale_never_displays_cached_data(self):
        data = parse_response({'ok': True, 'stale': True, 'five_hour': {'remaining_percent': 88}})
        self.assertFalse(data['ok'])
        self.assertIsNone(data['five_hour'])

    def test_bogus_percentage_rejected(self):
        data = parse_response({'ok': True, 'five_hour': {'remaining_percent': 120}, 'weekly': {'remaining_percent': True}})
        self.assertIsNone(data['five_hour'])
        self.assertIsNone(data['weekly'])

    def test_config_roundtrip_and_safe_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            path = pathlib.Path(temp) / 'settings.json'
            save_settings({'show_weekly': False, 'manage_backends': True, 'wsl_distro': 'Ubuntu-24.04'}, path)
            self.assertEqual(load_settings(path)['wsl_distro'], 'Ubuntu-24.04')
            path.write_text('{bad json')
            self.assertTrue(load_settings(path)['show_weekly'])

    def test_windows_environment_trim(self):
        env = {'SystemRoot': r'C:\Windows', 'Path': 'x' * 200_000, 'HUGE_JSON': 'z' * 250_000,
               'USERPROFILE': r'C:\Users\x', 'TEMP': r'C:\Temp'}
        new = secure_child_env(env, 'Windows')
        self.assertNotIn('HUGE_JSON', new)
        self.assertLess(sum(len(k) + len(v) + 2 for k, v in new.items()), 60_000)
        self.assertIn('System32', new['Path'])

    def test_mac_and_linux_startup_generation(self):
        with tempfile.TemporaryDirectory() as temp:
            home, root = pathlib.Path(temp) / 'home', pathlib.Path(temp) / 'repo with space'
            for system in ('Darwin', 'Linux'):
                with mock.patch.dict(os.environ, {'XDG_CONFIG_HOME': str(home / '.config')}, clear=False):
                    set_enabled(True, root=root, system=system, home=home)
                    path = destination(system, home)
                    self.assertTrue(path.is_file())
                    self.assertIn(str(root), path.read_text())
                    set_enabled(False, root=root, system=system, home=home)
                    self.assertFalse(path.exists())
