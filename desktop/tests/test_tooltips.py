"""Reset timestamps in tray hover text must reflect the computer's local time."""
import datetime as dt
import pathlib
import sys
import unittest
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from desktop.tooltips import (MAX_TRAY_TOOLTIP, individual_tooltip,
                              local_reset_time, merged_tooltip)


class TooltipTests(unittest.TestCase):
    def setUp(self):
        self.utc = dt.timezone.utc
        self.snapshots = {
            "codex": {
                "ok": True,
                "five_hour": {"remaining_percent": 72, "resets_at": "2026-10-26T17:30:00Z"},
                "weekly": {"remaining_percent": 48, "resets_at": "2026-10-30T22:00:00+00:00"},
            },
            "claude": {
                "ok": True,
                "five_hour": {"remaining_percent": 36, "resets_at": "2026-10-26T21:00:00Z"},
                "weekly": {"remaining_percent": 81, "resets_at": "2026-11-01T09:00:00Z"},
            },
        }

    def test_timezone_converts_and_handles_uk_dst(self):
        try:
            london = ZoneInfo("Europe/London")
        except ZoneInfoNotFoundError:
            self.skipTest("IANA timezone database unavailable (e.g. bare Windows Python)")
        # BST until the clocks return to GMT on 25 October 2026.
        self.assertEqual(local_reset_time("2026-10-24T23:30:00Z", timezone=london),
                         "Sun 25 Oct 00:30")
        self.assertEqual(local_reset_time("2026-10-25T02:30:00Z", timezone=london),
                         "Sun 25 Oct 02:30")
        self.assertEqual(local_reset_time("2026-10-25T02:30:00+02:00", timezone=self.utc),
                         "Sun 25 Oct 00:30")

    def test_fixed_timezone_conversion_without_tzdata(self):
        bst = dt.timezone(dt.timedelta(hours=1))
        self.assertEqual(local_reset_time("2026-10-24T23:30:00Z", timezone=bst),
                         "Sun 25 Oct 00:30")
        self.assertEqual(local_reset_time("2026-10-25T02:30:00Z", timezone=self.utc),
                         "Sun 25 Oct 02:30")

    def test_invalid_or_naive_timestamps_not_guessed(self):
        for raw in (None, "", "not-a-date", "2026-10-26T17:30:00", {}, 12):
            self.assertIsNone(local_reset_time(raw))

    def test_individual_hover_shows_both_reset_dates_and_percentages(self):
        tooltip = individual_tooltip("codex", self.snapshots["codex"], timezone=self.utc)
        self.assertIn("Codex (local time)", tooltip)
        self.assertIn("5h: 72% left; reset Mon 26 Oct 17:30", tooltip)
        self.assertIn("7d: 48% left; reset Fri 30 Oct 22:00", tooltip)
        self.assertLessEqual(len(tooltip), MAX_TRAY_TOOLTIP)
        # Weekly icons use the same complete hover text, not just weekly data.

    def test_missing_resets_display_unknown_not_an_estimate(self):
        snapshot = {"ok": True, "five_hour": {"remaining_percent": 19, "resets_at": None}, "weekly": None}
        tip = individual_tooltip("claude", snapshot, timezone=self.utc)
        self.assertIn("5h: 19% left; reset unknown", tip)
        self.assertIn("7d: not available", tip)
        self.assertIn("unavailable", individual_tooltip("claude", {"ok": False, "error": "Offline"}).lower())

    def test_cached_claude_remains_visible_but_is_marked_stale(self):
        snap = {
            "ok": True, "stale": True, "last_updated_at": "2026-10-28T10:05:00Z",
            "five_hour": {"remaining_percent": 63, "resets_at": "2026-10-28T13:00:00Z"},
            "weekly": {"remaining_percent": 35, "resets_at": "2026-11-01T20:00:00Z"},
        }
        tip = individual_tooltip("claude", snap, timezone=self.utc)
        self.assertIn("cached, not live", tip)
        self.assertIn("5h: 63%; reset 28 Oct 13:00", tip)
        self.assertIn("7d: 35%; reset 01 Nov 20:00", tip)
        self.assertIn("Seen 28 Oct 10:05", tip)
        self.assertLessEqual(len(tip), MAX_TRAY_TOOLTIP)
        merged = merged_tooltip(["claude"], {"claude": snap}, timezone=self.utc)
        self.assertIn("Claude (cached): 5h 63% left / 7d 35% left", merged)

    def test_balance_only_has_no_invented_reset_time(self):
        tip = individual_tooltip("deepseek", {"ok": True, "balance_text": "USD 5.50"})
        self.assertIn("USD 5.50", tip)
        self.assertIn("No timed quota reset available", tip)

    def test_merged_hover_shows_selected_providers_and_both_resets(self):
        tip = merged_tooltip(["codex", "claude"], self.snapshots, timezone=self.utc)
        self.assertIn("Reset times (local)", tip)
        self.assertIn("Codex: 5h 26 Oct 17:30 / 7d 30 Oct 22:00", tip)
        self.assertIn("Claude: 5h 26 Oct 21:00 / 7d 01 Nov 09:00", tip)
        self.assertLessEqual(len(tip), MAX_TRAY_TOOLTIP)

    def test_merged_hover_handles_many_providers_without_cutting_dates(self):
        names = ["codex", "claude", "muse", "kimi", "grok", "gemini", "cursor", "perplexity"]
        tip = merged_tooltip(names, self.snapshots, timezone=self.utc)
        self.assertLessEqual(len(tip), MAX_TRAY_TOOLTIP)
        self.assertIn("more; click for quick view", tip)
        self.assertNotIn("Grok:", tip)
        # Offline snapshots never re-use cached reset timestamps.
        tip = merged_tooltip(["codex"], {"codex": {"ok": False, "five_hour": self.snapshots["codex"]["five_hour"]}})
        self.assertIn("Codex: unavailable", tip)
        self.assertNotIn("17:30", tip)

    def test_short_limit_preserves_complete_fallback(self):
        tip = merged_tooltip(["codex", "claude"], self.snapshots, max_chars=55, timezone=self.utc)
        self.assertLessEqual(len(tip), 55)
        self.assertIn("click for quick view", tip)


if __name__ == "__main__":
    unittest.main()
