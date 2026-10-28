"""Lightweight Qt import/paint/dialog smoke test, run with QT_QPA_PLATFORM=offscreen."""
import os
import pathlib
import sys
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from desktop.app import icon_for, combined_icon, local_reset, ProviderSelection, QuickView, Dashboard, TrayController
from desktop.core import PROVIDERS, load_settings

app = QApplication([])
for provider in PROVIDERS:
    for field in ('five_hour', 'weekly'):
        for remaining in (None, 0.0, 54.5, 100.0):
            assert not icon_for(provider, field, remaining).isNull()
assert not icon_for("claude", "five_hour", 62.0, stale=True).isNull()
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

# Check the actual controller updates tooltip text on both standalone and merged icons.
class FakeTray:
    def setIcon(self, icon):
        assert not icon.isNull()
    def setToolTip(self, text):
        self.tooltip = text

class FakeView:
    def isVisible(self): return False

tray_controller = TrayController.__new__(TrayController)
tray_controller.settings = {'selected_providers': ['codex']}
tray_controller.snapshots = {}
tray_controller.merged_tray = FakeTray()
tray_controller.trays = {('codex', 'five_hour'): FakeTray(), ('codex', 'weekly'): FakeTray()}
tray_controller.quick = FakeView()
tray_controller.dashboard = FakeView()
tray_controller.set_snapshot('codex', {
    'ok': True,
    'five_hour': {'remaining_percent': 65, 'resets_at': '2026-10-26T17:30:00Z'},
    'weekly': {'remaining_percent': 34, 'resets_at': '2026-10-30T23:00:00Z'},
})
for tray in tray_controller.trays.values():
    assert '5h:' in tray.tooltip and '7d:' in tray.tooltip
    assert '26 Oct' in tray.tooltip and '30 Oct' in tray.tooltip
assert 'Codex:' in tray_controller.merged_tray.tooltip
assert '5h' in tray_controller.merged_tray.tooltip and '7d' in tray_controller.merged_tray.tooltip

print('Qt tray icon, local reset hover tooltips, setup, quick view and dashboard smoke test passed')
