"""Permission and security page: what Nova may do, and what always needs approval."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core.safety import PROTECTED_PATTERNS, TOOL_RISK, Risk
from .. import theme
from ..widgets import Card, PageHeader, Pill

RISK_NOTE = {
    Risk.LOW: "Runs immediately",
    Risk.MEDIUM: "Confirmation when enabled",
    Risk.HIGH: "Always asks first",
}


class SecurityPage(QWidget):
    def __init__(self, core: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.core = core
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(26, 22, 26, 20)
        layout.setSpacing(14)

        layout.addWidget(PageHeader("Permissions & security",
                                    "Every action Nova can take, and how much approval it needs."))

        for risk, title in [(Risk.HIGH, "Always requires your approval"),
                            (Risk.MEDIUM, "Asks when confirmations are on"),
                            (Risk.LOW, "Runs immediately")]:
            tools = sorted(t for t, r in TOOL_RISK.items() if r is risk)
            card = Card(title)
            note = QLabel(RISK_NOTE[risk])
            note.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11.5px;")
            card.add(note)
            grid = QWidget()
            flow = QVBoxLayout(grid)
            flow.setContentsMargins(0, 4, 0, 0)
            flow.setSpacing(3)
            line = QHBoxLayout()
            per_row = 4
            for i, tool in enumerate(tools):
                chip = QLabel(tool)
                colour = {Risk.HIGH: theme.ERROR, Risk.MEDIUM: theme.WARN, Risk.LOW: theme.TEXT_DIM}[risk]
                chip.setStyleSheet(
                    f"color: {colour}; background: {theme.SURFACE_2}; border: 1px solid {theme.BORDER};"
                    f"border-radius: 3px; padding: 3px 8px; font-size: 11px;"
                )
                line.addWidget(chip)
                if (i + 1) % per_row == 0:
                    line.addStretch(1)
                    flow.addLayout(line)
                    line = QHBoxLayout()
            if line.count():
                line.addStretch(1)
                flow.addLayout(line)
            card.add(grid)
            layout.addWidget(card)

        blocked = Card("Never allowed")
        text = QLabel(
            "Nova refuses outright — no confirmation offered — when a request touches Windows system "
            "folders, Program Files, or asks it to type a password, API key or private key."
        )
        text.setWordWrap(True)
        text.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 12.5px;")
        blocked.add(text)
        for pattern in PROTECTED_PATTERNS[:4]:
            p = QLabel("·  " + pattern.replace("^", "").replace("\\\\", "\\"))
            p.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11.5px; font-family: {theme.MONO};")
            blocked.add(p)
        layout.addWidget(blocked)

        self.decisions = Card("Recent permission decisions")
        self.decisions_body = QVBoxLayout()
        self.decisions_body.setSpacing(4)
        self.decisions.body().addLayout(self.decisions_body)
        clear = QPushButton("Forget remembered decisions")
        clear.clicked.connect(self._forget)
        self.decisions.add(clear)
        layout.addWidget(self.decisions)
        layout.addStretch(1)

        scroll.setWidget(host)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self.refresh()

    def _forget(self) -> None:
        self.core.db.execute("DELETE FROM permissions")
        self.refresh()

    def refresh(self) -> None:
        import time

        while self.decisions_body.count():
            item = self.decisions_body.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        rows = self.core.db.query("SELECT * FROM permissions ORDER BY ts DESC LIMIT 12")
        if not rows:
            label = QLabel("No decisions recorded yet.")
            label.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 12px;")
            self.decisions_body.addWidget(label)
            return
        for r in rows:
            line = QWidget()
            hl = QHBoxLayout(line)
            hl.setContentsMargins(0, 1, 0, 1)
            when = QLabel(time.strftime("%d %b %H:%M", time.localtime(r["ts"])))
            when.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
            when.setFixedWidth(88)
            what = QLabel(f"{r['action']}  {str(r['scope'] or '')[:46]}")
            what.setStyleSheet("font-size: 12px;")
            hl.addWidget(when)
            hl.addWidget(what, 1)
            hl.addWidget(Pill(r["decision"], "completed" if r["decision"] == "allow" else "failed"))
            self.decisions_body.addWidget(line)
