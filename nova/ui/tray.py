"""System tray icon and menu. Nova keeps running here when the window is closed."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from . import theme


def nova_icon(state: str = "idle") -> QIcon:
    """Draw the tray glyph: a hollow ring with a state-coloured core."""
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    painter.setPen(QPen(QColor("#d8dadf"), 5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QRect(9, 9, 46, 46))

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(theme.state_color(state)))
    painter.drawEllipse(QRect(23, 23, 18, 18))
    painter.end()
    return QIcon(pixmap)


class NovaTray(QSystemTrayIcon):
    def __init__(self, parent: Any = None) -> None:
        super().__init__(nova_icon("idle"), parent)
        self.setToolTip("Nova — ready")
        self._menu = QMenu()
        self._actions: dict[str, QAction] = {}
        self.activated.connect(self._on_activated)
        self.on_open: Callable[[], None] | None = None

    def build(self, handlers: dict[str, Callable[[], None]]) -> None:
        menu = self._menu
        menu.clear()

        header = QAction("Nova", menu)
        header.setEnabled(False)
        menu.addAction(header)
        menu.addSeparator()

        for label, key in [("Open Nova", "open"), ("Tasks", "tasks"), ("Watchers", "watchers"),
                           ("History", "history"), ("Settings", "settings")]:
            action = QAction(label, menu)
            action.triggered.connect(handlers[key])
            menu.addAction(action)
            self._actions[key] = action

        menu.addSeparator()
        self.pause_action = QAction("Pause listening", menu)
        self.pause_action.triggered.connect(handlers["pause"])
        menu.addAction(self.pause_action)
        self.resume_action = QAction("Resume listening", menu)
        self.resume_action.triggered.connect(handlers["resume"])
        menu.addAction(self.resume_action)

        menu.addSeparator()
        stop = QAction("Stop all activity", menu)
        stop.triggered.connect(handlers["stop"])
        menu.addAction(stop)

        menu.addSeparator()
        quit_action = QAction("Exit", menu)
        quit_action.triggered.connect(handlers["exit"])
        menu.addAction(quit_action)

        self.setContextMenu(menu)
        self.on_open = handlers["open"]

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick) and self.on_open:
            self.on_open()

    def set_state(self, state: str, detail: str = "") -> None:
        self.setIcon(nova_icon(state))
        label = state.replace("_", " ")
        self.setToolTip(f"Nova — {label}" + (f": {detail}" if detail else ""))

    def set_listening(self, listening: bool) -> None:
        if hasattr(self, "pause_action"):
            self.pause_action.setEnabled(listening)
            self.resume_action.setEnabled(not listening)

    def notify(self, title: str, body: str) -> None:
        self.showMessage(title, body, nova_icon("idle"), 6000)
