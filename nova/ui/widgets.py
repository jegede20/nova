"""Small reusable widgets shared by the pages."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import theme


class StatusDot(QWidget):
    """A small coloured dot that breathes while Nova is busy."""

    def __init__(self, state: str = "idle", size: int = 9, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._size = size
        self._opacity = 1.0
        self.setFixedSize(size + 4, size + 4)
        self._pulse = QPropertyAnimation(self, b"pulse")
        self._pulse.setDuration(1100)
        self._pulse.setStartValue(1.0)
        self._pulse.setEndValue(0.35)
        self._pulse.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._pulse.setLoopCount(-1)
        self.set_state(state)

    def _get_pulse(self) -> float:
        return self._opacity

    def _set_pulse(self, value: float) -> None:
        self._opacity = value
        self.update()

    # Exposed to Qt so QPropertyAnimation can drive the fade.
    pulse = Property(float, _get_pulse, _set_pulse)

    def set_state(self, state: str) -> None:
        self._state = (state or "idle").lower()
        busy = self._state in {"thinking", "planning", "executing", "listening",
                               "recording", "running", "speaking", "waiting_confirmation"}
        self._pulse.stop()
        if busy:
            self._pulse.start()
        else:
            self._opacity = 1.0
        self.update()

    def paintEvent(self, event: Any) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(theme.state_color(self._state))
        color.setAlphaF(self._opacity)
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(2, 2, self._size, self._size)


class Card(QFrame):
    """Compact bordered surface used everywhere."""

    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 14, 16, 14)
        self._layout.setSpacing(10)
        if title:
            label = QLabel(title.upper())
            label.setObjectName("SectionLabel")
            self._layout.addWidget(label)

    def body(self) -> QVBoxLayout:
        return self._layout

    def add(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)


class Row(QWidget):
    """A single line of activity: dot + text + timestamp."""

    def __init__(self, text: str, state: str = "ok", timestamp: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 3, 0, 3)
        layout.setSpacing(10)
        icon = {"ok": "✓", "failed": "✕", "denied": "⊘", "running": "●", "info": "·"}.get(state, "·")
        color = {"ok": theme.OK, "failed": theme.ERROR, "denied": theme.WARN,
                 "running": theme.BUSY}.get(state, theme.TEXT_FAINT)
        mark = QLabel(icon)
        mark.setStyleSheet(f"color: {color}; font-size: 12px;")
        mark.setFixedWidth(14)
        body = QLabel(text)
        body.setStyleSheet(f"font-size: 12.5px; color: {theme.TEXT};")
        body.setWordWrap(True)
        body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(mark)
        layout.addWidget(body, 1)
        if timestamp:
            ts = QLabel(timestamp)
            ts.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
            layout.addWidget(ts)


class SettingRow(QWidget):
    """Label + description on the left, control on the right."""

    def __init__(self, label: str, control: QWidget, hint: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(2)
        title = QLabel(label)
        title.setStyleSheet("font-size: 13px;")
        left.addWidget(title)
        if hint:
            sub = QLabel(hint)
            sub.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
            sub.setWordWrap(True)
            left.addWidget(sub)
        layout.addLayout(left, 1)
        control.setMinimumWidth(180)
        control.setMaximumWidth(280)
        layout.addWidget(control, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


class Toggle(QCheckBox):
    def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setChecked(checked)
        self.setMaximumWidth(30)


class Pill(QLabel):
    """Small state badge, e.g. RUNNING / FAILED."""

    def __init__(self, text: str, state: str = "idle", parent: QWidget | None = None) -> None:
        super().__init__(text.upper(), parent)
        self.apply_color(theme.state_color(state))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(19)

    def apply_color(self, color: str) -> None:
        self.setStyleSheet(
            f"color: {color}; border: 1px solid {theme.rgba(color, 0.35)};"
            f"background: {theme.rgba(color, 0.10)};"
            f"border-radius: 3px; padding: 2px 7px; font-size: 10px; font-weight: 700; letter-spacing: 0.6px;"
        )


class EmptyState(QWidget):
    def __init__(self, message: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 26, 0, 26)
        label = QLabel(message)
        label.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 12.5px;")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)


class LinkButton(QPushButton):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; color: {theme.ACCENT};"
            f"font-size: 12px; padding: 2px 4px; text-align: left; }}"
            f"QPushButton:hover {{ color: #7ba4f5; }}"
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class Divider(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Divider")
        self.setFixedHeight(1)


class PageHeader(QWidget):
    def __init__(self, title: str, hint: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 6)
        layout.setSpacing(3)
        t = QLabel(title)
        t.setObjectName("PageTitle")
        layout.addWidget(t)
        if hint:
            h = QLabel(hint)
            h.setObjectName("PageHint")
            layout.addWidget(h)


class ConfirmBanner(QFrame):
    """Inline confirmation strip shown when Nova needs approval."""

    approved = Signal()
    declined = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setStyleSheet(
            f"QFrame#Card {{ background: #221d14; border: 1px solid {theme.WARN}55; border-radius: 6px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 13, 16, 13)
        layout.setSpacing(9)

        head = QHBoxLayout()
        self.risk = Pill("high", "failed")
        head.addWidget(self.risk)
        self.title = QLabel()
        self.title.setStyleSheet("font-size: 13.5px; font-weight: 600;")
        self.title.setWordWrap(True)
        head.addWidget(self.title, 1)
        layout.addLayout(head)

        self.detail = QLabel()
        self.detail.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 12px;")
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        no = QPushButton("Cancel")
        yes = QPushButton("Approve")
        yes.setObjectName("Primary")
        no.clicked.connect(self.declined.emit)
        yes.clicked.connect(self.approved.emit)
        buttons.addWidget(no)
        buttons.addWidget(yes)
        layout.addLayout(buttons)
        self.hide()

    def show_request(self, summary: str, details: list[str], risk: str) -> None:
        self.title.setText(summary + "?")
        self.detail.setText(" ".join(details) if details else "Nova needs your approval before continuing.")
        self.risk.setText(f"{risk.upper()} RISK")
        self.risk.apply_color(theme.ERROR if risk == "high" else theme.WARN)
        self.show()
