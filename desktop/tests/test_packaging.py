"""Tests for binary-only startup and bundled backend process dispatch."""
import os
import pathlib
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from desktop.processes import BackendManager
from desktop.autostart import destination, set_enabled
from desktop.bundled_entry import run_backend_server


class TestFrozenApp(unittest.TestCase):
    def test_packaged_native_supervisor_launches_same_executable(self):
        manager = BackendManager(ROOT, system='Linux')
        with mock.patch.object(sys, 'frozen', True, create=True):
            self.assertEqual(manager._cmd('codex'), [sys.executable, '--backend-supervisor', 'codex'])
            self.assertEqual(manager._cmd('claude'), [sys.executable, '--backend-supervisor', 'claude'])

    def test_source_native_supervisor_preserved(self):
        manager = BackendManager(ROOT, system='Linux')
        self.assertEqual(manager._cmd('codex'), [sys.executable, str(ROOT / 'desktop' / 'managed_native.py'), 'codex'])

    def test_packaged_autostart_points_to_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp) / 'home'
            binary = pathlib.Path(tmp) / 'App Folder' / 'ProviderUsageTray'
            for system in ('Darwin', 'Linux'):
                with mock.patch.object(sys, 'frozen', True, create=True), mock.patch.object(sys, 'executable', str(binary)):
                    with mock.patch.dict(os.environ, {'XDG_CONFIG_HOME': str(home / '.config')}):
                        set_enabled(True, root=ROOT, system=system, home=home)
                        path = destination(system, home)
                        if system == 'Darwin':
                            plist = plistlib.loads(path.read_bytes())
                            self.assertEqual(plist['ProgramArguments'], [str(binary.resolve())])
                            self.assertEqual(plist['WorkingDirectory'], str(binary.parent.resolve()))
                        else:
                            self.assertIn(str(binary.resolve()).replace('\\', '\\\\'), path.read_text())
                            self.assertNotIn('start-linux.sh', path.read_text())
                        set_enabled(False, root=ROOT, system=system, home=home)

    def test_bundled_server_entry_help_without_network_access(self):
        # Ensures both original backend parsers are accessible through dispatcher.
        for service in ('codex', 'claude'):
            run = subprocess.run(
                [sys.executable, '-m', 'desktop.bundled_entry', '--backend-server', service, '--help'],
                cwd=ROOT, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(run.returncode, 0, f'{service}: {run.stderr}')
            self.assertIn('--port', run.stdout)

    def test_unknown_service_is_rejected(self):
        self.assertEqual(run_backend_server('unlisted'), 2)


if __name__ == '__main__':
    unittest.main()
