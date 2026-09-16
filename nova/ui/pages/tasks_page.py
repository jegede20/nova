"""Tasks page: see, pause, resume and cancel background work."""

from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..widgets import PageHeader

COLUMNS = ["Task", "State", "Progress", "Started", "Detail"]


class TasksPage(QWidget):
    def __init__(self, core: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.core = core
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 20)
        layout.setSpacing(13)

        layout.addWidget(PageHeader("Tasks", "Long-running work Nova is doing in the background."))

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.pause_btn = QPushButton("Pause")
        self.resume_btn = QPushButton("Resume")
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("Danger")
        self.cancel_all_btn = QPushButton("Cancel all")
        self.cancel_all_btn.setObjectName("Danger")
        refresh = QPushButton("Refresh")
        self.pause_btn.clicked.connect(lambda: self._act("pause"))
        self.resume_btn.clicked.connect(lambda: self._act("resume"))
        self.cancel_btn.clicked.connect(lambda: self._act("cancel"))
        self.cancel_all_btn.clicked.connect(self._cancel_all)
        refresh.clicked.connect(self.refresh)
        for b in (self.pause_btn, self.resume_btn, self.cancel_btn):
            controls.addWidget(b)
        controls.addStretch(1)
        controls.addWidget(self.cancel_all_btn)
        controls.addWidget(refresh)
        layout.addLayout(controls)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        for i in (1, 2, 3):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)
        self.refresh()

    def _selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return int(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _act(self, action: str) -> None:
        task_id = self._selected_id()
        if task_id is None:
            return
        getattr(self.core.tasks, action)(task_id)
        self.refresh()

    def _cancel_all(self) -> None:
        self.core.tasks.cancel_all()
        self.refresh()

    def refresh(self) -> None:
        rows = self.core.db.list_tasks(limit=60)
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            title = QTableWidgetItem(r["title"])
            title.setData(Qt.ItemDataRole.UserRole, r["id"])
            self.table.setItem(i, 0, title)

            state = QTableWidgetItem(r["state"].upper())
            state.setForeground(Qt.GlobalColor.white)
            from PySide6.QtGui import QColor

            state.setForeground(QColor(theme.state_color(r["state"])))
            self.table.setItem(i, 1, state)

            pct = int((r.get("progress") or 0) * 100)
            self.table.setItem(i, 2, QTableWidgetItem(f"{pct}%"))
            started = time.strftime("%H:%M", time.localtime(r["created_at"]))
            self.table.setItem(i, 3, QTableWidgetItem(started))
            detail = r.get("error") or r.get("result") or ""
            self.table.setItem(i, 4, QTableWidgetItem(str(detail)[:110]))
