"""Provider adapters. Only real quota windows or actual credit balances are displayed."""
from __future__ import annotations

import math
import re
from typing import Any
from urllib.parse import urlparse

from .core import parse_response


def is_local_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return (parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1")
                and not parsed.username and not parsed.password and bool(parsed.port)
                and len(url) < 2048)
    except ValueError:
        return False


def window(remaining: Any, reset: Any = None) -> dict[str, Any] | None:
    if isinstance(remaining, bool) or not isinstance(remaining, (int, float)) or not math.isfinite(remaining) or not 0 <= remaining <= 100:
        return None
    return {"remaining_percent": float(remaining), "resets_at": reset if isinstance(reset, str) else None}


def base_result() -> dict[str, Any]:
    return {"ok": True, "five_hour": None, "weekly": None, "monthly": None, "balance_text": None, "error": None}


def normalize(service: str, payload: Any) -> dict[str, Any]:
    """Normalize upstream payloads without equating credit balances to subscription quotas."""
    if service in ("codex", "claude"):
        return parse_response(payload)
    if not isinstance(payload, dict):
        raise ValueError("Usage response was not an object")
    if service == "kimi" and "data" in payload:
        data = payload["data"]
        if not isinstance(data, dict) or data.get("kind") != "ok":
            raise ValueError(str(data.get("message", "Kimi quota not available"))[:160] if isinstance(data, dict) else "Unexpected Kimi response")
        quota = data.get("quota") or {}
        usages = quota.get("usages") or {}
        result = base_result()
        if isinstance(usages, dict):
            for original, target in (("limit5h", "five_hour"), ("limit7d", "weekly"), ("monthTotal", "monthly")):
                raw = usages.get(original)
                if isinstance(raw, dict):
                    ratio = raw.get("usedRatio")
                    if isinstance(ratio, (int, float)) and not isinstance(ratio, bool) and math.isfinite(ratio) and 0 <= ratio <= 1:
                        result[target] = window(100 * (1 - ratio), raw.get("resetAt"))
        wallet = quota.get("extraUsage")
        if isinstance(wallet, dict) and isinstance(wallet.get("balanceCents"), (int, float)):
            currency = wallet.get("currency") or "USD"
            result["balance_text"] = f"{currency} {wallet['balanceCents'] / 100:,.2f} extra"
        return result
    if service == "deepseek":
        infos = payload.get("balance_infos")
        if not isinstance(infos, list) or not infos:
            raise ValueError("DeepSeek returned no balance information")
        balance_parts = []
        for item in infos:
            if isinstance(item, dict):
                try:
                    amount = float(item["total_balance"])
                    if math.isfinite(amount):
                        balance_parts.append(f"{item.get('currency', '')} {amount:,.2f}")
                except (ValueError, TypeError, KeyError):
                    continue
        if not balance_parts:
            raise ValueError("No valid DeepSeek balance")
        result = base_result()
        result["balance_text"] = " · ".join(balance_parts)
        return result
    if service == "openrouter":
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("OpenRouter returned no credits data")
        try:
            total = float(data["total_credits"])
            used = float(data["total_usage"])
            if not all(math.isfinite(v) for v in (total, used)):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise ValueError("Invalid OpenRouter credits") from None
        result = base_result()
        result["balance_text"] = f"USD {max(0, total - used):,.2f} credits"
        if total > 0:
            result["credit_percent"] = max(0., min(100., 100 * (total - used) / total))
        return result

    # Custom bridges use the /get format, plus optional `monthly` and `balance_text`.
    if payload.get("ok") is not True or payload.get("stale") is True:
        raise ValueError(str(payload.get("error") or "Bridge has no fresh usage data")[:160])
    result = base_result()
    for key in ("five_hour", "weekly", "monthly"):
        raw = payload.get(key)
        if isinstance(raw, dict):
            remaining = raw.get("remaining_percent")
            if remaining is None and isinstance(raw.get("used_percent"), (float, int)) and not isinstance(raw.get("used_percent"), bool):
                remaining = 100 - raw["used_percent"]
            result[key] = window(remaining, raw.get("resets_at"))
    balance = payload.get("balance_text")
    if isinstance(balance, str) and len(balance) <= 100:
        result["balance_text"] = balance
    return result


ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

