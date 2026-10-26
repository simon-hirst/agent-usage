"""Lightweight Qt import/paint/dialog smoke test, run with QT_QPA_PLATFORM=offscreen."""
import os
import pathlib
import sys
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from desktop.app import icon_for, combined_icon, local_reset, ProviderSelection, QuickView, Dashboard
from desktop.core import PROVIDERS, load_settings

app = QApplication([])
for provider in PROVIDERS:
    for field in ('five_hour', 'weekly'):
        for remaining in (None, 0.0, 54.5, 100.0):
            assert not icon_for(provider, field, remaining).isNull()
assert not combined_icon().isNull()
settings = load_settings(ROOT / 'nonexistent-settings-for-smoke.json')
settings['selected_providers'] = ['codex', 'claude', 'deepseek']
setup = ProviderSelection(settings, first_run=True)
assert len(setup.boxes) >= 10
setup.close()
class Stub:
    def __init__(self):
        self.settings = settings
        self.snapshots = {'codex': {'ok': True, 'five_hour': {'remaining_percent': 65, 'resets_at': None}}}
        self.tray_available = True
    def poll(self): pass
    def show_dashboard(self): pass
    def settings_dialog(self): pass
    def exit_app(self): pass
controller = Stub()
quick = QuickView(controller)
quick.redraw()
quick.close()
dashboard = Dashboard(controller)
dashboard.redraw()
dashboard.hide()
print('Qt tray icon, first-run setup, quick view and dashboard smoke test passed')
