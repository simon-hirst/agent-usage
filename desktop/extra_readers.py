"""Opt-in, read-only account quota readers. Never persist, log or return login secrets.

Only executed for providers explicitly selected by the user. Remote requests
are restricted to fixed provider HTTPS hosts, with no redirects to other hosts.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import math
import os
from pathlib import Path
import platform
import re
import sqlite3
import subprocess
import time
from urllib.parse import urlencode, quote
from urllib.request import Request, build_opener, HTTPHandler, HTTPSHandler, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
import uuid

class ProviderError(Exception):
    pass

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderError('Account endpoint redirected; sign in again')

_OPENER = build_opener(HTTPHandler(), HTTPSHandler(), NoRedirect())


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (ValueError, TypeError):
        return None


def _iso(value):
    if isinstance(value, str) and value:
        try:
            parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is not None:
                return parsed.isoformat()
        except ValueError:
            return None
    v = _number(value)
    if v and v > 1_000_000_000:
        try:
            return dt.datetime.fromtimestamp(v / (1000 if v > 1e12 else 1), dt.timezone.utc).isoformat()
        except (ValueError, OSError, OverflowError):
            pass
    return None


def _window_used(value, reset=None):
    v = _number(value)
    if v is None or v < 0 or v > 100:
        return None
    return {'remaining_percent': round(100-v, 3), 'resets_at': _iso(reset)}


def _window_left(value, reset=None):
    v = _number(value)
    if v is None or v < 0 or v > 100:
        return None
    return {'remaining_percent': round(v, 3), 'resets_at': _iso(reset)}


def _get_json(url, headers=None, payload=None, timeout=10):
    # Do not forward credentials in a redirect to a new hostname.
    if not url.startswith(('https://cursor.com/', 'https://www.perplexity.ai/',
                           'https://cli-chat-proxy.grok.com/', 'https://home.qwencloud.com/',
                           'https://cs-data.qwencloud.com/')):
        raise ProviderError('Unapproved provider endpoint')
    request = Request(url, data=payload, headers={
        'Accept': 'application/json', 'User-Agent': 'ProviderUsageTray/3.3', **(headers or {})},
        method='POST' if payload is not None else 'GET')
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            raw = response.read(524289)
    except HTTPError as exc:
        raise ProviderError(f'Provider HTTP {exc.code}; check account sign-in') from None
    except (URLError, TimeoutError) as exc:
        raise ProviderError('Provider unavailable or timed out') from None
    if len(raw) > 524288:
        raise ProviderError('Provider returned oversized data')
    try:
        return json.loads(raw)
    except (UnicodeError, ValueError):
        raise ProviderError('Provider returned invalid JSON') from None


def browser_cookie(domain, names=None):
    """Read cookies only for an explicitly selected provider, never store them."""
    try:
        import browser_cookie3
    except ImportError:
        raise ProviderError('Browser cookie reader missing from installation') from None
    for loader in ('chrome', 'edge', 'brave', 'firefox', 'chromium'):
        try:
            jar = getattr(browser_cookie3, loader)(domain_name=domain)
            values = [(c.name, c.value) for c in jar
                      if (c.domain.lstrip('.') == domain or c.domain.lstrip('.').endswith('.' + domain))
                      and (not names or c.name in names or any(c.name.startswith(n+'.') for n in names))]
            if values:
                return '; '.join(f'{k}={v}' for k, v in values)
        except Exception:
            continue
    raise ProviderError(f'No readable {domain} session; sign into the site in Chrome, Edge or Firefox')


def _session_cookie(domain, env_name, names=None):
    manual = os.environ.get(env_name, '').strip()
    if manual:
        return manual.removeprefix('Cookie:').strip()
    return browser_cookie(domain, names)


def _cursor_db_path():
    home = Path.home()
    system = platform.system()
    if system == 'Windows':
        return Path(os.environ.get('APPDATA', home/'AppData'/'Roaming'))/'Cursor/User/globalStorage/state.vscdb'
    if system == 'Darwin':
        return home/'Library/Application Support/Cursor/User/globalStorage/state.vscdb'
    xdg = os.environ.get('XDG_CONFIG_HOME')
    return (Path(xdg) if xdg and Path(xdg).is_absolute() else home/'.config')/'Cursor/User/globalStorage/state.vscdb'


def read_sqlite_item(path: Path, key: str):
    """Never modify the editor database. Respect live WAL journal state."""
    if not path.is_file():
        return None
    from urllib.parse import quote as urlquote
    uri = 'file:' + urlquote(str(path.resolve()), safe='/:') + '?mode=ro'
    try:
        with sqlite3.connect(uri, uri=True, timeout=2) as conn:
            row = conn.execute('SELECT value FROM ItemTable WHERE key = ?', (key,)).fetchone()
    except sqlite3.Error:
        return None
    if not row:
        return None
    value = row[0]
    if isinstance(value, bytes):
        if len(value) > 2 and value[1::2].count(0) >= len(value)//4:
            value = value.decode('utf-16le', 'replace')
        else:
            value = value.decode('utf-8', 'replace')
    return value


def parse_cursor(payload):
    if not isinstance(payload, dict):
        raise ProviderError('Cursor usage response invalid')
    plan = (payload.get('individualUsage') or {}).get('plan') or {}
    used = _number(plan.get('totalPercentUsed'))
    result = {'ok': True}
    monthly = _window_used(used, payload.get('billingCycleEnd'))
    if monthly:
        result['monthly'] = monthly
    if not monthly:
        raise ProviderError('Cursor did not expose an included-usage percentage')
    return result


def read_cursor():
    token = read_sqlite_item(_cursor_db_path(), 'cursorAuth/accessToken')
    headers = {}
    if token:
        token = token.strip().strip('"')
        if not token or len(token) > 16384:
            token = None
        if token:
            headers['Cookie'] = 'WorkosCursorSessionToken=' + quote(token, safe='')
    headers.update({'Origin': 'https://cursor.com', 'Referer': 'https://cursor.com/dashboard'})
    if token:
        try:
            result = parse_cursor(_get_json('https://cursor.com/api/usage-summary', headers))
        except ProviderError:
            # The editor token is not necessarily a website session cookie.
            # Fall back to an explicitly selected browser login if available.
            headers['Cookie'] = _session_cookie('cursor.com', 'CURSOR_COOKIE',
                {'WorkosCursorSessionToken', '__Secure-next-auth.session-token', 'next-auth.session-token'})
            result = parse_cursor(_get_json('https://cursor.com/api/usage-summary', headers))
    else:
        headers['Cookie'] = _session_cookie('cursor.com', 'CURSOR_COOKIE',
            {'WorkosCursorSessionToken', '__Secure-next-auth.session-token', 'next-auth.session-token'})
        result = parse_cursor(_get_json('https://cursor.com/api/usage-summary', headers))
    try:
        sand = _get_json('https://cursor.com/api/dashboard/get-sand-usage-status',
                         {**headers, 'Content-Type': 'application/json'}, b'{}', timeout=6)
        if isinstance(sand, dict) and sand.get('hasNonZeroIncludedLimit') is True:
            result['weekly'] = _window_used(sand.get('usagePercent'), sand.get('nextResetTimestampUtc'))
            if sand.get('isUnified') is True:
                # New X subscriptions use the shared Grok/Cursor weekly pool.
                result.pop('monthly', None)
    except ProviderError:
        pass
    if not result.get('monthly') and not result.get('weekly'):
        raise ProviderError('Cursor returned no current quota')
    return result


def parse_grok_billing(payload):
    if not isinstance(payload, dict):
        raise ProviderError('Grok billing data invalid')
    data = payload.get('config') if isinstance(payload.get('config'), dict) else payload
    period = data.get('currentPeriod') if isinstance(data.get('currentPeriod'), dict) else {}
    used = _number(data.get('creditUsagePercent'))
    if used is None:
        spend = data.get('onDemandUsed') or {}
        cap = data.get('onDemandCap') or {}
        if isinstance(spend, dict) and isinstance(cap, dict):
            cap_val = _number(cap.get('val'))
            spent_val = _number(spend.get('val'))
            if cap_val and spent_val is not None:
                used = 100*spent_val/cap_val
    result = {'ok': True}
    if used is not None:
        # This is Grok's billing period, which may be weekly OR monthly.
        start = period.get('start', data.get('billingPeriodStart'))
        end = period.get('end', data.get('billingPeriodEnd'))
        start_iso, end_iso = _iso(start), _iso(end)
        if start_iso and end_iso:
            seconds = (dt.datetime.fromisoformat(end_iso) - dt.datetime.fromisoformat(start_iso)).total_seconds()
            if 6*86400 <= seconds <= 8*86400:
                result['weekly'] = _window_used(used, end)
            elif 27*86400 <= seconds <= 32*86400:
                result['monthly'] = _window_used(used, end)
            else:
                # A real percentage is known, but its billing-window type is not.
                result['credit_percent'] = max(0, 100 - used)
                result['credit_resets_at'] = end_iso
        else:
            result['credit_percent'] = max(0, 100 - used)
            result['credit_resets_at'] = end_iso
    balance = data.get('prepaidBalance')
    if isinstance(balance, dict):
        val = _number(balance.get('val'))
        if val is not None:
            result['balance_text'] = f'{val:g} prepaid credits'
    if not any(result.get(k) for k in ('weekly', 'monthly', 'balance_text', 'credit_percent')):
        raise ProviderError('Grok did not report a current billing allowance')
    return result


def _grok_token(auth: dict):
    """Current Grok CLI OAuth is nested under issuer URLs; ignore expired tokens."""
    if not isinstance(auth, dict):
        return None
    entries = []
    for name, value in auth.items():
        if isinstance(value, dict) and name.startswith(('https://auth.x.ai', 'https://accounts.x.ai')):
            entries.append(value)
    entries.append(auth)  # Older client builds wrote a flat auth object.
    now = time.time()
    for item in entries:
        token = next((item[k] for k in ('key', 'access_token', 'accessToken', 'token')
                      if isinstance(item.get(k), str) and item[k]), None)
        if not token:
            continue
        expires_at = item.get('expires_at')
        if isinstance(expires_at, str) and expires_at:
            ts = _number(expires_at)
            if ts is None:
                iso = _iso(expires_at)
                if iso:
                    ts = dt.datetime.fromisoformat(iso).timestamp()
            if ts is not None and ts > 1e12:
                ts /= 1000
            if ts is not None and ts <= now + 30:
                continue
        elif isinstance(expires_at, (float, int)) and expires_at < (now + 30):
            continue
        return token
    return None


def read_grok():
    token = os.environ.get('GROK_OAUTH_TOKEN', '').strip()
    if not token:
        home = Path(os.environ.get('GROK_HOME') or Path.home()/'.grok')
        try:
            auth = json.loads((home/'auth.json').read_text('utf-8'))
        except (OSError, ValueError):
            raise ProviderError('Sign in with Grok CLI (`grok login`) to track its billing quota') from None
        token = _grok_token(auth)
    if not token or token.startswith('xai-'):
        raise ProviderError('Grok OAuth token missing or expired; run `grok login`')
    return parse_grok_billing(_get_json('https://cli-chat-proxy.grok.com/v1/billing?format=credits', {
        'Authorization': 'Bearer '+token, 'x-xai-token-auth': 'xai-grok-cli'}))


def _windsurf_db_path():
    home = Path.home()
    if platform.system() == 'Windows':
        root = Path(os.environ.get('APPDATA', home/'AppData'/'Roaming'))
    elif platform.system() == 'Darwin':
        root = home/'Library/Application Support'
    else:
        root = Path(os.environ.get('XDG_CONFIG_HOME') or home/'.config')
    return root/'Windsurf/User/globalStorage/state.vscdb'


def parse_windsurf_cache(payload):
    if not isinstance(payload, dict):
        raise ProviderError('Windsurf plan cache invalid')
    quota = payload.get('quotaUsage') or {}
    if not isinstance(quota, dict):
        quota = {}
    result = {'ok': True}
    result['daily'] = _window_left(quota.get('dailyRemainingPercent'), quota.get('dailyResetAtUnix'))
    result['weekly'] = _window_left(quota.get('weeklyRemainingPercent'), quota.get('weeklyResetAtUnix'))
    # Older editor versions only publish these counts, without a known reset
    # interval. Keep them as named counters, not fake daily/weekly windows.
    if not result['daily'] and not result['weekly']:
        counters = payload.get('usage') or {}
        if isinstance(counters, dict):
            model_quotas = []
            for name, total_field, used_field in (('Messages','messages','usedMessages'),
                                                   ('Flow actions','flowActions','usedFlowActions')):
                total = _number(counters.get(total_field))
                used = _number(counters.get(used_field))
                if total and used is not None and 0 <= used <= total:
                    model_quotas.append({'name':name,'remaining_percent':100*(total-used)/total,
                                         'resets_at':None})
            if model_quotas:
                result['model_quotas'] = model_quotas
            else:
                raise ProviderError('Windsurf has no numeric quota in local cache; open Windsurf to update it')
        else:
            raise ProviderError('Windsurf cache missing quota; open Windsurf to update it')
    return result


def read_windsurf():
    value = read_sqlite_item(_windsurf_db_path(), 'windsurf.settings.cachedPlanInfo')
    if not value:
        raise ProviderError('Windsurf cache not found; sign in to the Windsurf editor')
    try:
        payload = json.loads(value)
    except ValueError:
        raise ProviderError('Windsurf cache is unreadable') from None
    return parse_windsurf_cache(payload)


def parse_perplexity_credits(data):
    if not isinstance(data, dict):
        raise ProviderError('Perplexity credits response invalid')
    grants = data.get('credit_grants', data.get('creditGrants'))
    used = _number(data.get('total_usage_cents', data.get('totalUsageCents')))
    if not isinstance(grants, list) or used is None:
        raise ProviderError('Perplexity returned no credit-grant data')
    recurring = 0
    other = 0
    for item in grants:
        if not isinstance(item, dict):
            continue
        amount = _number(item.get('amount_cents', item.get('amountCents')))
        if amount is not None and amount >= 0:
            if item.get('type') == 'recurring':
                recurring += amount
            else:
                other += amount
    result = {'ok': True, 'balance_text': f'{max(0,(recurring+other-used)/100):.2f} credits remaining'}
    if recurring > 0:
        result['credit_percent'] = round(max(0, 100*(1-min(used, recurring)/recurring)), 2)
        result['credit_resets_at'] = _iso(data.get('renewal_date_ts', data.get('renewalDateTs')))
    return result


def read_perplexity():
    names = {'__Secure-authjs.session-token','authjs.session-token',
             '__Secure-next-auth.session-token','next-auth.session-token'}
    cookies = _session_cookie('perplexity.ai', 'PERPLEXITY_COOKIE', names)
    # Filter to session token cookies only (including split authjs tokens).
    pairs = []
    for part in cookies.split(';'):
        if '=' in part:
            name, value = part.strip().split('=',1)
            if name in names or any(name.startswith(n+'.') for n in names):
                pairs.append((name,value))
    if not pairs:
        raise ProviderError('No Perplexity session token; sign into perplexity.ai')
    hdr = '; '.join(f'{k}={v}' for k,v in pairs)
    data = _get_json('https://www.perplexity.ai/rest/billing/credits?version=2.18&source=default', {
        'Cookie': hdr,'Origin':'https://www.perplexity.ai','Referer':'https://www.perplexity.ai/account/usage'})
    return parse_perplexity_credits(data)


def _unpack_json(data, depth=0):
    if depth > 7:
        return data
    if isinstance(data, str) and len(data) < 180000 and data.lstrip().startswith(('{','[')):
        try:
            return _unpack_json(json.loads(data), depth+1)
        except ValueError:
            return data
    if isinstance(data, dict):
        return {k:_unpack_json(v, depth+1) for k,v in data.items()}
    if isinstance(data, list):
        return [_unpack_json(v, depth+1) for v in data[:100]]
    return data


def _find_named(node, candidates, depth=0):
    if depth > 8:
        return None
    if isinstance(node, dict):
        for k,v in node.items():
            if k.lower() in candidates and isinstance(v, dict):
                return v
        for value in node.values():
            got = _find_named(value, candidates, depth+1)
            if got is not None:
                return got
    if isinstance(node, list):
        for value in node[:40]:
            got = _find_named(value, candidates, depth+1)
            if got is not None:
                return got
    return None


def parse_qwen_usage(payload):
    data = _unpack_json(payload)
    result = {'ok': True}
    # Match *named* quota windows only. Never infer a percentage from price,
    # credit values or a reset timestamp on its own.
    for names, target in (({'fivehour','five_hour','5h','limit5h','fivehourquota'}, 'five_hour'),
                          ({'weekly','week','sevenday','7d','limit7d','weeklyquota'}, 'weekly')):
        value = _find_named(data, names)
        if not isinstance(value, dict):
            continue
        reset = next((value.get(k) for k in ('resetAt','resetTime','nextResetAt','nextResetTime','reset_at') if value.get(k)), None)
        rem = next((_number(value[k]) for k in ('remainingPercent','remainingPercentage') if k in value), None)
        used = next((_number(value[k]) for k in ('usedPercent','usagePercent','usedPercentage') if k in value), None)
        total = next((_number(value[k]) for k in ('limit','total','quota') if k in value), None)
        count = next((_number(value[k]) for k in ('used','consumed','usage') if k in value), None)
        result[target] = (_window_left(rem,reset) if rem is not None else
                          _window_used(used,reset) if used is not None else
                          _window_used(100*count/total,reset) if total and count is not None else None)
    if not result.get('five_hour') and not result.get('weekly'):
        raise ProviderError('Qwen Cloud response has no recognised 5h/weekly quota fields')
    return result


def read_qwen():
    # Qwen Cloud international individual Token Plan, not generic Qwen chat.
    cookies = _session_cookie('qwencloud.com', 'QWEN_CLOUD_COOKIE')
    token = os.environ.get('QWEN_CLOUD_SEC_TOKEN')
    dashboard = 'https://home.qwencloud.com/billing/subscription/token-plan-individual'
    if not token:
        # sec_token is a CSRF token, not an API key. Resolve it using the
        # signed-in dashboard; abort if unavailable instead of guessing.
        from urllib.request import Request
        try:
            with _OPENER.open(Request(dashboard, headers={'Cookie':cookies,'User-Agent':'Mozilla/5.0'}),timeout=8) as response:
                page = response.read(262145).decode('utf-8','replace')
        except (URLError, HTTPError, TimeoutError):
            raise ProviderError('Qwen Cloud dashboard unavailable or login expired') from None
        match = re.search(r'["\\\']sec_token["\\\']\s*[:=]\s*["\\\']([^"\\\']{4,256})',page)
        if match:
            token = match.group(1)
        else:
            match = re.search(r'(?:^|;\s*)sec_token=([^;]+)',cookies)
            if match:
                token = match.group(1)
    if not token:
        try:
            info = _get_json('https://home.qwencloud.com/tool/user/info.json',
                             {'Cookie': cookies, 'Referer': dashboard}, timeout=6)
            if isinstance(info, dict):
                nested = info.get('data') or info.get('Data')
                items = [info, nested] if isinstance(nested, dict) else [info]
                token = next((part[key] for part in items for key in ('sec_token','secToken')
                              if isinstance(part.get(key), str) and len(part[key]) >= 4), None)
        except ProviderError:
            pass
    if not token:
        raise ProviderError('Cannot resolve Qwen Cloud sec_token from browser login')
    api = 'zeldaHttp.apikeyMgr./tokenplan/personal/api/v2/usage'
    url = 'https://cs-data.qwencloud.com/data/api.json?' + urlencode({
        'action':'IntlBroadScopeAspnGateway','product':'sfm_bailian','api':api,'_v':'undefined'})
    cornerstone = {'feTraceId':str(uuid.uuid4()),'feURL':dashboard,'protocol':'V2',
                   'console':'ONE_CONSOLE','productCode':'p_efm','domain':'home.qwencloud.com',
                   'consoleSite':'QWENCLOUD','userNickName':'','userPrincipalName':'','xsp_lang':'en-US'}
    form = urlencode({'product':'sfm_bailian','action':'IntlBroadScopeAspnGateway',
                      'sec_token':token,'region':'ap-southeast-1','language':'en-US',
                      'params':json.dumps({'Api':api,'V':'1.0','Data':{'cornerstoneParam':cornerstone}})})
    response = _get_json(url,{'Cookie':cookies,'Content-Type':'application/x-www-form-urlencoded',
                        'Origin':'https://home.qwencloud.com','Referer':dashboard,
                        'X-Requested-With':'XMLHttpRequest'}, form.encode('utf-8'))
    return parse_qwen_usage(response)


READERS = {
    'grok': read_grok, 'cursor': read_cursor, 'windsurf': read_windsurf,
    'qwen': read_qwen, 'perplexity': read_perplexity,
}
