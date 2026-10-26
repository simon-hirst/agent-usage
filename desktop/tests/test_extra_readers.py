"""Fixtures validate read-only integrations without exposing user sessions."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from desktop.extra_readers import (
    parse_cursor, parse_grok_billing, parse_windsurf_cache,
    parse_perplexity_credits, parse_qwen_usage, read_sqlite_item,
    _get_json, ProviderError, _iso, _grok_token)
from desktop.providers import normalize_direct_result

class Tests(unittest.TestCase):
    def test_cursor_monthly_usage(self):
        result = normalize_direct_result('cursor', parse_cursor({
            'billingCycleEnd':'2026-11-01T00:00:00Z',
            'individualUsage': {'plan': {'totalPercentUsed': 62.5}}
        }))
        self.assertEqual(result['monthly']['remaining_percent'],37.5)
        self.assertIsNone(result['five_hour'])

    def test_cursor_missing_usage_is_not_zero(self):
        with self.assertRaises(ProviderError):
            parse_cursor({'individualUsage':{'plan':{'remaining':0}}})

    def test_grok_current_cli_auth_file_and_expiry(self):
        data = {'https://auth.x.ai::grok-client': {
            'key': 'test-only-bearer', 'expires_at': 4102444800,
            'auth_mode': 'oidc'}}
        self.assertEqual(_grok_token(data), 'test-only-bearer')
        data['https://auth.x.ai::grok-client']['expires_at'] = 10
        self.assertIsNone(_grok_token(data))

    def test_grok_unknown_billing_duration_is_credit_not_weekly(self):
        data = parse_grok_billing({'config': {'creditUsagePercent': 22.5}})
        self.assertIsNone(data.get('weekly'))
        self.assertEqual(data['credit_percent'], 77.5)

    def test_grok_weekly_window_with_reset(self):
        result = parse_grok_billing({'config': {'creditUsagePercent':41,
            'currentPeriod':{'start':1792530000,'end':1793134800}}})
        self.assertEqual(result['weekly']['remaining_percent'], 59)
        self.assertTrue(result['weekly']['resets_at'])

    def test_grok_wallet_not_fabricated_percent(self):
        result = parse_grok_billing({'config': {'prepaidBalance': {'val':16}}})
        self.assertIsNone(result.get('weekly'))
        self.assertIn('16',result['balance_text'])

    def test_windsurf_daily_and_weekly_fields(self):
        result = normalize_direct_result('windsurf',parse_windsurf_cache({
            'quotaUsage': {'dailyRemainingPercent':25,'weeklyRemainingPercent':70,
                'weeklyResetAtUnix':1793000000}}))
        self.assertEqual(result['daily']['remaining_percent'],25)
        self.assertEqual(result['weekly']['remaining_percent'],70)
        self.assertIsNotNone(result['weekly']['resets_at'])

    def test_windsurf_old_counts_not_mislabeled_weekly(self):
        result = parse_windsurf_cache({'usage': {'messages':100,'usedMessages':40}})
        self.assertIsNone(result['weekly'])
        self.assertEqual(result['model_quotas'][0]['remaining_percent'],60)

    def test_perplexity_recurring_credits(self):
        result = normalize_direct_result('perplexity', parse_perplexity_credits({
            'total_usage_cents': 700, 'renewal_date_ts':1793000000,
            'credit_grants':[{'type':'recurring','amount_cents':2000}]
        }))
        self.assertEqual(result['credit_percent'], 65)
        self.assertTrue(result['credit_resets_at'])
        self.assertIsNone(result['weekly'])

    def test_qwen_explicit_windows(self):
        result = normalize_direct_result('qwen',parse_qwen_usage({
            'response':{'usage':{'fiveHour':{'usedPercent':55,'resetAt':1793000000},
                'weekly': {'remainingPercent':65}}}}))
        self.assertEqual(result['five_hour']['remaining_percent'],45)
        self.assertEqual(result['weekly']['remaining_percent'],65)

    def test_qwen_unrelated_total_not_made_into_quota(self):
        with self.assertRaises(ProviderError):
            parse_qwen_usage({'data':{'total':2000,'used':1000}})

    def test_browser_cookie_subdomain_scoping(self):
        import types
        import desktop.extra_readers as ext
        class Cookie:
            def __init__(self,name,value,domain):
                self.name, self.value, self.domain=name,value,domain
        fake=types.SimpleNamespace(chrome=lambda domain_name: [
            Cookie('authjs.session-token','t','www.perplexity.ai'),
            Cookie('unrelated','secret','other.example')])
        with patch.dict(sys.modules, {'browser_cookie3':fake}):
            data=ext.browser_cookie('perplexity.ai', {'authjs.session-token'})
        self.assertIn('authjs.session-token=t',data)
        self.assertNotIn('unrelated',data)

    def test_read_only_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'state.vscdb'
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE ItemTable (key TEXT, value TEXT)')
                db.execute('INSERT INTO ItemTable VALUES (?, ?)', ('cursorAuth/accessToken','fake'))
                db.commit()
            self.assertEqual(read_sqlite_item(path,'cursorAuth/accessToken'),'fake')
            # tempfile cleanup is now safe on Windows: both connections close.

    def test_read_sqlite_item_closes_connection(self):
        """Catch leaked DB handles even on Linux where unlinking is allowed."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.vscdb'
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE ItemTable (key TEXT, value TEXT)')
                db.execute('INSERT INTO ItemTable VALUES (?, ?)', ('test', 'value'))
                db.commit()
            captured = []
            real_connect = sqlite3.connect

            def tracking_connect(*args, **kwargs):
                connection = real_connect(*args, **kwargs)
                captured.append(connection)
                return connection

            with patch('desktop.extra_readers.sqlite3.connect', side_effect=tracking_connect):
                self.assertEqual(read_sqlite_item(path, 'test'), 'value')
            self.assertEqual(len(captured), 1)
            with self.assertRaises(sqlite3.ProgrammingError):
                captured[0].execute('SELECT 1')

    def test_fixed_https_host_only(self):
        with self.assertRaises(ProviderError):
            _get_json('https://attacker.example/usage', {'Authorization':'Bearer secret'})

    def test_no_invalid_datetime_guess(self):
        self.assertIsNone(_iso('2026-10-27 12:00:00'))

if __name__ == '__main__': unittest.main()
