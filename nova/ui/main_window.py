"""The Nova window: sidebar navigation plus the seven pages."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..ai.agent import AgentEvent, AgentReply
from ..core.nova_core import NovaCore
from . import theme
from .pages.about_page import AboutPage
from .pages.dashboard import DashboardPage
from .pages.enroll_page import EnrollPage
from .pages.history_page import HistoryPage
from .pages.security_page import SecurityPage
from .pages.settings_page import SettingsPage
from .pages.tasks_page import TasksPage
from .pages.watchers_page import WatchersPage
from .tray import NovaTray
from .widgets import StatusDot

NAV = [
    ("dashboard", "Dashboard"),
    ("tasks", "Tasks"),
    ("watchers", "Watchers"),
    ("history", "History"),
    ("settings", "Settings"),
    ("enroll", "Voice enrollment"),
    ("security", "Permissions"),
    ("about", "About Nova"),
]


class Bridge(QObject):
    """Marshals callbacks from worker threads onto the Qt UI thread."""

    event = Signal(object)
    reply = Signal(object)
    listen_state = Signal(str)
    confirm = Signal(object, str, dict)


class MainWindow(QMainWindow):
    def __init__(self, core: NovaCore, start_hidden: bool = False) -> None:
        super().__init__()
        self.core = core
        self.setWindowTitle("Nova")
        self.resize(1080, 720)
        self.setMinimumSize(880, 600)

        self.bridge = Bridge()
        self.bridge.event.connect(self._on_event)
        self.bridge.reply.connect(self._on_reply)
        self.bridge.listen_state.connect(self._on_listen_state)
        self.bridge.confirm.connect(self._on_confirm_request)

        self._pending_confirm: Any = None
        self._build()
        self._wire_core()
        self._build_tray()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._periodic_refresh)
        self.timer.start(4000)

        self.dashboard.load_history(self.core.db.recent_history(20))
        if not start_hidden:
            self.show()

    # ---------------------------------------------------------------- build
    def _build(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._sidebar())

        self.stack = QStackedWidget()
        self.pages: dict[str, QWidget] = {
            "dashboard": DashboardPage(self.core),
            "tasks": TasksPage(self.core),
            "watchers": WatchersPage(self.core),
            "history": HistoryPage(self.core),
            "settings": SettingsPage(self.core),
            "enroll": EnrollPage(self.core),
            "security": SecurityPage(self.core),
            "about": AboutPage(self.core),
        }
        for key, _ in NAV:
            self.stack.addWidget(self.pages[key])
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self.dashboard: DashboardPage = self.pages["dashboard"]  # type: ignore[assignment]
        self.dashboard.command_submitted.connect(self._submit_command)
        self.dashboard.stop_requested.connect(self._stop_everything)
        self.dashboard.confirm_answered.connect(self._answer_confirm)

    def _sidebar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("Sidebar")
        bar.setFixedWidth(196)
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(0, 20, 0, 14)
        layout.setSpacing(0)

        brand = QWidget()
        bl = QHBoxLayout(brand)
        bl.setContentsMargins(18, 0, 16, 18)
        bl.setSpacing(9)
        self.brand_dot = StatusDot("ready", 9)
        bl.addWidget(self.brand_dot)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        wordmark = QLabel("NOVA")
        wordmark.setObjectName("Wordmark")
        tagline = QLabel("VOICE AGENT")
        tagline.setObjectName("Tagline")
        titles.addWidget(wordmark)
        titles.addWidget(tagline)
        bl.addLayout(titles)
        bl.addStretch(1)
        layout.addWidget(brand)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for index, (key, label) in enumerate(NAV):
            button = QPushButton(label)
            button.setObjectName("NavItem")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, k=key: self.show_page(k))
            if index == 0:
                button.setChecked(True)
            self.nav_group.addButton(button, index)
            layout.addWidget(button)

        layout.addStretch(1)
        self.sidebar_status = QLabel("Ready")
        self.sidebar_status.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: 11px; padding: 0 18px;")
        layout.addWidget(self.sidebar_status)
        return bar

    def _build_tray(self) -> None:
        self.tray = NovaTray(self)
        self.tray.build({
            "open": self._restore,
            "tasks": lambda: self._open_page("tasks"),
            "watchers": lambda: self._open_page("watchers"),
            "history": lambda: self._open_page("history"),
            "settings": lambda: self._open_page("settings"),
            "pause": self._pause_listening,
            "resume": self._resume_listening,
            "stop": self._stop_everything,
            "exit": self._quit,
        })
        self.tray.show()
        from ..winplat.notifications import set_tray_fallback

        set_tray_fallback(self.tray.notify)
        self.tray.set_listening(self.core.listening)

    def _wire_core(self) -> None:
        self.core.on_event = self.bridge.event.emit
        self.core.on_reply = self.bridge.reply.emit
        self.core.on_listen_state = self.bridge.listen_state.emit
        self.core.confirm_handler = self._request_confirmation
        self.core.watchers.on_change = lambda w, body: self.bridge.event.emit(
            AgentEvent("result", f"{w['name']}: {body[:80]}", {"ok": True})
        )

    # ---------------------------------------------------------------- nav
    def show_page(self, key: str) -> None:
        if key not in self.pages:
            return
        index = [k for k, _ in NAV].index(key)
        self.stack.setCurrentIndex(index)
        button = self.nav_group.button(index)
        if button:
            button.setChecked(True)
        page = self.pages[key]
        if hasattr(page, "refresh"):
            page.refresh()  # type: ignore[attr-defined]

    def _open_page(self, key: str) -> None:
        self._restore()
        self.show_page(key)

    def _restore(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # ---------------------------------------------------------------- commands
    def _submit_command(self, text: str) -> None:
        self.dashboard.add_activity(f"“{text}”", "info")
        self.dashboard.show_plan([])
        self.core.submit_command(text)

    def _stop_everything(self) -> None:
        message = self.core.cancel_everything()
        self.dashboard.add_activity(message, "denied")
        self._set_state("idle")
        self.dashboard.hide_confirmation()
        self.pages["tasks"].refresh()  # type: ignore[attr-defined]

    def _pause_listening(self) -> None:
        self.core.pause_listening()
        self._on_listen_state("paused")

    def _resume_listening(self) -> None:
        ok, message = self.core.resume_listening()
        self._on_listen_state("listening" if ok else "stopped")
        if not ok:
            self.dashboard.add_activity(message, "failed")

    # ---------------------------------------------------------------- events
    def _on_event(self, event: AgentEvent) -> None:
        kind = event.kind
        if kind == "state":
            self._set_state(event.text)
        elif kind == "plan":
            self.dashboard.show_plan(event.data.get("steps", []))
            self.dashboard.add_activity(f"Planned {len(event.data.get('steps', []))} steps", "info")
        elif kind == "tool":
            self.dashboard.add_activity(f"{event.text}…", "running")
        elif kind == "result":
            self.dashboard.add_activity(event.text, "ok" if event.data.get("ok") else "failed")
        elif kind == "error":
            self.dashboard.add_activity(event.text, "failed")
        elif kind == "message" and event.data.get("role") != "user":
            self.dashboard.add_activity(event.text, "info")

    def _on_reply(self, reply: AgentReply) -> None:
        self.dashboard.add_activity(reply.text, "ok" if reply.ok else "failed")
        self.dashboard.hide_confirmation()
        self._set_state("idle")
        self.dashboard.refresh()

    def _on_listen_state(self, state: str) -> None:
        listening = state in {"listening", "recording", "wake"}
        self.dashboard.set_listening(listening or self.core.listening)
        self.tray.set_listening(self.core.listening)
        if state == "wake":
            self.dashboard.add_activity("Wake word detected", "info")
        elif state == "unauthorized":
            self.dashboard.add_activity("Ignored a command from an unrecognised voice", "denied")
        elif state in {"paused", "stopped"}:
            self.sidebar_status.setText("Not listening")

    def _set_state(self, state: str) -> None:
        self.dashboard.set_state(state)
        self.brand_dot.set_state(state)
        self.tray.set_state(state)
        self.sidebar_status.setText(state.replace("_", " ").title())

    # ---------------------------------------------------------------- confirmations
    def _request_confirmation(self, decision: Any, tool: str, args: dict) -> Any:
        """Called from the worker loop; returns a future resolved by the UI."""
        import asyncio

        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        self._pending_confirm = future
        self.bridge.confirm.emit(decision, tool, args)
        return future

    def _on_confirm_request(self, decision: Any, tool: str, args: dict) -> None:
        self._restore()
        self.show_page("dashboard")
        self.dashboard.ask_confirmation(decision.summary, decision.details, decision.risk.value)
        self.dashboard.add_activity(f"Waiting for approval: {decision.summary}", "denied")
        self.tray.notify("Nova needs your approval", decision.summary)

    def _answer_confirm(self, approved: bool) -> None:
        self.dashboard.hide_confirmation()
        future = self._pending_confirm
        self._pending_confirm = None
        if future is None or future.done():
            return
        future.get_loop().call_soon_threadsafe(future.set_result, approved)
        self.dashboard.add_activity("Approved." if approved else "Declined.",
                                    "ok" if approved else "denied")

    # ---------------------------------------------------------------- lifecycle
    def _periodic_refresh(self) -> None:
        current = self.stack.currentWidget()
        if current is self.dashboard:
            self.dashboard.refresh()
        elif hasattr(current, "refresh") and current in (self.pages["tasks"], self.pages["watchers"]):
            current.refresh()  # type: ignore[attr-defined]

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """Closing the window keeps Nova alive in the tray."""
        if self.core.settings.get("minimize_to_tray", True) and self.tray.isVisible():
            event.ignore()
            self.hide()
            self.tray.notify("Nova is still running", "Nova stays in the system tray. Right-click it to exit.")
            return
        self._quit()

    def _quit(self) -> None:
        from PySide6.QtWidgets import QApplication

        self.timer.stop()
        self.tray.hide()
        self.core.shutdown()
        QApplication.quit()
