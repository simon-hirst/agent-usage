"""Per-user login startup, with no administrator privileges."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import plistlib
import sys

from .core import ROOT

WIN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
WIN_NAME = "CodexClaudeUsageQt"
MAC_LABEL = "local.codex-claude-usage.tray"


def destination(system: str | None = None, home: Path | None = None) -> Path | None:
    system, home = system or platform.system(), home or Path.home()
    if system == "Darwin":
        return home / "Library" / "LaunchAgents" / (MAC_LABEL + ".plist")
    if system == "Linux":
        config = Path(os.environ.get("XDG_CONFIG_HOME") or (home / ".config"))
        return config / "autostart" / "codex-claude-usage.desktop"
    return None


def enabled(system: str | None = None) -> bool:
    system = system or platform.system()
    if system == "Windows":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WIN_KEY) as key:
                val, _ = winreg.QueryValueEx(key, WIN_NAME)
                return bool(val)
        except OSError:
            return False
    return destination(system).is_file()


def set_enabled(enable: bool, root: Path = ROOT, system: str | None = None,
                home: Path | None = None) -> None:
    system = system or platform.system()
    root = Path(root).resolve()
    if system == "Windows":
        import winreg
        if enable:
            # Hidden PowerShell bootstrap handles huge env blocks and doesn't
            # leave a foreground console window open.
            shell = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
            command = f'"{shell}" -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{root / "start-windows.ps1"}" -NoConsole'
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, WIN_KEY) as key:
            if enable:
                winreg.SetValueEx(key, WIN_NAME, 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, WIN_NAME)
                except FileNotFoundError:
                    pass
        return
    path = destination(system, home)
    if path is None:
        raise OSError(f"Unsupported system: {system}")
    if not enable:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if system == "Darwin":
        launcher = str(root / ".venv" / "bin" / "python")
        source = str(root / "desktop" / "run_app.py")
        payload = {
            "Label": MAC_LABEL,
            "ProgramArguments": [launcher, source],
            "WorkingDirectory": str(root),
            "RunAtLoad": True,
            "KeepAlive": False,
        }
        path.write_bytes(plistlib.dumps(payload))
    else:
        launch = str(root / "start-linux.sh")
        # Escape characters per the desktop-file quoting convention.
        escaped = launch.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
        contents = "[Desktop Entry]\nType=Application\nName=Codex + Claude Usage Tray\n" + f'Exec="{escaped}"\n' + "Terminal=false\nX-GNOME-Autostart-enabled=true\n"
        path.write_text(contents, encoding="utf-8")
