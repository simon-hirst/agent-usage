import json
import pathlib
import sys
import threading
import time
import unittest
from urllib.request import urlopen

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server import CodexRpc, UsageCache, UsageHTTPServer, normalize_rate_limits


class TestNormalizer(unittest.TestCase):
    def test_weekly_in_primary_and_five_hour_in_secondary(self):
        data = normalize_rate_limits({
            'rateLimits': {
                'limitId': 'codex',
                'primary': {'usedPercent': 20, 'windowDurationMins': 10080, 'resetsAt': 1800000000},
                'secondary': {'usedPercent': 55, 'windowDurationMins': 300, 'resetsAt': 1790000000},
            }
        })
        self.assertEqual(data['weekly']['remaining_percent'], 80)
        self.assertEqual(data['five_hour']['remaining_percent'], 45)

    def test_missing_five_hour_is_null(self):
        data = normalize_rate_limits({'rateLimits': {
            'limitId': 'codex', 'primary': {'usedPercent': 4.2, 'windowDurationMins': 10080}
        }})
        self.assertIsNone(data['five_hour'])
        self.assertEqual(data['weekly']['used_percent'], 4.2)

    def test_nonstandard_window_is_not_labeled_five_hour(self):
        data = normalize_rate_limits({'rateLimits': {
            'limitId': 'codex', 'primary': {'usedPercent': 10, 'windowDurationMins': 15}
        }})
        self.assertIsNone(data['five_hour'])
        self.assertIsNone(data['weekly'])
        self.assertEqual(data['buckets']['codex']['other_windows'][0]['duration_minutes'], 15)

    def test_empty_quota_fails(self):
        with self.assertRaisesRegex(ValueError, 'no usable'):
            normalize_rate_limits({'rateLimits': {'limitId': 'codex'}})


class TestEndToEnd(unittest.TestCase):
    def test_json_rpc_and_real_http_get(self):
        fake = ROOT / 'tests' / 'fake_codex.py'
        client = CodexRpc([sys.executable, '-u', str(fake)], timeout=3)
        cache = UsageCache(client, interval=60)
        try:
            cache.refresh()
            with UsageHTTPServer(('127.0.0.1', 0), cache, None) as server:
                t = threading.Thread(target=server.serve_forever, daemon=True)
                t.start()
                port = server.server_address[1]
                with urlopen(f'http://127.0.0.1:{port}/get', timeout=3) as resp:
                    result = json.load(resp)
                    self.assertEqual(resp.status, 200)
                self.assertTrue(result['ok'])
                self.assertEqual(result['plan'], 'plus')
                self.assertEqual(result['five_hour']['used_percent'], 66.6)
                self.assertEqual(result['weekly']['used_percent'], 33.3)
                self.assertEqual(result['reset_credits_available'], 2)
                self.assertEqual(result['buckets']['codex_other']['other_windows'][0]['duration_minutes'], 120)
                self.assertNotIn('access_token', json.dumps(result))
                with urlopen(f'http://127.0.0.1:{port}/health', timeout=3) as resp:
                    self.assertTrue(json.load(resp)['healthy'])
                server.shutdown()
                t.join(3)
        finally:
            client.close()

    def test_stale_after_failed_refresh(self):
        fake = ROOT / 'tests' / 'fake_codex.py'
        client = CodexRpc([sys.executable, '-u', str(fake)], timeout=3)
        cache = UsageCache(client, interval=60)
        try:
            cache.refresh()
            client.command = ['/not/installed/codex', 'app-server']
            client.close()
            cache.refresh()
            value, status = cache.get()
            self.assertEqual(status, 200)
            self.assertTrue(value['stale'])
            self.assertFalse(value['ok'])
            self.assertIsNotNone(value['weekly'])
            self.assertIsNotNone(value['error'])
        finally:
            client.close()


if __name__ == '__main__':
    unittest.main()
