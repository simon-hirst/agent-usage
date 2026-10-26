#!/usr/bin/env python3
"""A local, dependency-free HTTP bridge for ChatGPT Work / Codex usage.

Runs inside the same WSL distribution as an authenticated Codex CLI. Uses
Codex's documented app-server JSON-RPC interface; no token scraping required.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import queue
import signal
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

VERSION = "1.0.0"
POLL_SECONDS = 60
RPC_TIMEOUT_SECONDS = 25
UTC = dt.timezone.utc


def iso_utc(timestamp: float | None = None) -> str:
    instant = dt.datetime.fromtimestamp(time.time() if timestamp is None else timestamp, UTC)
    return instant.isoformat(timespec="seconds").replace("+00:00", "Z")


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    val = float(value)
    return val if math.isfinite(val) else None


def parse_window(window: Any) -> dict[str, Any] | None:
    if not isinstance(window, dict):
        return None
    used = finite_number(window.get("usedPercent"))
    if used is None:
        return None

    duration = finite_number(window.get("windowDurationMins"))
    resets_at = finite_number(window.get("resetsAt"))
    if resets_at is not None and resets_at > 1e11:  # accommodate epoch milliseconds
        resets_at /= 1000

    return {
        "used_percent": round(used, 2),
        "remaining_percent": round(max(0.0, min(100.0, 100.0 - used)), 2),
        "duration_minutes": int(duration) if duration is not None else None,
        "resets_at_unix": int(resets_at) if resets_at is not None else None,
    }


def window_kind(window: dict[str, Any]) -> str | None:
    minutes = window["duration_minutes"]
    if minutes is None:
        return None
    # Use durations, not primary/secondary positions: some plans expose weekly first.
    if 270 <= minutes <= 330:
        return "five_hour"
    if 9_000 <= minutes <= 11_000:
        return "weekly"
    return None


def collect_bucket(bucket: Any) -> dict[str, Any]:
    if not isinstance(bucket, dict):
        return {"name": None, "five_hour": None, "weekly": None, "other_windows": []}

    output: dict[str, Any] = {
        "name": bucket.get("limitName") if isinstance(bucket.get("limitName"), str) else None,
        "five_hour": None,
        "weekly": None,
        "other_windows": [],
    }
    reached = bucket.get("rateLimitReachedType")
    if isinstance(reached, (str, dict)):
        output["limit_reached_type"] = reached

    for key in ("primary", "secondary"):
        parsed = parse_window(bucket.get(key))
        if parsed is None:
            continue
        kind = window_kind(parsed)
        if kind and output[kind] is None:
            output[kind] = parsed
        else:
            output["other_windows"].append({"slot": key, **parsed})

    return output


def normalize_rate_limits(result: dict[str, Any]) -> dict[str, Any]:
    buckets: dict[str, Any] = {}
    by_id = result.get("rateLimitsByLimitId")
    if isinstance(by_id, dict):
        for bucket_id, data in by_id.items():
            if isinstance(bucket_id, str) and isinstance(data, dict):
                buckets[bucket_id] = collect_bucket(data)

    main = result.get("rateLimits")
    if isinstance(main, dict):
        bucket_id = main.get("limitId") or "codex"
        if isinstance(bucket_id, str) and bucket_id not in buckets:
            buckets[bucket_id] = collect_bucket(main)

    if not buckets:
        raise ValueError("Codex returned no rate-limit buckets. Sign in using `codex login`.")
    if not any(
        b["five_hour"] is not None or b["weekly"] is not None or b["other_windows"]
        for b in buckets.values()
    ):
        raise ValueError("Codex returned no usable usage windows for this account.")

    main_bucket = buckets.get("codex")
    if main_bucket is None:
        # Some accounts report their primary allowance under a different bucket ID.
        main_bucket = next(iter(buckets.values()))

    plan = result.get("planType")
    if not isinstance(plan, str):
        plan = None
    if plan is None:
        for data in (main, by_id.get("codex") if isinstance(by_id, dict) else None):
            if isinstance(data, dict) and isinstance(data.get("planType"), str):
                plan = data["planType"]
                break

    reset_credits = result.get("rateLimitResetCredits")
    reset_count = reset_credits.get("availableCount") if isinstance(reset_credits, dict) else None
    if not isinstance(reset_count, int) or isinstance(reset_count, bool):
        reset_count = None

    return {
        "plan": plan,
        "five_hour": main_bucket["five_hour"],
        "weekly": main_bucket["weekly"],
        "buckets": buckets,
        "reset_credits_available": reset_count,
    }


def public_window(window: dict[str, Any] | None, now: float) -> dict[str, Any] | None:
    if window is None:
        return None
    output = dict(window)
    timestamp = output.get("resets_at_unix")
    output["resets_at"] = iso_utc(timestamp) if timestamp is not None else None
    output["resets_in_seconds"] = max(0, math.ceil(timestamp - now)) if timestamp is not None else None
    return output


def public_snapshot(snapshot: dict[str, Any], now: float) -> dict[str, Any]:
    output = {key: value for key, value in snapshot.items() if key != "buckets"}
    for kind in ("five_hour", "weekly"):
        output[kind] = public_window(output[kind], now)
    output["buckets"] = {}
    for key, bucket in snapshot["buckets"].items():
        rendered = dict(bucket)
        for kind in ("five_hour", "weekly"):
            rendered[kind] = public_window(rendered[kind], now)
        rendered["other_windows"] = [
            {"slot": win["slot"], **public_window({k: v for k, v in win.items() if k != "slot"}, now)}
            for win in rendered["other_windows"]
        ]
        output["buckets"][key] = rendered
    return output


class CodexRpc:
    """A single-outstanding-request JSON-line client for `codex app-server`."""

    def __init__(self, command: list[str], timeout: float = RPC_TIMEOUT_SECONDS):
        self.command = command
        self.timeout = timeout
        self.process: subprocess.Popen[str] | None = None
        self.responses: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self.next_id = 1

    def close(self) -> None:
        process = self.process
        self.process = None
        if process is not None:
            try:
                process.terminate()
                process.wait(timeout=2)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    process.kill()
                    process.wait(timeout=2)
                except (subprocess.TimeoutExpired, OSError):
                    pass
        if process is not None:
            for pipe in (process.stdin, process.stdout):
                if pipe is not None and not pipe.closed:
                    try:
                        pipe.close()
                    except OSError:
                        pass
        self.responses = queue.Queue()

    def _read_stdout(self, process: subprocess.Popen[str], response_queue: queue.Queue) -> None:
        try:
            assert process.stdout is not None
            for line in process.stdout:
                try:
                    message = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if isinstance(message, dict) and "id" in message:
                    response_queue.put(message)
        finally:
            response_queue.put(None)

    def _send(self, message: dict[str, Any]) -> None:
        assert self.process is not None and self.process.stdin is not None
        self.process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def _request(self, method: str, params: Any = None) -> Any:
        request_id = self.next_id
        self.next_id += 1
        request = {"id": request_id, "method": method}
        if params is not None:
            request["params"] = params
        self._send(request)

        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Codex app-server timed out on {method}")
            try:
                reply = self.responses.get(timeout=remaining)
            except queue.Empty as exc:
                raise TimeoutError(f"Codex app-server timed out on {method}") from exc
            if reply is None:
                raise RuntimeError("Codex app-server exited unexpectedly")
            if reply.get("id") != request_id:
                continue
            if "error" in reply:
                error = reply["error"]
                detail = error.get("message", str(error)) if isinstance(error, dict) else str(error)
                raise RuntimeError(f"Codex app-server {method}: {detail[:250]}")
            return reply.get("result")

    def _start(self) -> None:
        self.close()
        if not shutil.which(self.command[0]) and not os.path.isfile(self.command[0]):
            raise RuntimeError("`codex` not found in PATH. Start this service in the WSL shell where Codex works.")
        process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self.process = process
        self.responses = queue.Queue()
        threading.Thread(target=self._read_stdout, args=(process, self.responses), daemon=True).start()
        self._request("initialize", {
            "clientInfo": {"name": "work_codex_usage_bridge", "title": "Work Codex Usage Bridge", "version": VERSION}
        })
        self._send({"method": "initialized", "params": {}})

    def get_limits(self) -> dict[str, Any]:
        try:
            if self.process is None or self.process.poll() is not None:
                self._start()
            result = self._request("account/rateLimits/read")
            if not isinstance(result, dict):
                raise ValueError("Unexpected response from Codex (not an object).")
            return normalize_rate_limits(result)
        except Exception:
            self.close()
            raise


class UsageCache:
    def __init__(self, codex: CodexRpc, interval: int = POLL_SECONDS):
        self.codex = codex
        self.interval = interval
        self.lock = threading.Lock()
        self.snapshot: dict[str, Any] | None = None
        self.last_updated: float | None = None
        self.last_error: str | None = None
        self.failed_at: float | None = None
        self.stop_event = threading.Event()

    def refresh(self) -> None:
        try:
            new_snapshot = self.codex.get_limits()
        except Exception as exc:
            message = f"{type(exc).__name__}: {str(exc)[:300]}"
            with self.lock:
                self.last_error = message
                self.failed_at = time.time()
            print(f"[{iso_utc()}] Refresh failed: {message}", file=sys.stderr, flush=True)
            return

        now = time.time()
        with self.lock:
            self.snapshot = new_snapshot
            self.last_updated = now
            self.last_error = None
            self.failed_at = None
        print(f"[{iso_utc(now)}] Usage refreshed", file=sys.stderr, flush=True)

    def run(self) -> None:
        while not self.stop_event.wait(self.interval):
            self.refresh()

    def get(self) -> tuple[dict[str, Any], int]:
        now = time.time()
        with self.lock:
            data = self.snapshot
            updated = self.last_updated
            error = self.last_error
            failed = self.failed_at

        if data is None:
            return {
                "ok": False,
                "stale": True,
                "updated_at": None,
                "age_seconds": None,
                "refresh_interval_seconds": self.interval,
                "error": error or "Initial usage refresh has not completed.",
                "five_hour": None,
                "weekly": None,
            }, 503

        age = int(max(0, now - updated))
        # A failed refresh invalidates the cached reading even when the failure
        # and preceding success get identical wall-clock timestamps (possible on
        # Windows due to clock resolution). A successful refresh clears failed_at.
        stale = age >= self.interval * 2 or failed is not None
        return {
            "ok": not stale,
            "source": "codex-app-server",
            "updated_at": iso_utc(updated),
            "age_seconds": age,
            "refresh_interval_seconds": self.interval,
            "stale": stale,
            "error": error if stale else None,
            **public_snapshot(data, now),
        }, 200


class UsageHandler(BaseHTTPRequestHandler):
    server_version = "WorkCodexUsage/" + VERSION

    def send_json(self, data: dict[str, Any], status: int = 200) -> None:
        payload = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        origin = self.headers.get("Origin")
        if self.server.allowed_cors_origin is not None and origin == self.server.allowed_cors_origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self) -> None:
        origin = self.headers.get("Origin")
        if not self.server.allowed_cors_origin or origin != self.server.allowed_cors_origin:
            self.send_json({"error": "CORS origin not allowed"}, 403)
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/get":
            body, status = self.server.cache.get()
            self.send_json(body, status)
        elif path == "/health":
            body, status = self.server.cache.get()
            self.send_json({"healthy": status == 200 and body["ok"], "updated_at": body["updated_at"], "error": body.get("error")},
                           200 if body["ok"] else 503)
        elif path == "/":
            self.send_json({"service": "Work/Codex usage API", "endpoint": "/get", "health": "/health", "interval_seconds": self.server.cache.interval})
        else:
            self.send_json({"error": "Not found", "endpoints": ["/get", "/health"]}, 404)

    def log_message(self, fmt: str, *args: Any) -> None:
        print("[%s] %s" % (iso_utc(), fmt % args), flush=True)


class UsageHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], cache: UsageCache, allowed_cors_origin: str | None):
        super().__init__(address, UsageHandler)
        self.cache = cache
        self.allowed_cors_origin = allowed_cors_origin


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve local ChatGPT Work/Codex limits as JSON.")
    parser.add_argument("--port", type=int, default=3789, help="HTTP port (default: 3789)")
    parser.add_argument("--interval", type=int, default=POLL_SECONDS, help="Refresh interval in seconds (default: 60)")
    parser.add_argument("--cors-origin", help="Allow one specific browser origin (e.g. http://localhost:3000)")
    parser.add_argument("--once", action="store_true", help="Fetch and print JSON once, without starting HTTP server")
    parser.add_argument("--codex-path", default="codex", help="Path to codex executable (default: codex)")
    args = parser.parse_args()
    if not (1 <= args.port <= 65535):
        parser.error("--port must be between 1 and 65535")
    if args.interval < 10:
        parser.error("--interval must be at least 10 seconds")

    codex = CodexRpc([args.codex_path, "app-server"])
    cache = UsageCache(codex, args.interval)
    if threading.current_thread() is threading.main_thread():
        def graceful_sigterm(_signal, _frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, graceful_sigterm)
    try:
        cache.refresh()
        if args.once:
            response, status = cache.get()
            print(json.dumps(response, indent=2))
            return 0 if status == 200 else 1
        worker = threading.Thread(target=cache.run, daemon=True)
        worker.start()
        with UsageHTTPServer(("127.0.0.1", args.port), cache, args.cors_origin) as httpd:
            print(f"Serving http://localhost:{args.port}/get (refresh every {args.interval}s)", flush=True)
            try:
                httpd.serve_forever(poll_interval=0.25)
            except KeyboardInterrupt:
                print("\nStopping.", flush=True)
    finally:
        cache.stop_event.set()
        codex.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
