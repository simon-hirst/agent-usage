"""Lightweight Qt import/paint smoke test; runs with QT_QPA_PLATFORM=offscreen."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from desktop.app import icon_for, local_reset

app = QApplication([])
for provider in ('codex', 'claude'):
    for window in ('five_hour', 'weekly'):
        for remaining in (None, 0.0, 54.5, 100.0):
            icon = icon_for(provider, window, remaining)
            assert not icon.isNull(), (provider, window, remaining)
print('Qt tray icon paint test passed')
