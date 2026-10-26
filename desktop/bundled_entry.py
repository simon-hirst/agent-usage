#!/usr/bin/env python3
"""Executable entrypoint for PyInstaller distributions and source smoke tests.

Modes are explicitly dispatched before Qt imports so the bundled executable can
supervise and serve the native APIs without creating a GUI window.
"""
from __future__ import annotations

import argparse  # required by included server scripts
import email.utils
import hashlib
import http.server
import json
import os
from pathlib import Path
import queue
import runpy
import shutil
import signal
import ssl
import subprocess
import sys
import threading
import urllib.error
import urllib.request

# Importing these modules explicitly guarantees their standard-library imports
# are present when the server scripts are run from bundled *data* at runtime.
from desktop.core import ROOT


def run_backend_server(service: str) -> int:
    folders = {"codex": "work-codex-usage-api", "claude": "claude-usage-api"}
    folder = folders.get(service)
    if not folder:
        return 2
    script = ROOT / folder / "server.py"
    if not script.is_file():
        raise FileNotFoundError(f"Bundled backend source missing: {script}")
    sys.argv = [str(script)] + sys.argv[3:]
    sys.path.insert(0, str(script.parent))
    runpy.run_path(str(script), run_name="__main__")
    return 0


def verify_bundle() -> int:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    for service in ("work-codex-usage-api", "claude-usage-api"):
        if not (ROOT / service / "server.py").is_file():
            raise RuntimeError(f"Missing {service} backend")
    if not (ROOT / "desktop" / "managed-wsl.sh").is_file():
        raise RuntimeError("Missing WSL supervisor")
    from PySide6.QtWidgets import QApplication
    from desktop.app import icon_for, combined_icon
    app = QApplication([])
    if combined_icon().isNull() or icon_for("codex", "five_hour", 73).isNull():
        raise RuntimeError("Qt icons failed to paint")
    app.quit()
    print("Packaged backend resources and Qt rendering verified", flush=True)
    return 0


def main() -> int:
    # Windowed PyInstaller executables may have no Python standard streams.
    # The embedded API scripts and their argparse parsers need writable streams.
    if len(sys.argv) >= 2 and sys.argv[1] in ('--backend-supervisor', '--backend-server', '--verify-bundle', '--direct-usage'):
        if sys.stdout is None:
            sys.stdout = open(os.devnull, 'w', encoding='utf-8')
        if sys.stderr is None:
            sys.stderr = open(os.devnull, 'w', encoding='utf-8')
    if len(sys.argv) >= 2:
        if sys.argv[1] == "--backend-supervisor":
            from desktop.managed_native import run
            return run(sys.argv[2] if len(sys.argv) == 3 else "")
        if sys.argv[1] == "--backend-server":
            return run_backend_server(sys.argv[2] if len(sys.argv) >= 3 else "")
        if sys.argv[1] == "--direct-usage":
            from desktop.direct_usage import run
            if len(sys.argv) == 5 and sys.argv[3] == '--output':
                return run(sys.argv[2], sys.argv[4])
            return 2  # Bundled reader must use an output file (no GUI stdout).
        if sys.argv[1] == "--verify-bundle":
            return verify_bundle()
    from desktop.app import main as gui_main
    return gui_main()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        import traceback
        from desktop.core import state_dir
        log_dir = state_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "tray-error.log").open("a", encoding="utf-8") as log:
            traceback.print_exc(file=log)
        raise
