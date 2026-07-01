"""Dependency-free presentation, network and cross-platform configuration helpers."""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import re
import sys
from typing import Any

SERVICES = {
    "codex": {"name": "Codex", "port": 3789, "folder": "work-codex-usage-api", "letter": "C"},
    "claude": {"name": "Claude", "port": 3790, "folder": "claude-usage-api", "letter": "A"},
}
ROOT = Path(__file__).resolve().parent.parent
APP_ID = "codex-claude-usage"


def app_data_dir(system: str | None = None, environ: dict[str, str] | None = None,
                 home: Path | None = None) -> Path:
    system = system or platform.system()
    env = os.environ if environ is None else environ
    home = home or Path.home()
    if system == "Windows":
        return Path(env.get("APPDATA") or (home / "AppData" / "Roaming")) / "CodexClaudeUsage"
    if system == "Darwin":
        return home / "Library" / "Application Support" / "CodexClaudeUsage"
    return Path(env.get("XDG_CONFIG_HOME") or (home / ".config")) / APP_ID


def state_dir(system: str | None = None) -> Path:
    system = system or platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Logs" / "CodexClaudeUsage"
    if system == "Windows":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "CodexClaudeUsage" / "logs"
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))) / APP_ID


DEFAULTS = {"show_weekly": True, "manage_backends": True, "wsl_distro": "Debian"}


def load_settings(path: Path | None = None) -> dict[str, Any]:
    path = path or (app_data_dir() / "settings.json")
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    out = DEFAULTS.copy()
    for field in ("show_weekly", "manage_backends"):
        if isinstance(raw.get(field), bool):
            out[field] = raw[field]
    value = raw.get("wsl_distro")
    if isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9._-]{1,80}", value):
        out["wsl_distro"] = value
    return out


def save_settings(settings: dict[str, Any], path: Path | None = None) -> None:
    path = path or (app_data_dir() / "settings.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps({k: settings[k] for k in DEFAULTS}, indent=2), encoding="utf-8")
    temp.replace(path)


def secure_child_env(environ: dict[str, str] | None = None, system: str | None = None) -> dict[str, str]:
    """Avoid Windows CreateProcess's 32K UTF-16 environment-block limit.

    Keep Windows PATH where reasonable so wsl.exe is found, omit enormous
    inherited build variables, and add common native CLI installation paths.
    Does not change the parent process environment.
    """
    env = dict(os.environ if environ is None else environ)
    system = system or platform.system()
    if system == "Windows":
        allow = (
            "SystemRoot", "windir", "SystemDrive", "ComSpec", "Path", "PATHEXT", "TEMP", "TMP", "USERPROFILE",
            "APPDATA", "LOCALAPPDATA", "HOMEDRIVE", "HOMEPATH", "OS", "PROCESSOR_ARCHITECTURE",
            "NUMBER_OF_PROCESSORS", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "CommonProgramFiles",
            "CommonProgramFiles(x86)", "WSLENV", "LANG", "LC_ALL", "TERM",
        )
        approved = {name.lower() for name in allow}
        env = {k: v for k, v in env.items() if k.lower() in approved and len(v) <= 10000}
        windows = next((v for k, v in env.items() if k.lower() == "systemroot"), r"C:\Windows")
        path_key = next((k for k in env if k.lower() == "path"), "Path")
        if len(env.get(path_key, "")) > 10000 or not env.get(path_key):
            env[path_key] = windows + r"\System32;" + windows + ";" + windows + r"\System32\Wbem"
        # Bad WSLENV values can propagate sensitive/unwanted variables into WSL.
        env = {k: v for k, v in env.items() if k.lower() != "wslenv"}
    else:
        candidates = [
            str(Path.home() / ".local" / "bin"), str(Path.home() / ".npm-global" / "bin"),
            str(Path.home() / ".volta" / "bin"),
            str(Path.home() / ".asdf" / "shims"),
            str(Path.home() / ".bun" / "bin"),
            str(Path.home() / ".local" / "share" / "mise" / "shims"),
            "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin",
        ]
        # Login startup managers don't inherit shell rc PATH additions. Discover
        # common nvm Node installs so `codex` remains available after login.
        nvm = Path.home() / ".nvm" / "versions" / "node"
        if nvm.is_dir():
            candidates.extend(str(p / "bin") for p in sorted(nvm.iterdir(), reverse=True) if p.is_dir())
        current = env.get("PATH", "")
        env["PATH"] = os.pathsep.join(dict.fromkeys(p for p in current.split(os.pathsep) + candidates if p))
    return env


def parse_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Only surface numbers from fresh, successful API responses."""
    if not isinstance(payload, dict) or payload.get("ok") is not True or payload.get("stale") is True:
        reason = str(payload.get("error") or "API unavailable or data stale") if isinstance(payload, dict) else "Invalid JSON"
        return {"ok": False, "error": reason[:220], "five_hour": None, "weekly": None}
    result: dict[str, Any] = {"ok": True, "error": None, "five_hour": None, "weekly": None}
    for field in ("five_hour", "weekly"):
        window = payload.get(field)
        if not isinstance(window, dict):
            continue
        remaining = window.get("remaining_percent")
        if not isinstance(remaining, (int, float)) or isinstance(remaining, bool) or not 0 <= remaining <= 100:
            continue
        result[field] = {"remaining_percent": float(remaining), "resets_at": window.get("resets_at")}
    return result
