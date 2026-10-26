import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

if os.name == 'nt':
    raise unittest.SkipTest('POSIX lifecycle tests run in GitHub Actions Linux and macOS')
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from desktop.processes import BackendManager

FAKE_SERVER = '''import os, pathlib, signal, sys, time
root = pathlib.Path(__file__).resolve().parent.parent
def finish(sig, frame):
    (root / 'stopped').write_text(str(os.getpid()))
    sys.exit(0)
# Register SIGTERM *before* writing the readiness marker. The test closes the
# parent's pipe as soon as it sees this file; the handler must already exist.
signal.signal(signal.SIGTERM, finish)
(root / 'running-pid').write_text(str(os.getpid()))
while True: time.sleep(.05)
'''


def wait_for(predicate, seconds=4):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.temp.name)
        (self.path / 'desktop').mkdir()
        (self.path / 'work-codex-usage-api').mkdir()
        shutil.copyfile(ROOT / 'desktop' / 'managed_native.py', self.path / 'desktop' / 'managed_native.py')
        (self.path / 'work-codex-usage-api' / 'server.py').write_text(FAKE_SERVER)

    def tearDown(self):
        self.temp.cleanup()

    @mock.patch('desktop.processes.port_open', return_value=False)
    @mock.patch('desktop.processes.SERVICES', {'codex': {'port': 3789}})
    def test_tray_exit_stops_exact_child(self, _port):
        with mock.patch('desktop.processes.state_dir', return_value=self.path / 'logs'):
            manager = BackendManager(self.path, system='Linux')
            manager.ensure_running()
            self.assertTrue(wait_for(lambda: (self.path / 'running-pid').exists()))
            pid = int((self.path / 'running-pid').read_text())
            manager.stop()
            self.assertTrue(wait_for(lambda: (self.path / 'stopped').exists()))
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    @mock.patch('desktop.processes.port_open', return_value=False)
    @mock.patch('desktop.processes.SERVICES', {'codex': {'port': 3789}})
    def test_parent_crash_stops_child_on_pipe_eof(self, _port):
        with mock.patch('desktop.processes.state_dir', return_value=self.path / 'logs'):
            manager = BackendManager(self.path, system='Linux')
            manager.ensure_running()
            self.assertTrue(wait_for(lambda: (self.path / 'running-pid').exists()))
            child = manager.children['codex']
            # Closing the tray-owned pipe without a stop command simulates
            # an abruptly crashed tray process; the supervisor must stop.
            child.stdin.close()
            child.wait(timeout=4)
            self.assertTrue(wait_for(lambda: (self.path / 'stopped').exists()))
            manager.children.clear()

    def test_bash_wsl_runner_pipe_protocol(self):
        # Simulates exact bash/WSL wrapper under Linux (without calling wsl.exe).
        shutil.copyfile(ROOT / 'desktop' / 'managed-wsl.sh', self.path / 'desktop' / 'managed-wsl.sh')
        env = dict(os.environ)
        env['XDG_STATE_HOME'] = str(self.path / 'logs')
        process = subprocess.Popen(['bash', '-i', './desktop/managed-wsl.sh', 'codex'],
                                   cwd=self.path, stdin=subprocess.PIPE,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        try:
            self.assertTrue(wait_for(lambda: (self.path / 'running-pid').exists()))
            process.stdin.write(b'stop\n')
            process.stdin.flush()
            process.stdin.close()
            process.wait(timeout=4)
            self.assertEqual(process.returncode, 0)
            self.assertTrue(wait_for(lambda: (self.path / 'stopped').exists()))
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
