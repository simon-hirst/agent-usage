"""Cross-platform provider-selectable system tray with a compact click popup."""
from __future__ import annotations

import html
import json
import os
import platform
import sys
import time
import tempfile
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QLockFile, QProcess, QProcessEnvironment, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QCursor, QDesktopServices, QFont, QIcon, QPainter, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from .autostart import enabled as autostart_enabled, set_enabled as set_autostart
from .claude_cache import ClaudeLastKnown
from .core import ROOT, PROVIDERS, SERVICES, USAGE_PAGES, app_data_dir, load_settings, save_settings, secure_child_env
from .processes import BackendManager
from .providers import icon_number, is_local_url, normalize, parse_muse_usage, normalize_direct_result, parse_direct_output
from .tooltips import individual_tooltip, merged_tooltip, local_reset_time


def icon_for(service: str, field: str, remaining: float | None, *, stale: bool = False) -> QIcon:
    """Small transparent, coloured numeric icon, never an invented usage figure."""
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    font = QFont("Arial", 34 if remaining is None or remaining >= 100 else 38, QFont.Weight.Bold)
    painter.setFont(font)
    value = "--" if remaining is None else str(int(round(remaining)))
    rect = pix.rect()
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        painter.setPen(QColor(0, 0, 0, 80))
        painter.drawText(rect.adjusted(dx, dy, dx, dy), Qt.AlignmentFlag.AlignCenter, value)
    colour = QColor(PROVIDERS[service]["colour"])
    if stale:
        colour.setAlpha(155)  # A cached reading is still visible, but not presented as live.
    painter.setPen(colour)
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, value)
    painter.end()
    return QIcon(pix)


