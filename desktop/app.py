"""Cross-platform Qt system tray + dashboard; backend processes are owned here."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import sys
from typing import Any

from PySide6.QtCore import Qt, QLockFile, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from .autostart import enabled as autostart_enabled, set_enabled as set_autostart
from .core import ROOT, SERVICES, app_data_dir, load_settings, parse_response, save_settings
from .processes import BackendManager

COLOURS = {"codex": "#168466", "claude": "#BE6849"}


def icon_for(service: str, field: str, remaining: float | None) -> QIcon:
    """Transparent tray icon that shows only the remaining percentage number."""
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    colour = QColor(COLOURS[service])
    font = QFont("Arial", 34 if remaining is None or remaining >= 100 else 38, QFont.Weight.Bold)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    painter.setFont(font)
    number = "--" if remaining is None else str(int(round(remaining)))
    rect = pix.rect()

    # subtle outline so the coloured number stays readable on light or dark trays
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        painter.setPen(QColor(0, 0, 0, 85))
        painter.drawText(rect.adjusted(dx, dy, dx, dy), Qt.AlignmentFlag.AlignCenter, number)

    painter.setPen(colour)
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, number)
    painter.end()
    return QIcon(pix)


def local_reset(iso: Any) -> str:
    if not isinstance(iso, str) or not iso:
        return "Reset time not available"
    try:
        stamp = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return "Resets " + stamp.astimezone().strftime("%a %d %b at %H:%M")
    except ValueError:
        return "Reset time not available"


class Dashboard(QDialog):
    def __init__(self, controller: "TrayController"):
        super().__init__()
        self.controller = controller
        self.setWindowTitle("Codex + Claude — quota remaining")
        self.setMinimumWidth(420)
        self.setWindowIcon(icon_for("codex", "five_hour", None))
        outer = QVBoxLayout(self)
        title = QLabel("Codex + Claude usage")
        title.setStyleSheet("font-size: 21px; font-weight: 700; padding-bottom: 4px;")
        outer.addWidget(title)
        outer.addWidget(QLabel("Percentages are remaining, not used. Updated by the local APIs."))
        self.widgets: dict[tuple[str, str], tuple[QProgressBar, QLabel]] = {}
        self.status_labels: dict[str, QLabel] = {}
        for service, meta in SERVICES.items():
            group = QGroupBox(meta["name"])
            layout = QVBoxLayout(group)
            status = QLabel("Connecting…")
            self.status_labels[service] = status
            layout.addWidget(status)
            for field, label in (("five_hour", "5-hour allowance"), ("weekly", "Weekly allowance")):
                row = QHBoxLayout()
                row.addWidget(QLabel(label))
                details = QLabel("--")
                details.setAlignment(Qt.AlignmentFlag.AlignRight)
                row.addWidget(details)
                layout.addLayout(row)
                bar = QProgressBar()
                bar.setMinimum(0)
                bar.setMaximum(100)
                bar.setValue(0)
                bar.setFormat("--")
                bar.setStyleSheet(f"QProgressBar::chunk {{background-color: {COLOURS[service]};}}")
                layout.addWidget(bar)
                self.widgets[(service, field)] = (bar, details)
            outer.addWidget(group)
        actions = QHBoxLayout()
        refresh = QPushButton("Refresh display")
        refresh.clicked.connect(controller.poll)
        actions.addWidget(refresh)
        settings = QPushButton("Settings")
        settings.clicked.connect(controller.settings_dialog)
        actions.addWidget(settings)
        hide = QPushButton("Hide")
        hide.clicked.connect(self.hide)
        actions.addWidget(hide)
        outer.addLayout(actions)

    def closeEvent(self, event):
        if self.controller.tray_available:
            self.hide()
            event.ignore()
        else:
            self.controller.exit_app()
            event.accept()

    def redraw(self) -> None:
        for service in SERVICES:
            data = self.controller.snapshots.get(service) or {"ok": False}
            status = self.status_labels[service]
            if data.get("ok"):
                status.setText("Online · last cached reading is fresh")
            else:
                reason = str(data.get("error") or "Waiting for backend")[:180]
                status.setText(f"Offline / stale: {reason}")
            for field in ("five_hour", "weekly"):
                bar, detail = self.widgets[(service, field)]
                window = data.get(field) if data.get("ok") else None
                if not window:
                    bar.setValue(0)
                    bar.setFormat("--")
                    detail.setText("Not available")
                    continue
                n = window["remaining_percent"]
                bar.setValue(round(n))
                bar.setFormat(f"{n:g}% left")
                detail.setText(local_reset(window.get("resets_at")))


class SettingsDialog(QDialog):
    def __init__(self, controller: "TrayController"):
        super().__init__(controller.dashboard)
        self.setWindowTitle("Usage Tray settings")
        self.setMinimumWidth(385)
        layout = QVBoxLayout(self)
        self.show_weekly = QCheckBox("Show weekly icons in tray (four instead of two)")
        self.show_weekly.setChecked(controller.settings["show_weekly"])
        layout.addWidget(self.show_weekly)
        self.manage = QCheckBox("Automatically run both APIs in the background")
        self.manage.setChecked(controller.settings["manage_backends"])
        layout.addWidget(self.manage)
        self.startup = QCheckBox("Start automatically when signing in")
        self.startup.setChecked(autostart_enabled())
        layout.addWidget(self.startup)
        form = QFormLayout()
        self.distro = QLineEdit(controller.settings["wsl_distro"])
        self.distro.setToolTip("Windows only. Must be a WSL distro with Codex and Claude Code signed in.")
        form.addRow("WSL distribution (Windows):", self.distro)
        layout.addLayout(form)
        layout.addWidget(QLabel("Managed API processes stop when you Exit the tray app.\nExisting independently started servers are never terminated."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        import re
        name = self.distro.text().strip()
        if not re.fullmatch(r"[a-zA-Z0-9._-]{1,80}", name):
            QMessageBox.warning(self, "Invalid distro", "Use a valid WSL distribution name such as Debian.")
            return
        try:
            set_autostart(self.startup.isChecked())
        except OSError as exc:
            QMessageBox.warning(self, "Startup setting failed", str(exc))
            return
        c = self.parent().controller
        c.settings.update({"show_weekly": self.show_weekly.isChecked(), "manage_backends": self.manage.isChecked(), "wsl_distro": name})
        save_settings(c.settings)
        c.manager.wsl_distro = name
        if not c.settings["manage_backends"]:
            c.manager.stop()
        elif not c.manager.enabled:
            c.manager = BackendManager(root=ROOT, wsl_distro=name)
            c.manager.ensure_running()
        c.apply_visibility()
        c.update_menus()
        super().accept()


class TrayController:
    def __init__(self, app: QApplication):
        self.app = app
        self.app.setQuitOnLastWindowClosed(False)
        self.settings = load_settings()
        self.manager = BackendManager(wsl_distro=self.settings["wsl_distro"])
        self.manager.enabled = self.settings["manage_backends"]
        self.snapshots: dict[str, dict[str, Any]] = {}
        self.tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        self.net = QNetworkAccessManager(self.app)
        self.trays: dict[tuple[str, str], QSystemTrayIcon] = {}
        self.menus: list[QMenu] = []
        self.weekly_actions: list[QAction] = []
        self.startup_actions: list[QAction] = []
        self.dashboard = Dashboard(self)
        for service in SERVICES:
            for field in ("five_hour", "weekly"):
                tray = QSystemTrayIcon(self.app)
                tray.setIcon(icon_for(service, field, None))
                label = "5-hour" if field == "five_hour" else "weekly"
                tray.setToolTip(f"{SERVICES[service]['name']} {label}: waiting for data")
                menu = QMenu()
                heading = QAction(f"{SERVICES[service]['name']} — {'5-hour' if field == 'five_hour' else 'weekly'} remaining", menu)
                heading.setEnabled(False)
                menu.addAction(heading)
                menu.addSeparator()
                dashboard_action = menu.addAction("Open dashboard")
                dashboard_action.triggered.connect(self.show_dashboard)
                weekly_action = menu.addAction("Show weekly tray icons")
                weekly_action.setCheckable(True)
                weekly_action.triggered.connect(self.toggle_weekly)
                self.weekly_actions.append(weekly_action)
                startup_action = menu.addAction("Start with my computer")
                startup_action.setCheckable(True)
                startup_action.triggered.connect(self.toggle_autostart)
                self.startup_actions.append(startup_action)
                settings_action = menu.addAction("Settings…")
                settings_action.triggered.connect(self.settings_dialog)
                menu.addSeparator()
                exit_action = menu.addAction("Exit — stop managed APIs")
                exit_action.triggered.connect(self.exit_app)
                tray.setContextMenu(menu)
                tray.activated.connect(self.on_activated)
                self.trays[(service, field)] = tray
                self.menus.append(menu)
        self.update_menus()
        self.apply_visibility()
        self.refresh_timer = QTimer(self.app)
        self.refresh_timer.timeout.connect(self.poll)
        self.refresh_timer.start(60_000)
        self.boot_timer = QTimer(self.app)
        self.boot_timer.timeout.connect(self.poll)
        self.boot_checks = 0
        self.boot_timer.start(8_000)
        self.app.aboutToQuit.connect(lambda: self.manager.stop())
        self.manager.ensure_running()
        self.poll()
        if not self.tray_available:
            self.dashboard.show()
            QMessageBox.information(self.dashboard, "System tray unavailable",
                                    "Your desktop currently has no supported system tray. The dashboard will stay open.\n"
                                    "On GNOME/Wayland, you may need an AppIndicator extension.")

    def on_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_dashboard()

    def show_dashboard(self):
        self.dashboard.redraw()
        self.dashboard.show()
        self.dashboard.raise_()
        self.dashboard.activateWindow()

    def update_menus(self):
        for action in self.weekly_actions:
            action.setChecked(self.settings["show_weekly"])
        for action in self.startup_actions:
            action.setChecked(autostart_enabled())

    def toggle_weekly(self, checked):
        self.settings["show_weekly"] = bool(checked)
        save_settings(self.settings)
        self.update_menus()
        self.apply_visibility()

    def toggle_autostart(self, checked):
        try:
            set_autostart(bool(checked))
        except OSError as exc:
            QMessageBox.warning(self.dashboard, "Startup setting failed", str(exc))
        self.update_menus()

    def apply_visibility(self):
        for (service, field), tray in self.trays.items():
            tray.setVisible(self.tray_available and (field != "weekly" or self.settings["show_weekly"]))

    def settings_dialog(self):
        SettingsDialog(self).exec()

    def poll(self):
        self.manager.ensure_running()
        if self.boot_timer.isActive():
            self.boot_checks += 1
            if self.boot_checks >= 15 or all(self.snapshots.get(s, {}).get("ok") for s in SERVICES):
                self.boot_timer.stop()
        for service, meta in SERVICES.items():
            request = QNetworkRequest(QUrl(f"http://127.0.0.1:{meta['port']}/get"))
            request.setTransferTimeout(4500)
            reply = self.net.get(request)
            reply.finished.connect(lambda r=reply, s=service: self.consume(s, r))

    def consume(self, service: str, reply: QNetworkReply):
        try:
            data = bytes(reply.readAll())
            if len(data) > 262_144:
                raise ValueError("Response too large")
            if reply.error() != QNetworkReply.NetworkError.NoError:
                raise ValueError(reply.errorString())
            snapshot = parse_response(json.loads(data.decode("utf-8")))
        except (ValueError, UnicodeError) as exc:
            snapshot = {"ok": False, "error": str(exc)[:200], "five_hour": None, "weekly": None}
        finally:
            reply.deleteLater()
        self.snapshots[service] = snapshot
        for field in ("five_hour", "weekly"):
            window = snapshot.get(field) if snapshot["ok"] else None
            remaining = window["remaining_percent"] if window else None
            tray = self.trays[(service, field)]
            tray.setIcon(icon_for(service, field, remaining))
            label = "5-hour" if field == "five_hour" else "weekly"
            if remaining is None:
                detail = str(snapshot.get("error") or "Window unavailable")
                tray.setToolTip(f"{SERVICES[service]['name']} {label}: -- ({detail[:100]})")
            else:
                tray.setToolTip(f"{SERVICES[service]['name']} {label}: {remaining:g}% remaining\n{local_reset(window.get('resets_at'))}")
        if self.dashboard.isVisible():
            self.dashboard.redraw()

    def exit_app(self):
        self.refresh_timer.stop()
        self.boot_timer.stop()
        for tray in self.trays.values():
            tray.hide()
        self.manager.stop()
        self.app.quit()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Codex Claude Usage")
    app.setOrganizationName("Local Usage Monitor")
    lockpath = app_data_dir() / "tray.lock"
    lockpath.parent.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(lockpath))
    lock.setStaleLockTime(30_000)
    if not lock.tryLock(0):
        return 0  # Another copy is already running. Do not duplicate backends.
    controller = None
    try:
        controller = TrayController(app)
        return app.exec()
    finally:
        if controller is not None:
            controller.manager.stop()
        lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main())
