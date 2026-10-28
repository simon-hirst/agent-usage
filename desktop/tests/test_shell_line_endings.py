"""Prevent Windows Git checkout from breaking the WSL backend launchers."""
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.build_release import validate_wsl_shell_sources


class ShellLineEndingsTests(unittest.TestCase):
    def test_wsl_scripts_have_lf_only(self):
        files = [ROOT / "desktop/managed-wsl.sh", ROOT / "desktop/direct-usage.sh"]
        validate_wsl_shell_sources(files)
        for path in files:
            raw = path.read_bytes()
            self.assertTrue(raw.startswith(b"#!/usr/bin/env bash\n"))
            self.assertNotIn(b"\r", raw, f"{path} has CRLF line endings")

    def test_attributes_enforce_lf_for_every_shell_script(self):
        rules = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("*.sh text eol=lf", rules)

    def test_release_builder_rejects_crlf(self):
        with tempfile.TemporaryDirectory() as folder:
            script = pathlib.Path(folder) / "script.sh"
            script.write_bytes(b"#!/bin/bash\r\nset -e\r\n")
            with self.assertRaisesRegex(RuntimeError, "CRLF"):
                validate_wsl_shell_sources([script])
            script.write_bytes(b"#!/bin/bash\nset -e\n")
            validate_wsl_shell_sources([script])


if __name__ == "__main__":
    unittest.main()
