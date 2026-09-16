"""Watchers page: monitor websites and folders."""

from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..widgets import Card, PageHeader

COLUMNS = ["Name", "Type", "Target", "Every", "Last checked", "Status"]


class WatchersPage(QWidget):
    def __init__(self, core: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.core = core
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 20)
        layout.setSpacing(13)
        layout.addWidget(PageHeader("Watchers", "Nova checks these in the background and notifies you on change."))

        creator = Card("Add a watcher")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.kind = QComboBox()
        self.kind.addItems(["Website", "Folder"])
        self.kind.setMaximumWidth(110)
        self.target = QLineEdit()
        self.target.setPlaceholderText("https://example.com  or  C:\\Users\\you\\Downloads")
        self.interval = QSpinBox()
        self.interval.setRange(1, 1440)
        self.interval.setValue(10)
        self.interval.setSuffix(" min")
        self.interval.setMaximumWidth(95)
        add = QPushButton("Add")
        add.setObjectName("Primary")
        add.clicked.connect(self._add)
        row.addWidget(self.kind)
        row.addWidget(self.target, 1)
        row.addWidget(self.interval)
        row.addWidget(add)
        creator.body().addLayout(row)
        layout.addWidget(creator)

        controls = QHBoxLayout()
        self.toggle_btn = QPushButton("Pause / Resume")
        self.check_btn = QPushButton("Check now")
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setObjectName("Danger")
        self.toggle_btn.clicked.connect(self._toggle)
        self.check_btn.clicked.connect(self._check_now)
        self.delete_btn.clicked.connect(self._delete)
        controls.addWidget(self.toggle_btn)
        controls.addWidget(self.check_btn)
        controls.addStretch(1)
        controls.addWidget(self.delete_btn)
        layout.addLayout(controls)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)
        self.refresh()

    def _add(self) -> None:
        target = self.target.text().strip()
        if not target:
            return
        minutes = self.interval.value()
        if self.kind.currentText() == "Website":
            self.core.watchers.add_website(target, minutes * 60)
        else:
            self.core.watchers.add_folder(target, minutes * 60)
        self.target.clear()
        self.refresh()

    def _selected(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return int(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _toggle(self) -> None:
        wid = self._selected()
        if wid is None:
            return
        w = self.core.db.get_watcher(wid)
        if w:
            self.core.db.update_watcher(wid, active=0 if w["active"] else 1)
        self.refresh()

    def _check_now(self) -> None:
        wid = self._selected()
        if wid is None:
            return
        w = self.core.db.get_watcher(wid)
        if w:
            self.core.tasks.run_soon(self.core.watchers.check(w))

    def _delete(self) -> None:
        wid = self._selected()
        if wid is not None:
            self.core.db.delete_watcher(wid)
            self.refresh()

    def refresh(self) -> None:
        from PySide6.QtGui import QColor

        rows = self.core.watchers.list()
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            name = QTableWidgetItem(r["name"])
            name.setData(Qt.ItemDataRole.UserRole, r["id"])
            self.table.setItem(i, 0, name)
            self.table.setItem(i, 1, QTableWidgetItem(r["wtype"]))
            self.table.setItem(i, 2, QTableWidgetItem(r["target"][:80]))
            self.table.setItem(i, 3, QTableWidgetItem(f"{max(1, r['interval_s'] // 60)} min"))
            last = r.get("last_checked")
            self.table.setItem(i, 4, QTableWidgetItem(
                time.strftime("%H:%M", time.localtime(last)) if last else "—"))
            status = "ACTIVE" if r["active"] else "PAUSED"
            cell = QTableWidgetItem(status)
            cell.setForeground(QColor(theme.OK if r["active"] else theme.TEXT_FAINT))
            self.table.setItem(i, 5, cell)
