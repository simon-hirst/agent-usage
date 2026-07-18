#!/usr/bin/env python3
"""Direct script entry for platform startup managers."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from desktop.app import main

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        # pythonw.exe has no console; record startup errors in a per-user log.
        import traceback
        from desktop.core import state_dir
        log_dir = state_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "tray-error.log").open("a", encoding="utf-8") as log:
            traceback.print_exc(file=log)
        raise
