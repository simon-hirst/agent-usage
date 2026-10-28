"""Claude last-successful reading must be retained but clearly marked stale."""
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from desktop.claude_cache import ClaudeLastKnown


class ClaudeCacheTests(unittest.TestCase):
    def test_failure_preserves_last_good_reading_and_recovers(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = ClaudeLastKnown(pathlib.Path(folder) / "claude.json")
            failed = {"ok": False, "error": "429 rate limited"}
            self.assertEqual(cache.apply(failed), failed)
            good = {"ok": True, "five_hour": {"remaining_percent": 73,
                       "resets_at": "2026-10-29T13:30:00Z"},
                    "weekly": {"remaining_percent": 42, "resets_at": None}}
            self.assertIs(cache.apply(good), good)
            cached = cache.apply(failed)
            self.assertTrue(cached["ok"])
            self.assertTrue(cached["stale"])
            self.assertEqual(cached["five_hour"]["remaining_percent"], 73)
            self.assertEqual(cached["weekly"]["remaining_percent"], 42)
            self.assertEqual(cached["error"], "429 rate limited")
            self.assertIsNotNone(cached["last_updated_at"])
            self.assertFalse(cache.apply({"ok": True, "weekly": {"remaining_percent": 80}}).get("stale", False))
            self.assertEqual(cache.apply(failed)["weekly"]["remaining_percent"], 80)
            self.assertIsNone(cache.apply(failed)["five_hour"])

    def test_survives_restart_and_stores_no_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "claude.json"
            c = ClaudeLastKnown(path)
            c.apply({"ok": True, "five_hour": {"remaining_percent": 30, "resets_at": None},
                     "secret_token": "DO_NOT_WRITE", "extra": "private"})
            self.assertNotIn("DO_NOT_WRITE", path.read_text())
            restarted = ClaudeLastKnown(path)
            fallback = restarted.fallback("offline")
            self.assertTrue(fallback["stale"])
            self.assertEqual(fallback["five_hour"]["remaining_percent"], 30)

    def test_rejects_corrupt_invalid_or_out_of_range_snapshots(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "claude.json"
            path.write_text("this is not json")
            self.assertIsNone(ClaudeLastKnown(path).fallback("offline"))
            path.write_text(json.dumps({"saved_at": "2026-10-28T12:00:00Z",
                "snapshot": {"five_hour": {"remaining_percent": 110},
                             "weekly": {"remaining_percent": True}}}))
            self.assertIsNone(ClaudeLastKnown(path).fallback("offline"))

    def test_stale_upstream_result_never_overwrites_fresh_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = ClaudeLastKnown(pathlib.Path(folder) / "claude.json")
            cache.apply({"ok": True, "five_hour": {"remaining_percent": 55}})
            result = cache.apply({"ok": False, "stale": True, "error": "offline",
                                  "five_hour": {"remaining_percent": 99}})
            self.assertEqual(result["five_hour"]["remaining_percent"], 55)
            self.assertTrue(result["stale"])


if __name__ == "__main__":
    unittest.main()
