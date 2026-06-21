#!/usr/bin/env python3
"""Local-only Claude/Claude Code quota bridge (Python standard library only).

Uses the logged-in Claude Code OAuth access token; token is *never* sent to a
browser or returned by the HTTP API. This uses an undocumented Anthropic usage
endpoint, so it may break or be rate-limited without warning.
"""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import json
import math
import os
import pathlib
import subprocess
import hashlib
import platform
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

VERSION = "1.0.0"
DEFAULT_PORT = 3790
DEFAULT_INTERVAL = 60
URL = "https://api.anthropic.com/api/oauth/usage"
UTC = dt.timezone.utc


def iso_utc(timestamp: float | None = None) -> str:
    timestamp = time.time() if timestamp is None else timestamp
    return dt.datetime.fromtimestamp(timestamp, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def parse_timestamp(value: Any) -> int | None:
    n = number(value)
    if n is not None:
        # Support Unix seconds or milliseconds, should Anthropic vary its format.
        if n > 1e11:
            n /= 1000
        return int(n) if 0 <= n < 1e11 else None
    if not isinstance(value, str) or len(value) > 80:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return int(parsed.timestamp())
    except (ValueError, OverflowError, OSError):
        return None


def parse_window(raw: Any, duration_minutes: int, scale: str = "percent") -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    used = number(raw.get("utilization"))
    if used is None:
        return None
    if scale == "fraction":
        used *= 100
    if used < 0 or used > 100:
        raise ValueError("Unexpected Claude utilization value (expected percentage from 0 to 100)")
    reset = parse_timestamp(raw.get("resets_at"))
    return {
        "used_percent": round(used, 2),
        "remaining_percent": round(max(0, 100 - used), 2),
        "duration_minutes": duration_minutes,
        "resets_at_unix": reset,
    }


def clean_extra(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    out: dict[str, Any] = {}
    if isinstance(raw.get("is_enabled"), bool):
        out["is_enabled"] = raw["is_enabled"]
    for field in ("used_credits", "monthly_limit", "utilization"):
        val = number(raw.get(field))
        out[field] = val
    if isinstance(raw.get("currency"), str):
        out["currency"] = raw["currency"][:10]
    return out or None


def clean_scoped(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    result = []
    for entry in raw[:100]:
        if not isinstance(entry, dict):
            continue
        item = {key: entry[key][:100] for key in ("kind", "group") if isinstance(entry.get(key), str)}
        fraction = number(entry.get("percent"))
        if fraction is not None and 0 <= fraction <= 100:
            item["used_percent"] = round(fraction, 2)
            item["remaining_percent"] = round(100 - fraction, 2)
        item["resets_at_unix"] = parse_timestamp(entry.get("resets_at"))
        scope = entry.get("scope")
        if isinstance(scope, dict):
            model = scope.get("model")
            if isinstance(model, dict) and isinstance(model.get("display_name"), str):
                item["model"] = model["display_name"][:100]
        if "used_percent" in item:
            result.append(item)
    return result


def normalize(raw: Any, scale: str = "percent") -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("Anthropic returned invalid quota data")
    if scale not in ("percent", "fraction"):
        raise ValueError("Unknown utilization scale")
    main = parse_window(raw.get("five_hour"), 300, scale)
    weekly = parse_window(raw.get("seven_day"), 10080, scale)
    additional = {}
    for name, window in raw.items():
        if not isinstance(name, str) or name in ("seven_day", "five_hour"):
            continue
        if name.startswith("seven_day_"):
            normalized = parse_window(window, 10080, scale)
        elif name.startswith("five_hour_"):
            normalized = parse_window(window, 300, scale)
        else:
            continue
        if normalized is not None:
            additional[name] = normalized
    scoped = clean_scoped(raw.get("limits"))
    if main is None and weekly is None and not additional and not scoped:
        raise ValueError("Anthropic returned no quota windows. Check Claude Code is logged in with a subscription.")
    return {
        "five_hour": main,
        "weekly": weekly,
        "additional_limits": additional,
        "scoped_limits": scoped,
        "extra_usage": clean_extra(raw.get("extra_usage")),
    }


def public_window(value: dict[str, Any] | None, now: float) -> dict[str, Any] | None:
    if value is None:
        return None
    data = dict(value)
    reset = data.get("resets_at_unix")
    data["resets_at"] = iso_utc(reset) if reset is not None else None
    data["resets_in_seconds"] = max(0, math.ceil(reset - now)) if reset is not None else None
    return data


def public_snapshot(value: dict[str, Any], now: float) -> dict[str, Any]:
    return {
        "five_hour": public_window(value["five_hour"], now),
        "weekly": public_window(value["weekly"], now),
        "additional_limits": {
            k: public_window(v, now) for k, v in value["additional_limits"].items()
        },
        "scoped_limits": [public_window(v, now) for v in value["scoped_limits"]],
        "extra_usage": value["extra_usage"],
    }


class UsageError(Exception):
    pass


class RateLimited(UsageError):
    def __init__(self, retry_after: float | None):
        super().__init__("Anthropic usage endpoint returned HTTP 429 (rate limited)")
        self.retry_after = retry_after


def read_retry_after(value: str | None, now: float) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
        return seconds if math.isfinite(seconds) and seconds > 0 else None
    except ValueError:
        try:
            date = email.utils.parsedate_to_datetime(value)
            return max(0, date.timestamp() - now)
        except (ValueError, TypeError, OverflowError):
            return None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise UsageError("Anthropic usage endpoint redirected unexpectedly; refusing to forward credentials")


def read_credentials(path: pathlib.Path) -> dict[str, Any]:
    """Claude Code's normal credential store: file on Linux/Windows, Keychain on macOS.

    Mac Keychain may prompt for user permission. Never log or expose the token.
    """
    if platform.system() == "Darwin" and not path.is_file():
        config = pathlib.Path(os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude")).expanduser().resolve()
        default = pathlib.Path("~/.claude").expanduser().resolve()
        suffix = "" if config == default else "-" + hashlib.sha256(str(config).encode()).hexdigest()[:8]
        try:
            result = subprocess.run(
                ["/usr/bin/security", "find-generic-password", "-s", "Claude Code-credentials" + suffix, "-w"],
                capture_output=True, check=False, timeout=8,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise UsageError("Could not read Claude Code credentials from macOS Keychain.") from exc
        if result.returncode != 0:
            raise UsageError("Claude Code Keychain login not found/authorised. Open Claude Code and sign in.")
        try:
            value = json.loads(result.stdout)
        except ValueError as exc:
            raise UsageError("Claude Code Keychain returned invalid credentials data.") from exc
        if not isinstance(value, dict):
            raise UsageError("Claude Code Keychain returned unexpected data.")
        return value
    try:
        with path.open("r", encoding="utf-8") as file:
            value = json.load(file)
        if not isinstance(value, dict):
            raise ValueError("Not an object")
        return value
    except FileNotFoundError as exc:
        raise UsageError(f"No Claude Code login at {path}. Run Claude Code and sign in.") from exc
    except (OSError, ValueError) as exc:
        raise UsageError("Could not read Claude Code OAuth credentials. Check your login.") from exc


class ClaudeUsageClient:
    def __init__(self, credentials_path: pathlib.Path, scale: str = "percent", endpoint: str = URL,
                 opener: Any = None, timeout: float = 12):
        self.credentials_path = credentials_path
        self.scale = scale
        self.endpoint = endpoint
        self.opener = opener if opener is not None else urllib.request.build_opener(NoRedirect())
        self.timeout = timeout

    def fetch(self) -> dict[str, Any]:
        data = read_credentials(self.credentials_path)
        creds = data.get("claudeAiOauth") if isinstance(data, dict) else None
        token = creds.get("accessToken") if isinstance(creds, dict) else None
        if not isinstance(token, str) or not token:
            raise UsageError("No Claude Code OAuth access token; sign in with /login (API-key login is not supported).")
        expires = number(creds.get("expiresAt"))
        if expires is not None:
            if expires > 1e11:
                expires /= 1000
            if time.time() >= expires:
                # Do not rotate shared refresh tokens behind Claude Code's back.
                raise UsageError("Claude Code access token expired. Open Claude Code to renew login, then retry.")

        request = urllib.request.Request(self.endpoint, method="GET", headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
            "Accept": "application/json",
            "User-Agent": "local-claude-usage/1.0",
        })
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                # An unexpected HTML/error page must not be treated as valid quota data.
                if response.status != 200:
                    raise UsageError(f"Anthropic returned HTTP {response.status}")
                body = response.read(1024 * 1024 + 1)
                if len(body) > 1024 * 1024:
                    raise UsageError("Anthropic usage payload unexpectedly large")
                raw = json.loads(body)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise RateLimited(read_retry_after(exc.headers.get("Retry-After"), time.time())) from None
            if exc.code in (401, 403):
                raise UsageError("Claude OAuth authentication rejected. Open Claude Code to renew /login.") from None
            raise UsageError(f"Anthropic usage endpoint returned HTTP {exc.code}") from None
        except urllib.error.URLError as exc:
            raise UsageError("Could not reach Anthropic usage endpoint (check network / DNS / TLS).") from exc
        except (TimeoutError, OSError) as exc:
            raise UsageError("Request to Anthropic usage endpoint timed out or failed.") from exc
        except ValueError as exc:
            raise UsageError("Anthropic returned invalid JSON.") from exc
        return normalize(raw, self.scale)


class UsageCache:
    def __init__(self, client: ClaudeUsageClient, interval: int = DEFAULT_INTERVAL):
        self.client = client
        self.interval = interval
        self.lock = threading.Lock()
        self.snapshot: dict[str, Any] | None = None
        self.updated_at: float | None = None
        self.error: str | None = None
        self.failed_at: float | None = None
        self.next_poll: float = 0
        self.rate_limit_failures = 0
        self.stopped = threading.Event()

    def refresh(self) -> bool:
        now = time.time()
        with self.lock:
            if now < self.next_poll:
                return False
        try:
            fetched = self.client.fetch()
        except RateLimited as exc:
            with self.lock:
                self.rate_limit_failures += 1
                # 429 can persist for a long time; don't hammer the endpoint.
                backoff = min(3600, 900 * 2 ** min(self.rate_limit_failures - 1, 2))
                backoff = max(backoff, exc.retry_after or 0)
                self.next_poll = time.time() + backoff
                self.error = f"HTTP 429: paused Anthropic polling for {math.ceil(backoff)}s to respect its rate limit"
                self.failed_at = time.time()
            print(f"[{iso_utc()}] {self.error}", file=sys.stderr, flush=True)
            return False
        except Exception as exc:
            with self.lock:
                self.error = str(exc)[:300] if isinstance(exc, UsageError) else f"Refresh error: {type(exc).__name__}"
                self.failed_at = time.time()
                self.next_poll = time.time() + self.interval
            print(f"[{iso_utc()}] {self.error}", file=sys.stderr, flush=True)
            return False
        now = time.time()
        with self.lock:
            self.snapshot = fetched
            self.updated_at = now
            self.error = None
            self.failed_at = None
            self.rate_limit_failures = 0
            self.next_poll = now + self.interval
        print(f"[{iso_utc(now)}] Claude usage refreshed", file=sys.stderr, flush=True)
        return True

    def run(self) -> None:
        # Lightweight local timer; never fetches more frequently than configured.
        while not self.stopped.wait(min(self.interval, 10)):
            self.refresh()

    def get(self) -> tuple[dict[str, Any], int]:
        now = time.time()
        with self.lock:
            snapshot = self.snapshot
            updated = self.updated_at
            error = self.error
            failure = self.failed_at
            next_poll = self.next_poll
        common = {
            "source": "anthropic-oauth-usage-undocumented",
            "refresh_interval_seconds": self.interval,
            "next_refresh_at": iso_utc(next_poll) if next_poll > now else None,
        }
        if snapshot is None:
            return {
                "ok": False, "stale": True, "updated_at": None, "age_seconds": None,
                "error": error or "Initial Claude usage refresh has not completed.",
                **common, "five_hour": None, "weekly": None, "additional_limits": {},
                "scoped_limits": [], "extra_usage": None,
            }, 503
        age = max(0, int(now - updated))
        stale = age >= 2 * self.interval or (failure is not None and failure > updated)
        return {
            "ok": not stale,
            "stale": stale,
            "updated_at": iso_utc(updated),
            "age_seconds": age,
            "error": error if stale else None,
            **common,
            **public_snapshot(snapshot, now),
        }, 200


class UsageHandler(BaseHTTPRequestHandler):
    server_version = "ClaudeUsage/" + VERSION

    def send_json(self, data: dict[str, Any], code: int = 200) -> None:
        body = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        origin = self.headers.get("Origin")
        if self.server.allowed_cors_origin and origin == self.server.allowed_cors_origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def safe_host(self) -> bool:
        host = self.headers.get("Host", "").split(":")[0].lower()
        return host in ("localhost", "127.0.0.1")

    def do_OPTIONS(self) -> None:
        origin = self.headers.get("Origin")
        if not self.safe_host() or not self.server.allowed_cors_origin or origin != self.server.allowed_cors_origin:
            self.send_json({"error": "CORS origin not allowed"}, 403)
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        if not self.safe_host():
            self.send_json({"error": "Invalid Host header"}, 403)
            return
        path = urlsplit(self.path).path
        if path == "/get":
            payload, status = self.server.cache.get()
            self.send_json(payload, status)
        elif path == "/health":
            payload, _ = self.server.cache.get()
            self.send_json({"healthy": payload["ok"], "updated_at": payload["updated_at"],
                            "error": payload.get("error")}, 200 if payload["ok"] else 503)
        elif path == "/":
            self.send_json({"service": "Claude/Claude Code usage API", "endpoint": "/get", "health": "/health",
                            "refresh_interval_seconds": self.server.cache.interval})
        else:
            self.send_json({"error": "Not found", "endpoints": ["/get", "/health"]}, 404)

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{iso_utc()}] {fmt % args}", flush=True)


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr: tuple[str, int], cache: UsageCache, allowed_cors_origin: str | None):
        super().__init__(addr, UsageHandler)
        self.cache = cache
        self.allowed_cors_origin = allowed_cors_origin


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve Claude/Claude Code usage at /get on localhost.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL)
    parser.add_argument("--credentials", type=pathlib.Path, help="Override Claude OAuth credential file")
    parser.add_argument("--utilization-scale", choices=["percent", "fraction"], default="percent",
                        help="How Anthropic reports utilization; default percent (0-100)")
    parser.add_argument("--cors-origin", help="Explicitly permit one browser origin (default: none)")
    parser.add_argument("--once", action="store_true", help="One request, print JSON, exit")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be 1-65535")
    if args.interval < 60:
        parser.error("--interval must be >= 60 to avoid rate limiting Claude's usage endpoint")
    home = pathlib.Path(os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude")).expanduser()
    credential_path = args.credentials or home / ".credentials.json"
    client = ClaudeUsageClient(credential_path, scale=args.utilization_scale)
    cache = UsageCache(client, args.interval)
    cache.refresh()
    if args.once:
        payload, status = cache.get()
        print(json.dumps(payload, indent=2))
        return 0 if status == 200 else 1
    threading.Thread(target=cache.run, daemon=True).start()
    if threading.current_thread() is threading.main_thread():
        def graceful_sigterm(_signal, _frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, graceful_sigterm)
    try:
        with LocalServer(("127.0.0.1", args.port), cache, args.cors_origin) as httpd:
            print(f"Serving http://localhost:{args.port}/get (poll every {args.interval}s, 429 backoff enabled)", flush=True)
            httpd.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nStopping.", flush=True)
    finally:
        cache.stopped.set()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
