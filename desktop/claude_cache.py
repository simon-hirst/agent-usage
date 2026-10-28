"""Small, credential-free last-successful Claude quota cache for the desktop UI.

A stale snapshot is still useful, but must never be presented as live usage.
Only the percentages and reported reset timestamps are written to disk.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any


def _timestamp(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 48:
        return None
    try:
        stamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.utcoffset() is None:
            return None
        return stamp.isoformat()
    except (ValueError, OverflowError):
        return None


def _snapshot(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    out: dict[str, Any] = {"five_hour": None, "weekly": None}
    for name in out:
        item = value.get(name)
        if not isinstance(item, dict):
            continue
        remaining = item.get("remaining_percent")
        if (isinstance(remaining, (int, float)) and not isinstance(remaining, bool)
                and math.isfinite(remaining) and 0 <= remaining <= 100):
            out[name] = {
                "remaining_percent": float(remaining),
                "resets_at": _timestamp(item.get("resets_at")),
            }
    return out if any(isinstance(v, dict) for v in out.values()) else None


class ClaudeLastKnown:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.saved_at: str | None = None
        self.snapshot: dict[str, Any] | None = None
        self._load()

    def _load(self) -> None:
        try:
            if self.path.stat().st_size > 8192:
                return
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return
            stamp = _timestamp(data.get("saved_at"))
            snapshot = _snapshot(data.get("snapshot"))
            if stamp and snapshot:
                self.saved_at = stamp
                self.snapshot = snapshot
        except (OSError, ValueError, UnicodeError):
            pass

    def _save(self) -> None:
        if self.snapshot is None or self.saved_at is None:
            return
        temp: str | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".claude-usage-", suffix=".tmp", delete=False) as stream:
                temp = stream.name
                json.dump({"saved_at": self.saved_at, "snapshot": self.snapshot}, stream)
                stream.write("\n")
            os.replace(temp, self.path)
        except OSError:
            pass  # Keep the in-memory snapshot even on a read-only disk.
        finally:
            if temp is not None:
                try:
                    Path(temp).unlink(missing_ok=True)
                except OSError:
                    pass

    def fallback(self, reason: str) -> dict[str, Any] | None:
        if self.snapshot is None:
            return None
        return {
            "ok": True,
            "stale": True,
            "last_updated_at": self.saved_at,
            "error": str(reason)[:220],
            **self.snapshot,
        }

    def apply(self, result: dict[str, Any]) -> dict[str, Any]:
        """Keep the last valid reading on failure; replace it on recovery."""
        good = _snapshot(result) if result.get("ok") is True and not result.get("stale") else None
        if good is not None:
            self.snapshot = good
            self.saved_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
            self._save()
            return result
        return self.fallback(str(result.get("error") or "Claude usage temporarily unavailable")) or result
