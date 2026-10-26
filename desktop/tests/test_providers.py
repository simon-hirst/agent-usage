import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from desktop.core import load_settings, save_settings
from desktop.providers import icon_number, is_local_url, normalize, parse_muse_usage


class ProviderAdapterTests(unittest.TestCase):
    def test_kimi_real_quota_response(self):
        data = normalize('kimi', {'data': {'kind': 'ok', 'quota': {
            'usages': {'limit5h': {'usedRatio': .65, 'resetAt': '2026-10-27T11:00:00Z'},
                       'limit7d': {'usedRatio': .10}, 'monthTotal': {'usedRatio': .8}},
            'extraUsage': {'balanceCents': 1275, 'currency': 'USD'}}}})
        self.assertAlmostEqual(data['five_hour']['remaining_percent'], 35)
        self.assertAlmostEqual(data['weekly']['remaining_percent'], 90)
        self.assertAlmostEqual(data['monthly']['remaining_percent'], 20)
        self.assertEqual(data['balance_text'], 'USD 12.75 extra')

    def test_kimi_plan_without_weekly_quota(self):
        data = normalize('kimi', {'data': {'kind': 'ok', 'quota': {'usages': {'limit5h': {'usedRatio': .4}}}}})
        self.assertIsNone(data['weekly'])
        self.assertEqual(icon_number(data), '60')

    def test_deepseek_balance_not_fake_percent(self):
        data = normalize('deepseek', {'is_available': True, 'balance_infos': [
            {'currency': 'CNY', 'total_balance': '100.50'}]})
        self.assertEqual(data['balance_text'], 'CNY 100.50')
        self.assertIsNone(data['five_hour'])
        self.assertEqual(icon_number(data), '--')

    def test_openrouter_credits(self):
        data = normalize('openrouter', {'data': {'total_credits': 200, 'total_usage': 50}})
        self.assertEqual(data['balance_text'], 'USD 150.00 credits')
        self.assertEqual(data['credit_percent'], 75)
        self.assertEqual(icon_number(data), '--')

    def test_bridge_preserves_labels_and_skips_invalid(self):
        data = normalize('grok', {'ok': True,
             'five_hour': {'used_percent': 35, 'resets_at': '2026-10-27T12:00:00Z'},
             'weekly': {'remaining_percent': 250}})
        self.assertEqual(data['five_hour']['remaining_percent'], 65)
        self.assertIsNone(data['weekly'])
        with self.assertRaises(ValueError):
            normalize('grok', {'ok': True, 'stale': True, 'weekly': {'remaining_percent': 10}})

    def test_local_urls_only(self):
        self.assertTrue(is_local_url('http://127.0.0.1:8888/get'))
        self.assertFalse(is_local_url('https://attacker.example:8888/'))
        self.assertFalse(is_local_url('http://localhost:8888@evil.example/get'))
        self.assertFalse(is_local_url('file:///etc/passwd'))

    def test_muse_cli_percentage(self):
        text = '\x1b[33m5-hour: 45% used\x1b[0m\nWeekly: 70% remaining'
        snap = parse_muse_usage(text)
        self.assertEqual(snap['five_hour']['remaining_percent'], 55)
        self.assertEqual(snap['weekly']['remaining_percent'], 70)
        with self.assertRaises(ValueError):
            parse_muse_usage('1000 tokens used total')

    def test_provider_settings_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = pathlib.Path(temp) / 'settings.json'
            original = load_settings(path)
            self.assertFalse(original['setup_complete'])
            original.update({'selected_providers': ['muse', 'kimi', 'grok'], 'merged_icon': True,
                             'setup_complete': True, 'endpoints': {'grok': 'http://localhost:8888/get'}})
            save_settings(original, path)
            restored = load_settings(path)
            self.assertEqual(restored['selected_providers'], ['muse', 'kimi', 'grok'])
            self.assertTrue(restored['merged_icon'])
            self.assertTrue(restored['setup_complete'])
            self.assertEqual(restored['endpoints']['grok'], 'http://localhost:8888/get')


if __name__ == '__main__':
    unittest.main()
