import json
import os
from unittest import mock
import pathlib
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server import (
    ClaudeUsageClient, LocalServer, RateLimited, UsageCache, UsageError,
    normalize, parse_timestamp, parse_window, public_snapshot, read_retry_after, read_credentials,
)


class NormalizerTests(unittest.TestCase):
    def test_basic_quotas_and_models(self):
        data = normalize({
            'five_hour': {'utilization': 42.4, 'resets_at': '2026-10-25T22:00:00Z'},
            'seven_day': {'utilization': 26.5, 'resets_at': '2026-10-30T10:00:00+00:00'},
            'seven_day_sonnet': {'utilization': 75, 'resets_at': None},
            'seven_day_opus': None,
            'extra_usage': {'is_enabled': True, 'used_credits': 700, 'monthly_limit': 5000},
            'limits': [{'kind': 'weekly_scoped', 'group': 'weekly', 'percent': 15,
                        'resets_at': '2026-10-31T00:00:00Z',
                        'scope': {'model': {'display_name': 'Fable'}}}],
        })
        self.assertEqual(data['five_hour']['used_percent'], 42.4)
        self.assertEqual(data['weekly']['remaining_percent'], 73.5)
        self.assertEqual(data['additional_limits']['seven_day_sonnet']['remaining_percent'], 25)
        self.assertNotIn('seven_day_opus', data['additional_limits'])
        self.assertEqual(data['scoped_limits'][0]['model'], 'Fable')
        self.assertEqual(data['extra_usage']['used_credits'], 700)
        self.assertIn('resets_in_seconds', public_snapshot(data, time.time())['weekly'])

    def test_missing_five_hour_is_null_not_guessed(self):
        data = normalize({'seven_day': {'utilization': 12, 'resets_at': None}})
        self.assertIsNone(data['five_hour'])
        self.assertEqual(data['weekly']['used_percent'], 12)

    def test_fraction_option(self):
        self.assertEqual(normalize({'five_hour': {'utilization': 0.42}}, 'fraction')
                         ['five_hour']['used_percent'], 42)
        self.assertEqual(normalize({'five_hour': {'utilization': 0.42}}, 'percent')
                         ['five_hour']['used_percent'], 0.42)

    def test_reject_bad_units_and_bool(self):
        with self.assertRaises(ValueError):
            normalize({'five_hour': {'utilization': 142}})
        with self.assertRaisesRegex(ValueError, 'no quota'):
            normalize({'five_hour': {'utilization': True}, 'extra_usage': {'is_enabled': True}})

    def test_timestamp_numeric_and_iso(self):
        self.assertEqual(parse_timestamp(1780000000000), 1780000000)
        self.assertEqual(parse_timestamp('2026-10-25T19:00:00Z'), 1792954800)
        self.assertIsNone(parse_timestamp('garbage'))
        self.assertEqual(read_retry_after('360', time.time()), 360)
        self.assertIsNone(read_retry_after('0', time.time()))


