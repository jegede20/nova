"""Dashboard: status, command input, plan, activity, tasks and watchers at a glance."""

from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..widgets import Card, ConfirmBanner, EmptyState, PageHeader, Pill, Row, StatusDot

STATE_TEXT = {
    "idle": "Ready",
    "listening": "Listening",
    "recording": "Listening",
    "wake": "Wake word detected",
    "thinking": "Thinking",
    "planning": "Planning",
    "executing": "Executing",
    "waiting_confirmation": "Waiting for your confirmation",
    "speaking": "Speaking",
    "failed": "Something went wrong",
    "paused": "Paused",
    "stopped": "Not listening",
}


class DashboardPage(QWidget):
    command_submitted = Signal(str)
    stop_requested = Signal()
    confirm_answered = Signal(bool)

    def __init__(self, core: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.core = core
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 20)
        outer.setSpacing(14)

        outer.addWidget(PageHeader("Dashboard", "Say “Hey Nova” or type a command below."))

        # --- status strip ---
        status_card = Card()
        strip = QHBoxLayout()
        strip.setSpacing(11)
        self.dot = StatusDot("idle", 10)
        strip.addWidget(self.dot)
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("font-size: 15px; font-weight: 600;")
        strip.addWidget(self.status_label)
        self.substatus = QLabel("")
        self.substatus.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 12px;")
        strip.addWidget(self.substatus)
        strip.addStretch(1)

        self.mic_pill = Pill("mic off", "stopped")
        strip.addWidget(self.mic_pill)
        self.provider_label = QLabel("")
        self.provider_label.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
        strip.addWidget(self.provider_label)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("Danger")
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        strip.addWidget(self.stop_btn)
        status_card.body().addLayout(strip)
        outer.addWidget(status_card)

        # --- confirmation banner ---
        self.confirm = ConfirmBanner()
        self.confirm.approved.connect(lambda: self.confirm_answered.emit(True))
        self.confirm.declined.connect(lambda: self.confirm_answered.emit(False))
        outer.addWidget(self.confirm)

        # --- command input ---
        input_row = QHBoxLayout()
        input_row.setSpacing(9)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type a command, e.g. open my Downloads folder")
        self.input.returnPressed.connect(self._submit)
        self.input.setMinimumHeight(38)
        send = QPushButton("Send")
        send.setObjectName("Primary")
        send.setMinimumHeight(38)
        send.clicked.connect(self._submit)
        input_row.addWidget(self.input, 1)
        input_row.addWidget(send)
        outer.addLayout(input_row)

        # --- plan (hidden until a complex request) ---
        self.plan_card = Card("Action plan")
        self.plan_body = QVBoxLayout()
        self.plan_body.setSpacing(3)
        self.plan_card.body().addLayout(self.plan_body)
        self.plan_card.hide()
        outer.addWidget(self.plan_card)

        # --- columns ---
        columns = QHBoxLayout()
        columns.setSpacing(14)

        activity_card = Card("Recent activity")
        self.activity_area = QScrollArea()
        self.activity_area.setWidgetResizable(True)
        self.activity_area.setStyleSheet("background: transparent;")
        self.activity_area.viewport().setStyleSheet("background: transparent;")
        self.activity_host = QWidget()
        self.activity_body = QVBoxLayout(self.activity_host)
        self.activity_body.setContentsMargins(0, 0, 0, 0)
        self.activity_body.setSpacing(1)
        self.activity_body.addStretch(1)
        self.activity_area.setWidget(self.activity_host)
        self.activity_area.setMinimumHeight(210)
        activity_card.add(self.activity_area)
        columns.addWidget(activity_card, 3)

        right = QVBoxLayout()
        right.setSpacing(14)

        self.tasks_card = Card("Active tasks")
        self.tasks_body = QVBoxLayout()
        self.tasks_body.setSpacing(5)
        self.tasks_card.body().addLayout(self.tasks_body)
        right.addWidget(self.tasks_card)

        self.watchers_card = Card("Watchers")
        self.watchers_body = QVBoxLayout()
        self.watchers_body.setSpacing(5)
        self.watchers_card.body().addLayout(self.watchers_body)
        right.addWidget(self.watchers_card)
        right.addStretch(1)
        columns.addLayout(right, 2)

        outer.addLayout(columns, 1)
        self.refresh()

    # ---------- interaction ----------
    def _submit(self) -> None:
        text = self.input.text().strip()
        if text:
            self.input.clear()
            self.command_submitted.emit(text)

    def set_state(self, state: str, detail: str = "") -> None:
        self.dot.set_state(state)
        self.status_label.setText(STATE_TEXT.get(state, state.replace("_", " ").title()))
        self.substatus.setText(detail)

    def set_listening(self, listening: bool) -> None:
        self.mic_pill.setText("MIC ON" if listening else "MIC OFF")
        self.mic_pill.apply_color(theme.OK if listening else theme.TEXT_FAINT)

    def show_plan(self, steps: list[str]) -> None:
        while self.plan_body.count():
            item = self.plan_body.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not steps:
            self.plan_card.hide()
            return
        for i, step in enumerate(steps, 1):
            label = QLabel(f"{i}.  {step}")
            label.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 12.5px;")
            label.setWordWrap(True)
            self.plan_body.addWidget(label)
        self.plan_card.show()

    def add_activity(self, text: str, state: str = "ok") -> None:
        row = Row(text, state, time.strftime("%H:%M"))
        self.activity_body.insertWidget(self.activity_body.count() - 1, row)
        while self.activity_body.count() > 41:
            item = self.activity_body.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        bar = self.activity_area.verticalScrollBar()
        bar.setValue(bar.maximum())

    def ask_confirmation(self, summary: str, details: list[str], risk: str) -> None:
        self.confirm.show_request(summary, details, risk)

    def hide_confirmation(self) -> None:
        self.confirm.hide()

    # ---------- data ----------
    def refresh(self) -> None:
        status = self.core.status()
        self.provider_label.setText(f"{status['provider']} · {status['model']}")
        self.set_listening(bool(status["listening"]))
        self._fill_tasks()
        self._fill_watchers()

    def _clear(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _fill_tasks(self) -> None:
        self._clear(self.tasks_body)
        rows = self.core.tasks.active()
        if not rows:
            self.tasks_body.addWidget(EmptyState("No tasks running"))
            return
        for r in rows[:6]:
            line = QWidget()
            hl = QHBoxLayout(line)
            hl.setContentsMargins(0, 2, 0, 2)
            name = QLabel(r["title"][:36])
            name.setStyleSheet("font-size: 12.5px;")
            hl.addWidget(name, 1)
            hl.addWidget(Pill(r["state"], r["state"]))
            self.tasks_body.addWidget(line)

    def _fill_watchers(self) -> None:
        self._clear(self.watchers_body)
        rows = self.core.watchers.list(active_only=True)
        if not rows:
            self.watchers_body.addWidget(EmptyState("Nothing being monitored"))
            return
        for r in rows[:6]:
            line = QWidget()
            hl = QHBoxLayout(line)
            hl.setContentsMargins(0, 2, 0, 2)
            name = QLabel(f"{r['name'][:30]}")
            name.setStyleSheet("font-size: 12.5px;")
            hl.addWidget(name, 1)
            every = QLabel(f"every {max(1, r['interval_s'] // 60)}m")
            every.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
            hl.addWidget(every)
            self.watchers_body.addWidget(line)

    def load_history(self, rows: list[dict]) -> None:
        for r in reversed(rows[:18]):
            if r["kind"] in {"action", "response"} and r.get("detail"):
                self.add_activity(r["detail"][:90], r.get("status") or "ok")