def combined_icon() -> QIcon:
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    colours = ("#18A077", "#DB7958", "#547AE8", "#8566D8")
    for idx, colour in enumerate(colours):
        painter.setBrush(QColor(colour))
        painter.drawRoundedRect(7 + (idx % 2) * 27, 7 + (idx // 2) * 27, 23, 23, 6, 6)
    painter.end()
    return QIcon(pix)


def local_reset(iso: Any) -> str:
    local = local_reset_time(iso)
    return "Resets " + local if local else "Reset time unavailable"


def selected_services(settings: dict[str, Any]) -> list[str]:
    return [key for key in PROVIDERS if key in settings["selected_providers"]]


def usage_summary(snapshot: dict[str, Any] | None, include_weekly: bool = True,
                  include_resets: bool = False) -> str:
    if not snapshot or not snapshot.get("ok"):
        reason = str((snapshot or {}).get("error") or "Waiting for usage data")
        return "Unavailable — " + reason[:100]
    fragments = []
    for field, label in (("five_hour", "5h"), ("weekly", "7d"), ("monthly", "month"), ("daily", "day")):
        if field == "weekly" and not include_weekly:
            continue
        item = snapshot.get(field)
        if isinstance(item, dict):
            fragment = f"{label}: {item['remaining_percent']:g}% left"
            if include_resets:
                local = local_reset_time(item.get("resets_at"))
                fragment += f" (resets {local})" if local else " (reset unknown)"
            fragments.append(fragment)
    if snapshot.get("model_quotas"):
        for quota in snapshot["model_quotas"][:6]:
            part = f"{quota['name']}: {quota['remaining_percent']:g}% left"
            if include_resets:
                local = local_reset_time(quota.get('resets_at'))
                part += f" (resets {local})" if local else " (reset unknown)"
            fragments.append(part)
        if len(snapshot['model_quotas']) > 6:
            fragments.append(f"+{len(snapshot['model_quotas']) - 6} more model quotas")
    if snapshot.get("balance_text"):
        fragments.append(str(snapshot["balance_text"]))
    if snapshot.get("credit_percent") is not None:
        fragments.append(f"{snapshot['credit_percent']:g}% of credit allowance left")
    summary = " · ".join(fragments) or "No quota windows available"
    if snapshot.get("stale"):
        last = local_reset_time(snapshot.get("last_updated_at")) or "unknown"
        return f"Last known (not live; updated {last} local) — {summary}"
    return summary


class ProviderSelection(QDialog):
    def __init__(self, settings: dict[str, Any], first_run: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose providers to track" if first_run else "Usage tray settings")
        self.setMinimumWidth(470)
        self.setMinimumHeight(520)
        self.settings = settings
        outer = QVBoxLayout(self)
        heading = QLabel("Choose what to track" if first_run else "Providers and preferences")
        heading.setStyleSheet("font-size: 20px; font-weight: 700")
        outer.addWidget(heading)
        outer.addWidget(QLabel("Only selected providers appear in the tray and quick view."))
        permission = QLabel("Selected account readers may access that provider’s existing local login or browser cookies.\nCredentials stay on your computer and go only to their matching provider.")
        permission.setWordWrap(True)
        outer.addWidget(permission)
        scrolling = QScrollArea()
        scrolling.setWidgetResizable(True)
        widget = QWidget()
        body = QVBoxLayout(widget)
        self.boxes: dict[str, QCheckBox] = {}
        for key, meta in PROVIDERS.items():
            entry = QCheckBox(meta["name"])
            entry.setChecked(key in settings["selected_providers"])
            entry.setToolTip(meta["hint"])
            self.boxes[key] = entry
            body.addWidget(entry)
            hint = QLabel(meta["hint"])
            hint.setStyleSheet("color: #777; padding-left: 23px; font-size: 11px")
            hint.setWordWrap(True)
            body.addWidget(hint)
        body.addStretch()
        scrolling.setWidget(widget)
        outer.addWidget(scrolling, 1)
        self.merged = QCheckBox("Combine all providers into one tray icon (click for quick view)")
        self.merged.setChecked(settings["merged_icon"])
        outer.addWidget(self.merged)
        self.weekly = QCheckBox("Show separate weekly icons when not combined")
        self.weekly.setChecked(settings["show_weekly"])
        outer.addWidget(self.weekly)
        self.manage = QCheckBox("Run selected Codex / Claude APIs in the background")
        self.manage.setChecked(settings["manage_backends"])
        outer.addWidget(self.manage)
        self.startup = QCheckBox("Start automatically when signing in")
        self.startup.setChecked(autostart_enabled())
        outer.addWidget(self.startup)
        form = QFormLayout()
        self.distro = QLineEdit(settings["wsl_distro"])
        form.addRow("WSL distro (Windows):", self.distro)
        outer.addLayout(form)
        advanced_button = QPushButton("Advanced: optional Muse/Kimi local endpoint ▸")
        advanced_button.setToolTip("For Muse/Kimi installations with a nondefault endpoint")
        outer.addWidget(advanced_button)
        self.advanced_widget = QWidget()
        advanced_form = QFormLayout(self.advanced_widget)
        outer.addWidget(self.advanced_widget)
        self.advanced_widget.hide()
        advanced_button.clicked.connect(lambda: self.advanced_widget.setVisible(not self.advanced_widget.isVisible()))
        self.endpoint_edits: dict[str, QLineEdit] = {}
        for key in ("muse", "kimi"):
            entry = QLineEdit(settings["endpoints"].get(key, ""))
            entry.setPlaceholderText("http://127.0.0.1:PORT/get" if key != "kimi" else "http://127.0.0.1:58627/api/v1/oauth/usage")
            entry.setToolTip("Only http://localhost / 127.0.0.1 endpoints are accepted")
            self.endpoint_edits[key] = entry
            advanced_form.addRow(PROVIDERS[key]["short"] + " URL:", entry)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        controls.accepted.connect(self.accept)
        controls.rejected.connect(self.reject)
        outer.addWidget(controls)

    def accept(self):
        import re
        selected = [k for k in PROVIDERS if self.boxes[k].isChecked()]
        if not selected:
            QMessageBox.warning(self, "Select a provider", "Choose at least one provider.")
            return
        if not re.fullmatch(r"[a-zA-Z0-9._-]{1,80}", self.distro.text().strip()):
            QMessageBox.warning(self, "Invalid distribution", "Enter a WSL distro name, e.g. Debian.")
            return
        endpoints = {key: edit.text().strip() for key, edit in self.endpoint_edits.items() if edit.text().strip()}
        for key, url in endpoints.items():
            if not is_local_url(url):
                QMessageBox.warning(self, "Invalid endpoint", f"{key}: use an HTTP localhost URL with a port.")
                return
        try:
            set_autostart(self.startup.isChecked())
        except OSError as exc:
            QMessageBox.warning(self, "Startup setting failed", str(exc))
            return
        self.settings.update({
            "selected_providers": selected, "merged_icon": self.merged.isChecked(),
            "show_weekly": self.weekly.isChecked(), "manage_backends": self.manage.isChecked(),
            "wsl_distro": self.distro.text().strip(), "setup_complete": True, "endpoints": endpoints,
        })
        save_settings(self.settings)
        super().accept()


class QuickView(QWidget):
    def __init__(self, controller: "TrayController"):
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.controller = controller
        self.setMinimumWidth(345)
        self.setMaximumWidth(435)
        self.setObjectName("quick")
        self.setStyleSheet("#quick { background: palette(window); border: 1px solid palette(mid); border-radius: 10px; }")
        outer = QVBoxLayout(self)
        head = QHBoxLayout()
        title = QLabel("Usage remaining")
        title.setStyleSheet("font-weight: 700; font-size: 16px")
        head.addWidget(title)
        head.addStretch()
        refresh = QPushButton("↻")
        refresh.setToolTip("Refresh readings")
        refresh.setMaximumWidth(34)
        refresh.clicked.connect(controller.poll)
        head.addWidget(refresh)
        outer.addLayout(head)
        self.content = QVBoxLayout()
        outer.addLayout(self.content)
        footer = QHBoxLayout()
        dashboard = QPushButton("Open dashboard")
        dashboard.clicked.connect(self.open_dashboard)
        footer.addWidget(dashboard)
        settings = QPushButton("Settings")
        settings.clicked.connect(self.open_settings)
        footer.addWidget(settings)
        outer.addLayout(footer)

    def open_dashboard(self):
        self.hide()
        self.controller.show_dashboard()

    def open_settings(self):
        self.hide()
        self.controller.settings_dialog()

    def redraw(self):
        while self.content.count():
            child = self.content.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        for service in selected_services(self.controller.settings):
            entry = QLabel(f"<b style='color:{PROVIDERS[service]['colour']}'>{PROVIDERS[service]['short']}</b>"
                           + "<br>" + html.escape(usage_summary(self.controller.snapshots.get(service), include_resets=True)))
            entry.setTextFormat(Qt.TextFormat.RichText)
            entry.setWordWrap(True)
            entry.setStyleSheet("padding: 4px 3px")
            self.content.addWidget(entry)
            if service in USAGE_PAGES:
                open_page = QPushButton(f"Open {PROVIDERS[service]['short']} usage page")
                open_page.clicked.connect(lambda checked=False, s=service: self.controller.open_usage_page(s))
                self.content.addWidget(open_page)
        self.adjustSize()

    def show_at_cursor(self):
        self.redraw()
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        bounds = screen.availableGeometry()
        self.adjustSize()
        cursor = QCursor.pos()
        x = max(bounds.left(), min(cursor.x() - self.width() // 2, bounds.right() - self.width()))
        y = cursor.y() - self.height() - 12
        if y < bounds.top():
            y = min(cursor.y() + 12, bounds.bottom() - self.height())
        self.move(x, y)
        self.show()
        self.raise_()


class Dashboard(QDialog):
    def __init__(self, controller: "TrayController"):
        super().__init__()
        self.controller = controller
        self.setWindowTitle("Provider usage — dashboard")
        self.setMinimumSize(465, 410)
        self.setWindowIcon(combined_icon())
        root = QVBoxLayout(self)
        root.addWidget(QLabel("<h2>Usage remaining</h2>"))
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.content_widget = QWidget()
        self.content = QVBoxLayout(self.content_widget)
        self.scroll.setWidget(self.content_widget)
        root.addWidget(self.scroll)
        actions = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(controller.poll)
        actions.addWidget(refresh)
        settings = QPushButton("Settings")
        settings.clicked.connect(controller.settings_dialog)
        actions.addWidget(settings)
        close = QPushButton("Hide")
        close.clicked.connect(self.hide)
        actions.addWidget(close)
        root.addLayout(actions)

    def closeEvent(self, event):
        if self.controller.tray_available:
            self.hide()
            event.ignore()
        else:
            self.controller.exit_app()
            event.accept()

    def redraw(self):
        while self.content.count():
            child = self.content.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        for service in selected_services(self.controller.settings):
            group = QGroupBox(PROVIDERS[service]["name"])
            box = QVBoxLayout(group)
            snap = self.controller.snapshots.get(service)
            if not snap or not snap.get("ok"):
                details = QLabel(usage_summary(snap))
                details.setWordWrap(True)
                box.addWidget(details)
            else:
                if snap.get("stale"):
                    when = local_reset_time(snap.get("last_updated_at")) or "unknown"
                    warning = QLabel(f"Last known reading (not live) · updated {when} local")
                    warning.setWordWrap(True)
                    box.addWidget(warning)
                found = False
                for key, label in (("five_hour", "5-hour"), ("weekly", "Weekly"), ("monthly", "Monthly"), ("daily", "Daily")):
                    value = snap.get(key)
                    if not isinstance(value, dict):
                        continue
                    found = True
                    row = QLabel(f"{label}: <b>{value['remaining_percent']:g}% remaining</b> — {local_reset(value.get('resets_at'))}")
                    row.setWordWrap(True)
                    box.addWidget(row)
                    progress = QProgressBar()
                    progress.setRange(0, 100)
                    progress.setValue(int(round(value["remaining_percent"])))
                    progress.setStyleSheet(f"QProgressBar::chunk {{ background: {PROVIDERS[service]['colour']}; }}")
                    box.addWidget(progress)
                if snap.get('model_quotas'):
                    for quota in snap['model_quotas'][:15]:
                        text = f"{quota['name']}: {quota['remaining_percent']:g}% left — {local_reset(quota.get('resets_at'))}"
                        entry = QLabel(text)
                        entry.setWordWrap(True)
                        box.addWidget(entry)
                    found = True
                if snap.get("balance_text"):
                    box.addWidget(QLabel("Balance: " + snap["balance_text"]))
                    found = True
                if snap.get("credit_percent") is not None:
                    box.addWidget(QLabel(f"Credit allowance: {snap['credit_percent']:g}% remaining"))
                    found = True
                if not found:
                    box.addWidget(QLabel("No quota windows available for this account"))
            if service in USAGE_PAGES:
                open_page = QPushButton("Open account usage page")
                open_page.clicked.connect(lambda checked=False, s=service: self.controller.open_usage_page(s))
                box.addWidget(open_page)
            self.content.addWidget(group)
        self.content.addStretch()


class TrayController:
    def __init__(self, app: QApplication, settings: dict[str, Any]):
        self.app = app
        self.app.setQuitOnLastWindowClosed(False)
        self.settings = settings
        self.tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        self.manager = BackendManager(wsl_distro=settings["wsl_distro"])
        self.manager.enabled = settings["manage_backends"]
        self.manager.set_selected(settings["selected_providers"])
        self.claude_cache = ClaudeLastKnown(app_data_dir() / "claude-last-known.json")
        self.snapshots: dict[str, dict[str, Any]] = {}
        last_claude = self.claude_cache.fallback("Waiting for current Claude usage")
        if last_claude:
            self.snapshots["claude"] = last_claude
        self.net = QNetworkAccessManager(app)
        self.trays: dict[tuple[str, str], QSystemTrayIcon] = {}
        self.menus: list[QMenu] = []
        self.muse_proc: QProcess | None = None
        self.muse_started = False
        self.direct_procs: dict[str, QProcess] = {}
        self.direct_last_started: dict[str, float] = {}
        self.direct_result_paths: dict[str, Path] = {}
        self.dashboard = Dashboard(self)
        self.quick = QuickView(self)
        self.merged_tray = QSystemTrayIcon(combined_icon(), app)
        self.merged_tray.setToolTip(merged_tooltip(selected_services(self.settings), self.snapshots))
        self._configure_tray(self.merged_tray, None)
        self.rebuild_icons()
        self.refresh_timer = QTimer(app)
        self.refresh_timer.timeout.connect(self.poll)
        self.refresh_timer.start(60_000)
        self.boot_timer = QTimer(app)
        self.boot_timer.timeout.connect(lambda: self.poll(boot=True))
        self.boot_checks = 0
        self.boot_timer.start(8000)
        self.app.aboutToQuit.connect(self.manager.stop)
        self.manager.ensure_running()
        self.poll()
        if not self.tray_available:
            self.show_dashboard()
            QMessageBox.information(self.dashboard, "No system tray", "No usable tray was detected. The dashboard will stay open; closing it stops managed services.")

    def _configure_tray(self, tray: QSystemTrayIcon, which: tuple[str, str] | None):
        menu = QMenu()
        if which is not None:
            service, field = which
            description = ('Model quotas' if service == 'gemini' else
                           'Monthly quota' if service == 'copilot' else
                           'API balance' if service in ('deepseek', 'openrouter') else
                           'Account usage page' if PROVIDERS[service]['source'] == 'dashboard' else
                           '5-hour quota' if field == 'five_hour' else 'Weekly quota')
            heading = menu.addAction(f"{PROVIDERS[service]['name']} — {description}")
            heading.setEnabled(False)
            menu.addSeparator()
        popup = menu.addAction("Quick view")
        popup.triggered.connect(self.show_quick_view)
        dashboard = menu.addAction("Open dashboard")
        dashboard.triggered.connect(self.show_dashboard)
        settings = menu.addAction("Choose providers / Settings")
        settings.triggered.connect(self.settings_dialog)
        menu.addSeparator()
        quit_action = menu.addAction("Exit — stop managed backends")
        quit_action.triggered.connect(self.exit_app)
        tray.setContextMenu(menu)
        tray.activated.connect(self.on_activated)
        if which is not None and which[0] in USAGE_PAGES:
            menu.addSeparator()
            usage_action = menu.addAction("Open account usage page")
            usage_action.triggered.connect(lambda checked=False, s=which[0]: self.open_usage_page(s))
        self.menus.append(menu)

    def open_usage_page(self, service: str):
        url = USAGE_PAGES.get(service)
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def rebuild_icons(self):
        for tray in self.trays.values():
            tray.hide()
            tray.deleteLater()
        self.trays.clear()
        self.merged_tray.setVisible(False)
        self.update_merged_tooltip()
        if self.settings["merged_icon"]:
            self.merged_tray.setVisible(self.tray_available)
            return
        for service in selected_services(self.settings):
            fields = ("five_hour", "weekly") if self.settings["show_weekly"] and service in ("codex", "claude", "muse", "kimi", "grok", "cursor", "qwen", "windsurf") else ("five_hour",)
            for field in fields:
                tray = QSystemTrayIcon(self.app)
                snap = self.snapshots.get(service)
                value = snap.get(field) if snap and snap.get("ok") else None
                remaining = self.icon_remaining(service, snap, field)
                if remaining is None and field == "five_hour" and service == "openrouter" and snap and snap.get("ok"):
                    remaining = snap.get("credit_percent")
                tray.setIcon(icon_for(service, field, remaining, stale=bool(snap and snap.get("stale"))))
                tray.setToolTip(individual_tooltip(service, snap))
                self._configure_tray(tray, (service, field))
                tray.show() if self.tray_available else None
                self.trays[(service, field)] = tray

    def icon_remaining(self, service: str, snap: dict | None, field: str):
        if not snap or not snap.get('ok'):
            return None
        data = snap.get(field)
        if isinstance(data, dict):
            return data.get('remaining_percent')
        if field == 'five_hour':
            # Model-based quotas (Gemini, or older Windsurf plan caches) show
            # the most constrained bucket, not an invented five-hour limit.
            if service in ('gemini', 'windsurf') and snap.get('model_quotas'):
                return min(q['remaining_percent'] for q in snap['model_quotas'])
            # Copilot quota is monthly, not a five-hour window.
            if isinstance(snap.get('monthly'), dict):
                return snap['monthly']['remaining_percent']
            if isinstance(snap.get('daily'), dict):
                return snap['daily']['remaining_percent']
            if snap.get('credit_percent') is not None:
                return snap['credit_percent']
        return None

    def on_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_quick_view()

    def show_quick_view(self):
        self.quick.show_at_cursor()

    def show_dashboard(self):
        self.dashboard.redraw()
        self.dashboard.show()
        self.dashboard.raise_()
        self.dashboard.activateWindow()

    def settings_dialog(self):
        dialog = ProviderSelection(self.settings.copy(), first_run=False, parent=self.dashboard)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.settings = dialog.settings
        if not self.settings["manage_backends"]:
            self.manager.stop()
        elif not self.manager.enabled or self.manager.wsl_distro != self.settings["wsl_distro"]:
            self.manager.stop()
            self.manager = BackendManager(wsl_distro=self.settings["wsl_distro"])
        self.manager.set_selected(self.settings["selected_providers"])
        for service, proc in list(self.direct_procs.items()):
            if service not in self.settings['selected_providers']:
                proc.kill()
                self.direct_procs.pop(service, None)
                self.discard_direct_file(service)
        if "muse" not in self.settings["selected_providers"] and self.muse_proc is not None:
            self.muse_proc.kill()
            self.muse_proc = None
        self.manager.ensure_running()
        self.rebuild_icons()
        self.poll()
        if self.dashboard.isVisible():
            self.dashboard.redraw()

    def poll(self, boot=False):
        self.manager.ensure_running()
        if self.boot_timer.isActive():
            self.boot_checks += 1
            if self.boot_checks >= 15 or all(s in self.snapshots and self.snapshots[s].get("ok") for s in selected_services(self.settings)):
                self.boot_timer.stop()
        for service in selected_services(self.settings):
            if boot and service not in SERVICES:
                # Startup retries are for local WSL servers only; no extra remote API calls.
                continue
            source = PROVIDERS[service]["source"]
            endpoint = self.settings["endpoints"].get(service)
            if source == "local":
                url = f"http://127.0.0.1:{SERVICES[service]['port']}/get"
                token = None
            elif source == "direct":
                self.poll_direct(service)
                continue
            elif source == "dashboard":
                self.consume_error(service, "No automatic quota endpoint. Open the account usage page.")
                continue
            elif endpoint:
                if not is_local_url(endpoint):
                    self.consume_error(service, "Configured URL must point to localhost")
                    continue
                url, token = endpoint, os.environ.get("KIMI_SERVER_TOKEN") if service == "kimi" else None
            elif source == "kimi":
                url, token = "http://127.0.0.1:58627/api/v1/oauth/usage", os.environ.get("KIMI_SERVER_TOKEN")
            elif source == "deepseek":
                url, token = "https://api.deepseek.com/user/balance", os.environ.get("DEEPSEEK_API_KEY")
            elif source == "openrouter":
                url, token = "https://openrouter.ai/api/v1/credits", os.environ.get("OPENROUTER_API_KEY")
            elif source == "muse":
                self.poll_muse()
                continue
            else:
                self.consume_error(service, "No supported reader for this provider")
                continue
            if service in ("deepseek", "openrouter") and not token:
                self.consume_error(service, "Missing API key environment variable (see README)")
                continue
            if source == "kimi" and not token:
                self.consume_error(service, "Set KIMI_SERVER_TOKEN for your running Kimi local server")
                continue
            request = QNetworkRequest(QUrl(url))
            request.setTransferTimeout(7000)
            request.setRawHeader(b"Accept", b"application/json")
            if token:
                request.setRawHeader(b"Authorization", b"Bearer " + token.encode("utf-8"))
            reply = self.net.get(request)
            reply.finished.connect(lambda r=reply, s=service: self.consume(s, r))

    def poll_direct(self, service: str):
        if service in self.direct_procs:
            return
        # Internal quota endpoints should not be called every 60s unnecessarily.
        if time.monotonic() - self.direct_last_started.get(service, -1e10) < 300:
            return
        self.direct_last_started[service] = time.monotonic()
        proc = QProcess(self.app)
        self.direct_procs[service] = proc
        proc.setWorkingDirectory(str(ROOT))
        env = QProcessEnvironment()
        for key, value in secure_child_env().items():
            env.insert(key, value)
        proc.setProcessEnvironment(env)
        if platform.system() == 'Windows' and service in ('gemini', 'copilot', 'grok'):
            # CLIs are authenticated in WSL; editor/browser logins reside on Windows.
            proc.setProgram('wsl.exe')
            proc.setArguments(['-d', self.settings['wsl_distro'], '--', 'bash', '-i', './desktop/direct-usage.sh', service])
        else:
            directory = app_data_dir()
            directory.mkdir(parents=True, exist_ok=True)
            fd, filename = tempfile.mkstemp(prefix=f'direct-{service}-', suffix='.json', dir=directory)
            os.close(fd)
            self.direct_result_paths[service] = Path(filename)
            if getattr(sys, 'frozen', False):
                proc.setProgram(sys.executable)
                proc.setArguments(['--direct-usage', service, '--output', filename])
            else:
                proc.setProgram(sys.executable)
                proc.setArguments(['-m', 'desktop.direct_usage', service, '--output', filename])
        proc.finished.connect(lambda code, status, s=service, p=proc: self.consume_direct(s, p, code))
        proc.errorOccurred.connect(lambda error, s=service, p=proc: self.direct_error(s, p))
        proc.start()
        QTimer.singleShot(25000, lambda s=service, p=proc: self.timeout_direct(s, p))

    def discard_direct_file(self, service: str):
        path = self.direct_result_paths.pop(service, None)
        if path:
            path.unlink(missing_ok=True)

    def timeout_direct(self, service: str, proc: QProcess):
        if self.direct_procs.get(service) is proc and proc.state() != QProcess.ProcessState.NotRunning:
            self.direct_procs.pop(service, None)
            self.discard_direct_file(service)
            self.consume_error(service, 'Direct provider usage request timed out')
            proc.kill()
            proc.deleteLater()

    def direct_error(self, service: str, proc: QProcess):
        if self.direct_procs.get(service) is not proc:
            return
        if proc.error() == QProcess.ProcessError.FailedToStart:
            self.direct_procs.pop(service, None)
            self.discard_direct_file(service)
            self.consume_error(service, 'Cannot start provider reader; check CLI login and WSL settings')
            proc.deleteLater()

    def consume_direct(self, service: str, proc: QProcess, code: int):
        if self.direct_procs.get(service) is not proc:
            return
        self.direct_procs.pop(service, None)
        path = self.direct_result_paths.get(service)
        if path:
            try:
                output = path.read_bytes()
            except OSError:
                output = b''
            self.discard_direct_file(service)
        else:
            output = bytes(proc.readAllStandardOutput())
        proc.deleteLater()
        if service not in self.settings['selected_providers']:
            return
        try:
            if code or len(output) > 262144:
                raise ValueError('Direct provider reader failed')
            result = normalize_direct_result(service, parse_direct_output(output))
            self.set_snapshot(service, result)
        except (ValueError, UnicodeError) as err:
            self.consume_error(service, str(err))

    def poll_muse(self):
        if self.muse_proc is not None and self.muse_proc.state() != QProcess.ProcessState.NotRunning:
            return
        process = QProcess(self.app)
        self.muse_proc = process
        env = QProcessEnvironment()
        for key, value in secure_child_env().items():
            env.insert(key, value)
        process.setProcessEnvironment(env)
        if platform.system() == "Windows":
            process.setProgram("wsl.exe")
            process.setArguments(["-d", self.settings["wsl_distro"], "--", "bash", "-ic", "muse usage"])
        else:
            process.setProgram("muse")
            process.setArguments(["usage"])
        process.finished.connect(lambda code, status, proc=process: self.consume_muse(proc, code))
        process.errorOccurred.connect(lambda error, proc=process: self.muse_error(proc))
        process.start()
        QTimer.singleShot(12000, lambda proc=process: self.timeout_muse(proc))

    def timeout_muse(self, process: QProcess):
        if process is self.muse_proc and process.state() != QProcess.ProcessState.NotRunning:
            self.consume_error("muse", "Muse CLI usage command timed out")
            process.kill()

    def muse_error(self, process: QProcess):
        if process is not self.muse_proc:
            return
        if process.error() == QProcess.ProcessError.FailedToStart:
            self.consume_error("muse", "Muse CLI not found (install and sign in to Muse Code)")
            self.muse_proc = None
            process.deleteLater()

    def consume_muse(self, process: QProcess, exit_code: int):
        if process is not self.muse_proc:
            return
        data = bytes(process.readAllStandardOutput())
        err = bytes(process.readAllStandardError())
        self.muse_proc = None
        process.deleteLater()
        if "muse" not in self.settings["selected_providers"]:
            return
        try:
            if exit_code:
                raise ValueError("Muse CLI returned an error: " + err.decode("utf-8", "replace")[:160])
            result = parse_muse_usage(data.decode("utf-8", "replace"))
            self.set_snapshot("muse", result)
        except ValueError as exc:
            self.consume_error("muse", str(exc))

    def consume(self, service: str, reply: QNetworkReply):
        try:
            data = bytes(reply.readAll())
            if len(data) > 262144:
                raise ValueError("Response too large")
            if reply.error() != QNetworkReply.NetworkError.NoError:
                raise ValueError(reply.errorString())
            self.set_snapshot(service, normalize(service, json.loads(data.decode("utf-8"))))
        except (ValueError, UnicodeError) as exc:
            self.consume_error(service, str(exc))
        finally:
            reply.deleteLater()

    def consume_error(self, service: str, error: str):
        self.set_snapshot(service, {"ok": False, "error": error[:220], "five_hour": None, "weekly": None})

    def set_snapshot(self, service: str, result: dict[str, Any]):
        if service == "claude":
            result = self.claude_cache.apply(result)
        self.snapshots[service] = result
        for field in ("five_hour", "weekly"):
            tray = self.trays.get((service, field))
            if tray is None:
                continue
            item = result.get(field) if result.get("ok") else None
            remaining = self.icon_remaining(service, result, field)
            if remaining is None and field == "five_hour" and service == "openrouter" and result.get("ok"):
                remaining = result.get("credit_percent")
            tray.setIcon(icon_for(service, field, remaining, stale=bool(result.get("stale"))))
            tray.setToolTip(individual_tooltip(service, result))
        self.update_merged_tooltip()
        if self.quick.isVisible():
            self.quick.redraw()
        if self.dashboard.isVisible():
            self.dashboard.redraw()

    def update_merged_tooltip(self):
        self.merged_tray.setToolTip(
            merged_tooltip(selected_services(self.settings), self.snapshots)
        )

    def exit_app(self):
        self.refresh_timer.stop()
        self.boot_timer.stop()
        for tray in self.trays.values():
            tray.hide()
        self.merged_tray.hide()
        for proc in self.direct_procs.values():
            proc.kill()
            proc.waitForFinished(500)
        self.direct_procs.clear()
        for service in list(self.direct_result_paths):
            self.discard_direct_file(service)
        if self.muse_proc is not None:
            self.muse_proc.kill()
            self.muse_proc.waitForFinished(1000)
        self.manager.stop()
        self.app.quit()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Provider Usage Tray")
    app.setOrganizationName("Local Usage Monitor")
    lockpath = app_data_dir() / "tray.lock"
    lockpath.parent.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(lockpath))
    lock.setStaleLockTime(30000)
    if not lock.tryLock(0):
        return 0
    controller = None
    try:
        settings = load_settings()
        if not settings["setup_complete"]:
            setup = ProviderSelection(settings, first_run=True)
            if setup.exec() != QDialog.DialogCode.Accepted:
                return 0
            settings = setup.settings
        controller = TrayController(app, settings)
        return app.exec()
    finally:
        if controller:
            controller.manager.stop()
        lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main())
