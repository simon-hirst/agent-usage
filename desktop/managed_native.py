#!/usr/bin/env python3
"""Child supervisor: parent tray owns this process via stdin pipe.

When the parent exits abruptly, stdin EOF shuts down the backend too.
"""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

THIS = Path(__file__).resolve().parent
ROOT = Path(getattr(sys, "_MEIPASS", THIS.parent))
SERVICES = {"codex": "work-codex-usage-api", "claude": "claude-usage-api"}


def run(service: str) -> int:
    if service not in SERVICES:
        return 2
    folder = ROOT / SERVICES[service]
    if getattr(sys, "frozen", False):
        # A release contains its own Python runtime. No system Python needed.
        cmd = [sys.executable, "--backend-server", service]
    else:
        cmd = [sys.executable, "-u", str(folder / "server.py")]
    kwargs = {"cwd": folder, "stdin": subprocess.DEVNULL}
    if os.name != "nt":
        kwargs["start_new_session"] = True
    child = subprocess.Popen(cmd, **kwargs)
    stop = threading.Event()

    def watch_pipe() -> None:
        try:
            while True:
                line = sys.stdin.buffer.readline()
                if not line or line.strip() == b"stop":
                    break
        except (OSError, ValueError):
            pass
        stop.set()

    thread = threading.Thread(target=watch_pipe, daemon=True)
    thread.start()
    try:
        while child.poll() is None and not stop.wait(0.25):
            pass
    finally:
        if child.poll() is None:
            if os.name != "nt":
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            else:
                child.terminate()
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                if os.name != "nt":
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    child.kill()
                child.wait(timeout=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1] if len(sys.argv) == 2 else ""))
