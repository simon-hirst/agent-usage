"""Direct account readers (no bridge servers). Outputs ONLY quota JSON, never tokens.

Gemini: signed-in Gemini CLI OAuth + Google's Code Assist quota RPC.
Copilot: signed-in GitHub CLI token + GitHub's internal Copilot user endpoint.
Both may change independently of this app. Read-only, no browser cookie extraction.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request


class ReaderError(Exception):
    pass


def fetch_json(url: str, token: str, payload: dict | None = None) -> dict:
    headers = {"Accept": "application/json", "Authorization": "Bearer " + token,
               "User-Agent": "provider-usage-tray/3.2"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if "api.github.com" in url:
        headers["X-GitHub-Api-Version"] = "2025-05-01"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=9) as result:
            raw = result.read(524289)
    except urllib.error.HTTPError as err:
        raise ReaderError(f"Provider returned HTTP {err.code}; check account permissions/login") from None
    except (urllib.error.URLError, TimeoutError) as err:
        raise ReaderError("Provider quota request unavailable: " + str(err.reason if hasattr(err, 'reason') else err)[:90]) from None
    if len(raw) > 524288:
        raise ReaderError("Quota response too large")
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError):
        raise ReaderError("Provider returned invalid JSON") from None
    if not isinstance(result, dict):
        raise ReaderError("Provider response not an object")
    return result


def percent(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        return None
    return float(value) if 0 <= value <= 100 else None


def parse_gemini_quota(payload: dict) -> dict:
    """Retain model-level quotas: they are NOT invented 5h/weekly windows."""
    buckets = payload.get("buckets")
    if not isinstance(buckets, list):
        raise ReaderError("Gemini returned no quota buckets")
    models = []
    for item in buckets:
        if not isinstance(item, dict):
            continue
        fraction = item.get("remainingFraction")
        name = item.get("modelId")
        if isinstance(fraction, bool) or not isinstance(fraction, (float, int)) or not isinstance(name, str):
            continue
        remaining = percent(fraction * 100)
        if remaining is not None:
            models.append({"name": name[:72], "remaining_percent": remaining,
                           "resets_at": item.get("resetTime") if isinstance(item.get("resetTime"), str) else None})
    if not models:
        raise ReaderError("Gemini has no numeric model quota information")
    models.sort(key=lambda item: (item["remaining_percent"], item["name"]))
    return {"ok": True, "model_quotas": models}


def parse_copilot_quota(payload: dict) -> dict:
    """Copilot quota is monthly; don't map it to a five-hour or weekly window."""
    snapshots = payload.get("quota_snapshots") or payload.get("quotaSnapshots")
    if not isinstance(snapshots, dict):
        raise ReaderError("Copilot provided no quota snapshots (login may lack Copilot scope)")
    quotas = []
    for label, item in snapshots.items():
        if not isinstance(item, dict):
            continue
        rem = item.get("percent_remaining", item.get("remainingPercentage"))
        pct = percent(rem)
        if pct is None:
            continue
        quotas.append({"name": label[:72], "remaining_percent": pct,
                       "resets_at": payload.get("quota_reset_date_utc") or payload.get("quota_reset_date") or item.get("resetDate")})
    if not quotas:
        raise ReaderError("Copilot returned no usable quota percentages")
    primary = next((item for item in quotas if item['name'] in ('premium_interactions', 'ai_credits')), quotas[0])
    return {"ok": True, "monthly": {"remaining_percent": primary['remaining_percent'],
                                      "resets_at": primary['resets_at']}, "model_quotas": quotas,
            "quota_label": "Monthly Copilot allowance"}


def read_gemini() -> dict:
    file = Path.home() / '.gemini' / 'oauth_creds.json'
    try:
        creds = json.loads(file.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise ReaderError("Gemini CLI OAuth login not found; sign in with Gemini CLI") from None
    token = creds.get('access_token')
    expiry = creds.get('expiry_date')
    if not isinstance(token, str) or not token:
        raise ReaderError('Gemini login has no access token')
    if isinstance(expiry, (float, int)) and expiry < (time.time() * 1000 + 15000):
        raise ReaderError('Gemini OAuth token expired; open Gemini CLI to refresh your login')
    project = os.environ.get('GOOGLE_CLOUD_PROJECT') or os.environ.get('GOOGLE_CLOUD_PROJECT_ID')
    if not project:
        project = (fetch_json('https://cloudcode-pa.googleapis.com/v1internal:loadCodeAssist', token,
                              {"metadata": {"ideType": "IDE_UNSPECIFIED", "platform": "PLATFORM_UNSPECIFIED", "pluginType": "GEMINI"}})
                   .get('cloudaicompanionProject'))
    body = {'project': project} if isinstance(project, str) and project else {}
    quota = fetch_json('https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota', token, body)
    return parse_gemini_quota(quota)


def read_copilot() -> dict:
    try:
        token = subprocess.run(['gh', 'auth', 'token'], capture_output=True, text=True, timeout=6, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ReaderError('GitHub CLI unavailable; install gh and run `gh auth login`') from None
    if token.returncode != 0 or not token.stdout.strip():
        raise ReaderError('Sign in to GitHub CLI using `gh auth login`')
    value = token.stdout.strip()
    # Never emit/record access token, including on HTTP errors.
    return parse_copilot_quota(fetch_json('https://api.github.com/copilot_internal/user', value))


def run(service: str, output_path: str | None = None) -> int:
    try:
        if service == 'gemini':
            result = read_gemini()
        elif service == 'copilot':
            result = read_copilot()
        else:
            raise ReaderError('Unknown direct reader')
    except (ReaderError, OSError, ValueError) as err:
        result = {"ok": False, "error": str(err)[:220]}
    result_json = json.dumps(result, separators=(',', ':'))
    if output_path:
        # Native PyInstaller windowed executables may have no stdout. Use a
        # per-user 0600 temporary result file, deleted immediately by the tray.
        target = Path(output_path)
        with target.open('w', encoding='utf-8') as dest:
            dest.write(result_json)
    else:
        print(result_json, flush=True)
    return 0  # The tray consumes the explicit ok flag, not an exit code.


if __name__ == '__main__':
    args = sys.argv[1:]
    if len(args) == 1:
        raise SystemExit(run(args[0]))
    if len(args) == 3 and args[1] == '--output':
        raise SystemExit(run(args[0], args[2]))
    raise SystemExit(2)
