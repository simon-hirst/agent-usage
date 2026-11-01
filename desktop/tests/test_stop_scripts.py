"""Stop commands must only terminate this tray, never unrelated Python jobs."""
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]


class StopScriptsTests(unittest.TestCase):
    def test_launcher_sources_and_line_endings(self):
        for path in ("stop-linux.sh", "stop-macos.sh"):
            content = (ROOT / path).read_bytes()
            self.assertTrue(content.startswith(b"#!/usr/bin/env bash\n"))
            self.assertNotIn(b"\r", content)
            self.assertIn(b"--backend-server", content)
        content = (ROOT / "stop-windows.ps1").read_text(encoding="utf-8")
        self.assertIn("Get-CimInstance Win32_Process", content)
        self.assertIn("Stop-Process -Id", content)
        self.assertNotIn("wsl.exe --shutdown", content)

    @unittest.skipUnless(platform.system() == "Linux", "Linux process-isolation test")
    def test_stops_only_matching_source_tray(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for folder in (root, root / "unrelated"):
                (folder / "desktop").mkdir(parents=True)
                (folder / "desktop" / "run_app.py").write_text("import time\ntime.sleep(60)\n")
            script = root / "stop-linux.sh"
            script.write_bytes((ROOT / "stop-linux.sh").read_bytes())
            owned = subprocess.Popen([sys.executable, str(root / 'desktop' / 'run_app.py')],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            other = subprocess.Popen([sys.executable, str(root / 'unrelated' / 'desktop' / 'run_app.py')],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                time.sleep(0.2)
                result = subprocess.run(['bash', str(script)], capture_output=True, text=True, timeout=12)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f'PID {owned.pid}', result.stdout)
                owned.wait(timeout=4)
                self.assertIsNone(other.poll(), 'Unrelated Python service must not be stopped')
                repeat = subprocess.run(['bash', str(script)], capture_output=True, text=True, timeout=12)
                self.assertEqual(repeat.returncode, 0)
                self.assertIn('not running', repeat.stdout)
            finally:
                for proc in (owned, other):
                    if proc.poll() is None:
                        proc.kill()
                    proc.wait(timeout=4)


if __name__ == "__main__":
    unittest.main()
