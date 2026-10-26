"""Portable tooltip formatting for usage quotas (no Qt dependency).

Reset timestamps are UTC/offset-aware ISO-8601. Display times are converted
using the machine's local timezone, including daylight-saving transitions.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any, Mapping

from .core import PROVIDERS

# Windows notification icon tooltips have a small OS text limit. Leave a few
# characters of headroom so Qt/Windows don't truncate a reset time mid-line.
MAX_TRAY_TOOLTIP = 120


def local_reset_time(value: Any, *, compact: bool = False, timezone: dt.tzinfo | None = None) -> str | None:
    """Return an accurate local reset date/time, or None if unavailable."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        timestamp = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            return None  # Never guess whether a naive timestamp means UTC.
        local = timestamp.astimezone(timezone)
    except (TypeError, ValueError, OverflowError):
        return None
    return local.strftime("%d %b %H:%M" if compact else "%a %d %b %H:%M")


def _window(snapshot: Mapping[str, Any] | None, key: str) -> Mapping[str, Any] | None:
    if not snapshot or snapshot.get("ok") is not True:
        return None
    value = snapshot.get(key)
    return value if isinstance(value, dict) else None


def _remaining(value: Mapping[str, Any] | None) -> str:
    if not value:
        return "--"
    amount = value.get("remaining_percent")
    if isinstance(amount, (int, float)) and not isinstance(amount, bool) and math.isfinite(amount) and 0 <= amount <= 100:
        return f"{amount:g}% left"
    return "--"


def individual_tooltip(provider: str, snapshot: Mapping[str, Any] | None,
                       *, timezone: dt.tzinfo | None = None) -> str:
    """Show both 5h and weekly windows on *each* unmerged tray icon."""
    name = PROVIDERS[provider]["short"]
    if not snapshot or snapshot.get("ok") is not True:
        return f"{name} (local time)\nUsage unavailable; reset times unknown"
    model_quotas = snapshot.get('model_quotas')
    if provider in ('gemini', 'copilot') and isinstance(model_quotas, list) and model_quotas:
        lines = [f"{name} quota (local time)"]
        for quota in model_quotas[:2]:
            reset = local_reset_time(quota.get('resets_at'), compact=True, timezone=timezone) or '?'
            lines.append(f"{quota['name'][:16]}: {_remaining(quota)}; {reset}")
        if len("\n".join(lines)) > MAX_TRAY_TOOLTIP:
            lines = lines[:2]  # never truncate a reset timestamp mid-string
        return "\n".join(lines)
    windows = (_window(snapshot, "five_hour"), _window(snapshot, "weekly"))
    if all(v is None for v in windows):
        for field, tag in (('monthly','Month'),('daily','Day')):
            d = _window(snapshot, field)
            if d is not None:
                reset = local_reset_time(d.get('resets_at'), timezone=timezone)
                return f"{name} ({tag}): {_remaining(d)}\nReset {reset or 'unknown'} (local)"
        balance = snapshot.get("balance_text")
        if isinstance(balance, str) and balance:
            reset = local_reset_time(snapshot.get('credit_resets_at'),timezone=timezone)
            extra = f'\nRenews {reset} (local)' if reset else '\nNo timed quota reset available'
            return f"{name}: {balance[:60]}{extra}"
        return f"{name} (local time)\nNo 5h or weekly reset available"
    lines = [f"{name} (local time)"]
    for label, data in zip(("5h", "7d"), windows):
        if data is None:
            lines.append(f"{label}: not available")
        else:
            local = local_reset_time(data.get("resets_at"), timezone=timezone)
            lines.append(f"{label}: {_remaining(data)}; reset {local or 'unknown'}")
    # Compact timestamps if Windows' short tooltip limit would otherwise clip
    # the end of a reset time. Never chop a timestamp in the middle.
    tooltip = "\n".join(lines)
    if len(tooltip) > MAX_TRAY_TOOLTIP:
        lines = [f"{name} (local)"]
        for label, data in zip(("5h", "7d"), windows):
            local = local_reset_time(data.get("resets_at"), compact=True, timezone=timezone) if data else None
            lines.append(f"{label}: {_remaining(data)}; reset {local or 'unknown'}" if data else f"{label}: unavailable")
        tooltip = "\n".join(lines)
    return tooltip


def _merged_line(provider: str, snapshot: Mapping[str, Any] | None,
                 *, timezone: dt.tzinfo | None) -> str:
    name = PROVIDERS[provider]["short"]
    if not snapshot or snapshot.get("ok") is not True:
        return f"{name}: unavailable"
    if PROVIDERS[provider]['source'] == 'dashboard':
        return f"{name}: open account usage"
    pieces = []
    if provider in ('gemini', 'copilot'):
        quotas = snapshot.get('model_quotas')
        if isinstance(quotas, list) and quotas:
            q = min(quotas, key=lambda q: q.get('remaining_percent', 101))
            return f"{name}: {q['remaining_percent']:g}% ({local_reset_time(q.get('resets_at'), compact=True, timezone=timezone) or '?'})"
    for field, label in (("five_hour", "5h"), ("weekly", "7d"), ("monthly", "month"), ("daily", "day")):
        item = _window(snapshot, field)
        if item is not None:
            pieces.append(f"{label} {local_reset_time(item.get('resets_at'), compact=True, timezone=timezone) or '?'}")
    return f"{name}: " + (" / ".join(pieces) if pieces else "no timed reset")


def merged_tooltip(providers: list[str], snapshots: Mapping[str, Mapping[str, Any]],
                   *, timezone: dt.tzinfo | None = None, max_chars: int = MAX_TRAY_TOOLTIP) -> str:
    """Fit as many selected providers as possible without cutting a time in half.

    Users with many providers can click the merged icon for the full quick view.
    """
    names = [name for name in providers if name in PROVIDERS]
    header = "Reset times (local)"
    lines = [header]
    displayed = 0
    for idx, name in enumerate(names):
        line = _merged_line(name, snapshots.get(name), timezone=timezone)
        remaining = len(names) - idx - 1
        overflow = f"\n+{remaining} more; click for quick view" if remaining else ""
        proposed = "\n".join(lines + [line]) + overflow
        if len(proposed) > max_chars:
            break
        lines.append(line)
        displayed += 1
    hidden = len(names) - displayed
    if hidden:
        suffix = f"+{hidden} more; click for quick view"
        while len("\n".join(lines + [suffix])) > max_chars and len(lines) > 1:
            lines.pop()
            displayed -= 1
            hidden += 1
            suffix = f"+{hidden} more; click for quick view"
        lines.append(suffix)
    if not names:
        lines.append("No providers selected")
    return "\n".join(lines)
