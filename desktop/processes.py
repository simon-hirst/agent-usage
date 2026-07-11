"""Own backend subprocesses; never terminate servers we did not start."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import signal
import socket
import subprocess
import sys
import time
from typing import Any

from .core import ROOT, SERVICES, secure_child_env, state_dir


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


class BackendManager:
    def __init__(self, root: Path = ROOT, system: str | None = None, wsl_distro: str = "Debian"):
        self.root = Path(root).resolve()
        self.system = system or platform.system()
        self.wsl_distro = wsl_distro
        self.children: dict[str, subprocess.Popen] = {}
        self.last_start: dict[str, float] = {}
        self.log_paths: dict[str, Path] = {}
        self.errors: dict[str, str] = {}
        self.enabled = True

    def _cmd(self, service: str) -> list[str]:
        if self.system == "Windows":
            # WSL maps cwd automatically. No Windows path is passed as a shell argument.
            # bash -i sources the same profile as the user's existing CLI login.
            return ["wsl.exe", "-d", self.wsl_distro, "--", "bash", "-i", "./desktop/managed-wsl.sh", service]
        return [sys.executable, str(self.root / "desktop" / "managed_native.py"), service]

    def ensure_running(self) -> None:
        if not self.enabled:
            return
        for service, meta in SERVICES.items():
            child = self.children.get(service)
            if child is not None and child.poll() is not None:
                self.children.pop(service, None)
                try:
                    child.stdin.close() if child.stdin else None
                except OSError:
                    pass
            if service in self.children:
                continue
            # Do not replace/kill a user's existing standalone API process.
            if port_open(meta["port"]):
                continue
            if time.monotonic() - self.last_start.get(service, -1e10) < 20:
                continue
            self.last_start[service] = time.monotonic()
            try:
                logs = state_dir(self.system)
                logs.mkdir(parents=True, exist_ok=True)
                log_path = logs / f"{service}.log"
                self.log_paths[service] = log_path
                # Opening logs inside Python avoids attaching a console. The WSL
                # wrapper also writes its own logs to $HOME/.local/state.
                log = log_path.open("ab", buffering=0)
                try:
                    kwargs: dict[str, Any] = {
                        "cwd": self.root,
                        "stdin": subprocess.PIPE,
                        "stdout": log,
                        "stderr": subprocess.STDOUT,
                        "env": secure_child_env(system=self.system),
                    }
                    if self.system == "Windows":
                        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    self.children[service] = subprocess.Popen(self._cmd(service), **kwargs)
                finally:
                    log.close()
                self.errors.pop(service, None)
            except (OSError, ValueError) as exc:
                self.errors[service] = f"Cannot start {service}: {exc}"

    def stop(self) -> None:
        self.enabled = False
        children, self.children = self.children, {}
        for child in children.values():
            if child.poll() is None and child.stdin:
                try:
                    child.stdin.write(b"stop\n")
                    child.stdin.flush()
                except OSError:
                    pass
                try:
                    child.stdin.close()
                except OSError:
                    pass
        for child in children.values():
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # Only our wrapper process; user-started services are untouched.
                try:
                    child.terminate()
                    child.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        child.kill()
                        child.wait(timeout=2)
                    except OSError:
                        pass