def parse_muse_usage(output: str) -> dict[str, Any]:
    """Best-effort CLI text adapter, strict enough not to misread unrelated token counts."""
    text = ANSI.sub("", output)
    if len(text) > 200_000:
        raise ValueError("Muse usage output unexpectedly large")
    try:
        import json
        obj = json.loads(text)
        if isinstance(obj, dict):
            if "usage" in obj and isinstance(obj["usage"], dict):
                obj = obj["usage"]
            if "ok" in obj:
                return normalize("muse", obj)
    except (ValueError, TypeError):
        pass
    result = base_result()
    for line in text.splitlines():
        low = line.lower()
        target = ("five_hour" if re.search(r"\b5[ -]?h(?:our)?s?\b|five[ -]?hour", low) else
                  "weekly" if re.search(r"\bweek(?:ly)?\b|\b7[ -]?d(?:ays)?\b", low) else None)
        if not target:
            continue
        matches = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%\s*(remaining|left|used)", low)
        if matches:
            n = float(matches.group(1))
            result[target] = window(100 - n if matches.group(2) == "used" else n)
        else:
            matches = re.search(r"(used|remaining|left)\s*:?\s*(\d{1,3}(?:\.\d+)?)\s*%", low)
            if matches:
                n = float(matches.group(2))
                result[target] = window(100 - n if matches.group(1) == "used" else n)
    if result["five_hour"] is None and result["weekly"] is None:
        raise ValueError("Muse CLI returned no recognisable quota percentages (check `muse usage` manually)")
    return result


def icon_number(result: dict[str, Any] | None, field: str = "five_hour") -> str:
    if not result or not result.get("ok"):
        return "--"
    value = result.get(field)
    if isinstance(value, dict) and value.get("remaining_percent") is not None:
        return str(int(round(value["remaining_percent"])))
    # Balances do not have a meaningful percentage without a known quota.
    return "--"


def normalize_direct_result(service: str, data: Any) -> dict[str, Any]:
    """Validate direct subprocess output before rendering it in the UI."""
    if service not in ('gemini', 'copilot') or not isinstance(data, dict):
        raise ValueError('Invalid direct usage response')
    if data.get('ok') is False:
        raise ValueError(str(data.get('error') or 'Account unavailable')[:220])
    if data.get('ok') is not True:
        raise ValueError('Direct reader returned no account data')
    result = base_result()
    for field in ('monthly',):
        item = data.get(field)
        if isinstance(item, dict):
            result[field] = window(item.get('remaining_percent'), item.get('resets_at'))
    raw = data.get('model_quotas')
    if isinstance(raw, list):
        quotas = []
        for entry in raw[:100]:
            if not isinstance(entry, dict) or not isinstance(entry.get('name'), str):
                continue
            pct = window(entry.get('remaining_percent'), entry.get('resets_at'))
            if pct:
                quotas.append({'name': entry['name'][:72], **pct})
        result['model_quotas'] = quotas
    if not result.get('model_quotas') and not result.get('monthly'):
        raise ValueError('No supported quota metrics found')
    return result


def parse_direct_output(output: bytes) -> dict[str, Any]:
    """Accept JSON from the WSL reader even if an interactive shell prints a greeting."""
    if len(output) > 262144:
        raise ValueError('Direct reader output too large')
    for line in reversed(output.decode('utf-8', 'replace').splitlines()[-16:]):
        if line.lstrip().startswith('{'):
            try:
                data = __import__('json').loads(line)
                if isinstance(data, dict) and isinstance(data.get('ok'), bool):
                    return data
            except ValueError:
                pass
    raise ValueError('Direct reader returned no valid usage response')
