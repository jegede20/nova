"""History page: the action log."""

from __future__ import annotations

import time
from typing import Any

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..widgets import PageHeader

COLUMNS = ["Time", "Type", "Command", "Action / result", "Status"]
STATUS_COLORS = {"ok": theme.OK, "failed": theme.ERROR, "denied": theme.WARN}


class HistoryPage(QWidget):
    def __init__(self, core: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.core = core
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 20)
        layout.setSpacing(13)
        layout.addWidget(PageHeader("History", "Everything Nova has done on this PC, stored locally."))

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search history")
        self.search.textChanged.connect(self.refresh)
        self.filter = QComboBox()
        self.filter.addItems(["All", "Commands", "Actions", "Errors"])
        self.filter.setMaximumWidth(130)
        self.filter.currentTextChanged.connect(self.refresh)
        clear = QPushButton("Clear history")
        clear.setObjectName("Danger")
        clear.clicked.connect(self._clear)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.filter)
        bar.addWidget(clear)
        layout.addLayout(bar)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)
        self.refresh()

    def _clear(self) -> None:
        answer = QMessageBox.question(self, "Clear history",
                                      "Delete all locally stored command history?")
        if answer == QMessageBox.StandardButton.Yes:
            self.core.db.clear_history()
            self.refresh()

    def refresh(self) -> None:
        rows = self.core.db.recent_history(400)
        needle = self.search.text().lower().strip()
        mode = self.filter.currentText()
        if mode == "Commands":
            rows = [r for r in rows if r["kind"] == "command"]
        elif mode == "Actions":
            rows = [r for r in rows if r["kind"] == "action"]
        elif mode == "Errors":
            rows = [r for r in rows if r["kind"] == "error" or r.get("status") == "failed"]
        if needle:
            rows = [r for r in rows
                    if needle in (r.get("command") or "").lower() or needle in (r.get("detail") or "").lower()]

        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(time.strftime("%d %b %H:%M", time.localtime(r["ts"]))))
            self.table.setItem(i, 1, QTableWidgetItem(r["kind"]))
            self.table.setItem(i, 2, QTableWidgetItem((r.get("command") or "")[:90]))
            self.table.setItem(i, 3, QTableWidgetItem((r.get("detail") or "")[:130]))
            status = r.get("status") or ""
            cell = QTableWidgetItem(status.upper())
            if status in STATUS_COLORS:
                cell.setForeground(QColor(STATUS_COLORS[status]))
            self.table.setItem(i, 4, cell)