class FakeUpstream(BaseHTTPRequestHandler):
    rate_limited = False
    seen_auth = []

    def do_GET(self):
        type(self).seen_auth.append(self.headers.get('Authorization'))
        if type(self).rate_limited:
            self.send_response(429)
            self.send_header('Retry-After', '600')
            self.end_headers()
            self.wfile.write(b'{"error":"rate_limited"}')
        else:
            data = json.dumps({
                'five_hour': {'utilization': 66.6, 'resets_at': '2026-10-25T22:00:00Z'},
                'seven_day': {'utilization': 33.3, 'resets_at': '2026-10-30T10:00:00Z'},
                'seven_day_sonnet': {'utilization': 9.3, 'resets_at': None},
            }).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    def log_message(self, *args):
        pass


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.credentials = pathlib.Path(self.tmpdir.name) / '.credentials.json'
        self.credentials.write_text(json.dumps({'claudeAiOauth': {'accessToken': 'SECRET_TEST_TOKEN',
                                                               'expiresAt': int((time.time() + 3600) * 1000)}}))
        FakeUpstream.rate_limited = False
        FakeUpstream.seen_auth = []
        self.upstream = ThreadingHTTPServer(('127.0.0.1', 0), FakeUpstream)
        self.thread = threading.Thread(target=self.upstream.serve_forever, daemon=True)
        self.thread.start()
        self.client = ClaudeUsageClient(self.credentials, endpoint=f'http://127.0.0.1:{self.upstream.server_address[1]}')

    def tearDown(self):
        self.upstream.shutdown()
        self.thread.join(3)
        self.upstream.server_close()
        self.tmpdir.cleanup()

    def test_upstream_and_real_get_endpoint(self):
        cache = UsageCache(self.client, 60)
        self.assertTrue(cache.refresh())
        with LocalServer(('127.0.0.1', 0), cache, None) as httpd:
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            endpoint = f'http://127.0.0.1:{httpd.server_address[1]}'
            with urlopen(endpoint + '/get', timeout=3) as resp:
                self.assertEqual(resp.status, 200)
                result = json.load(resp)
            self.assertTrue(result['ok'])
            self.assertEqual(result['five_hour']['used_percent'], 66.6)
            self.assertEqual(result['weekly']['remaining_percent'], 66.7)
            self.assertIn('seven_day_sonnet', result['additional_limits'])
            self.assertEqual(FakeUpstream.seen_auth, ['Bearer SECRET_TEST_TOKEN'])
            self.assertNotIn('SECRET_TEST_TOKEN', json.dumps(result))
            with urlopen(endpoint + '/health', timeout=3) as resp:
                self.assertTrue(json.load(resp)['healthy'])
            with self.assertRaises(HTTPError) as err:
                urlopen(Request(endpoint + '/get', headers={'Host': 'evil.example'}), timeout=3)
            self.assertEqual(err.exception.code, 403)
            httpd.shutdown()
            thread.join(3)

    def test_429_respects_backoff_and_keeps_cached_value(self):
        cache = UsageCache(self.client, 60)
        self.assertTrue(cache.refresh())
        FakeUpstream.rate_limited = True
        cache.next_poll = 0
        self.assertFalse(cache.refresh())
        result, status = cache.get()
        self.assertEqual(status, 200)
        self.assertTrue(result['stale'])
        self.assertFalse(result['ok'])
        self.assertEqual(result['five_hour']['used_percent'], 66.6)
        self.assertIn('429', result['error'])
        self.assertGreaterEqual(cache.next_poll - time.time(), 899)
        n = len(FakeUpstream.seen_auth)
        cache.refresh()
        self.assertEqual(n, len(FakeUpstream.seen_auth))

    def test_failed_refresh_is_stale_when_timestamps_are_equal(self):
        # Windows ARM runners can timestamp two refreshes identically. The
        # failed refresh must still invalidate the previously cached reading.
        cache = UsageCache(self.client, 60)
        self.assertTrue(cache.refresh())
        FakeUpstream.rate_limited = True
        cache.next_poll = 0
        self.assertFalse(cache.refresh())
        with cache.lock:
            cache.failed_at = cache.updated_at
        result, status = cache.get()
        self.assertEqual(status, 200)
        self.assertTrue(result['stale'])
        self.assertFalse(result['ok'])
        self.assertEqual(result['five_hour']['used_percent'], 66.6)
        self.assertIn('429', result['error'])

        # A subsequent successful poll restores freshness.
        FakeUpstream.rate_limited = False
        cache.next_poll = 0
        self.assertTrue(cache.refresh())
        result, status = cache.get()
        self.assertEqual(status, 200)
        self.assertTrue(result['ok'])
        self.assertFalse(result['stale'])

    def test_initial_429_returns_503(self):
        FakeUpstream.rate_limited = True
        cache = UsageCache(self.client)
        self.assertFalse(cache.refresh())
        result, status = cache.get()
        self.assertEqual(status, 503)
        self.assertIsNone(result['five_hour'])
        self.assertIn('429', result['error'])

    def test_missing_and_expired_tokens_never_contact_server(self):
        self.credentials.unlink()
        with self.assertRaises(UsageError):
            self.client.fetch()
        self.credentials.write_text(json.dumps({'claudeAiOauth': {'accessToken': 'EXPIRED_SECRET',
                                                               'expiresAt': int((time.time() - 90) * 1000)}}))
        with self.assertRaisesRegex(UsageError, 'expired'):
            self.client.fetch()
        self.assertEqual(FakeUpstream.seen_auth, [])


if __name__ == '__main__':
    unittest.main()


class PortableCredentialsTests(unittest.TestCase):
    def test_linux_fallback_reads_existing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / '.credentials.json'
            path.write_text(json.dumps({'claudeAiOauth': {'accessToken': 'private-secret'}}))
            with mock.patch('server.platform.system', return_value='Linux'):
                result = read_credentials(path)
            self.assertEqual(result['claudeAiOauth']['accessToken'], 'private-secret')

    def test_mac_keychain_and_does_not_log_token(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / '.credentials.json'
            completed = mock.Mock(returncode=0, stdout=b'{"claudeAiOauth":{"accessToken":"secret"}}')
            with mock.patch('server.platform.system', return_value='Darwin'), \
                 mock.patch('server.subprocess.run', return_value=completed) as run, \
                 mock.patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(pathlib.Path.home() / '.claude')}):
                result = read_credentials(path)
            self.assertEqual(result['claudeAiOauth']['accessToken'], 'secret')
            self.assertEqual(run.call_args.args[0][0:4], ['/usr/bin/security','find-generic-password','-s','Claude Code-credentials'])
            self.assertNotIn('secret', str(run.call_args))
