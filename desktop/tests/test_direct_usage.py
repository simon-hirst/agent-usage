"""Tests for no-bridge Gemini / Copilot readers and quota normalisation."""
import json
import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from desktop.direct_usage import (parse_gemini_quota, parse_copilot_quota, read_copilot,
                                  ReaderError, run)
from desktop.providers import normalize_direct_result
from desktop.core import PROVIDERS, USAGE_PAGES
from desktop.providers import parse_direct_output


class DirectUsageTests(unittest.TestCase):
    def test_gemini_model_quotas_no_fake_5h(self):
        data = normalize_direct_result('gemini', parse_gemini_quota({'buckets': [
            {'modelId': 'gemini-3.1-pro', 'remainingFraction': .24,
             'resetTime': '2026-10-26T19:00:00Z'},
            {'modelId': 'gemini-3.5-flash', 'remainingFraction': 1},
            {'modelId': 'bad', 'remainingFraction': 120},
        ]}))
        self.assertIsNone(data['five_hour'])
        self.assertIsNone(data['weekly'])
        self.assertEqual(len(data['model_quotas']), 2)
        self.assertEqual(data['model_quotas'][0]['remaining_percent'], 24)
        self.assertEqual(data['model_quotas'][1]['remaining_percent'], 100)

    def test_copilot_monthly_not_five_hour(self):
        data = normalize_direct_result('copilot', parse_copilot_quota({
            'quota_reset_date_utc': '2026-11-01T00:00:00Z',
            'quota_snapshots': {'premium_interactions': {
                'entitlement': 300, 'percent_remaining': 55.5
            }}
        }))
        self.assertEqual(data['monthly']['remaining_percent'], 55.5)
        self.assertIsNone(data['five_hour'])
        self.assertIsNone(data['weekly'])

    def test_invalid_quota_rejected(self):
        with self.assertRaises(ReaderError):
            parse_gemini_quota({'buckets': [{'modelId': 'foo', 'remainingFraction': 1.2}]})
        with self.assertRaises(ReaderError):
            parse_copilot_quota({'quota_snapshots': {'foo': {'percent_remaining': 900}}})
        with self.assertRaises(ValueError):
            normalize_direct_result('gemini', {'ok': False, 'error': 'bad'})

    def test_copilot_gh_token_not_logged(self):
        class Completed:
            returncode = 0
            stdout = 'super-secret-gh-token\n'
        with patch('desktop.direct_usage.subprocess.run', return_value=Completed()) as subprocess_mock:
            with patch('desktop.direct_usage.fetch_json', return_value={
                'quota_snapshots': {'premium_interactions': {'percent_remaining': 45}}}):
                result = read_copilot()
            self.assertEqual(result['monthly']['remaining_percent'], 45)
            subprocess_mock.assert_called_once()
            self.assertNotIn('super-secret', json.dumps(result))

    def test_unsupported_providers_use_account_page_not_fake_number(self):
        for name in ('grok', 'cursor', 'windsurf', 'qwen', 'perplexity'):
            self.assertEqual(PROVIDERS[name]['source'], 'dashboard')
            self.assertTrue(USAGE_PAGES[name].startswith('https://'))
        for name in ('gemini', 'copilot'):
            self.assertEqual(PROVIDERS[name]['source'], 'direct')

    def test_wsl_shell_banners_do_not_break_json(self):
        output = b'Welcome to Debian\n\n{\"ok\":true,\"model_quotas\":[]}\n'
        self.assertTrue(parse_direct_output(output)['ok'])

    def test_bundled_output_file_mode(self):
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / 'quota.json'
            completed = subprocess.run([sys.executable, '-m', 'desktop.bundled_entry',
                                        '--direct-usage', 'verify-no-login', '--output', str(out)],
                                       cwd=ROOT, capture_output=True, text=True, timeout=10)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(json.loads(out.read_text())['ok'])

    def test_binary_mode_emits_valid_error_json(self):
        import io
        from contextlib import redirect_stdout
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run('verify-no-login'), 0)
        self.assertFalse(json.loads(out.getvalue())['ok'])


if __name__ == '__main__':
    unittest.main()
