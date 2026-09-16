"""About page: what Nova is, what's installed, and how data is handled."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from ...core.paths import app_data_dir
from .. import theme
from ..widgets import Card, PageHeader

VERSION = "1.0.0"


class AboutPage(QWidget):
    def __init__(self, core: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.core = core
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(26, 22, 26, 20)
        layout.setSpacing(14)

        layout.addWidget(PageHeader("About Nova", f"Version {VERSION} — a local-first Windows voice agent."))

        intro = Card()
        text = QLabel(
            "Nova listens for its wake word, verifies your voice, turns speech into text on this PC, "
            "then asks an AI model which of its controlled tools to run. Every action goes through a "
            "safety check, and risky ones need your explicit approval.\n\n"
            "Nova never gives the AI model a shell. It can only call the tools listed in the code, "
            "with validated arguments."
        )
        text.setWordWrap(True)
        text.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 12.5px; line-height: 150%;")
        intro.add(text)
        layout.addWidget(intro)

        self.caps = Card("Capabilities")
        self.caps_body = QVBoxLayout()
        self.caps_body.setSpacing(5)
        self.caps.body().addLayout(self.caps_body)
        layout.addWidget(self.caps)

        privacy = Card("Privacy")
        for line in [
            "Microphone audio is processed locally by Whisper. Raw audio is never uploaded.",
            "No recordings are stored — voice enrollment keeps mathematical embeddings only.",
            "Screenshots are sent to the AI provider only when you ask about your screen.",
            "API keys live in Windows Credential Manager, never in the database or logs.",
            f"All data is stored in {app_data_dir()}",
        ]:
            label = QLabel("·  " + line)
            label.setWordWrap(True)
            label.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 12px;")
            privacy.add(label)
        layout.addWidget(privacy)

        buttons = QHBoxLayout()
        open_data = QPushButton("Open data folder")
        open_data.clicked.connect(self._open_data)
        buttons.addWidget(open_data)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addStretch(1)

        scroll.setWidget(host)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self.refresh()

    def _open_data(self) -> None:
        from ...core.tools.files import open_folder

        open_folder(str(app_data_dir()))

    def refresh(self) -> None:
        while self.caps_body.count():
            item = self.caps_body.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for cap in self.core.capability_report():
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 1, 0, 1)
            mark = QLabel("✓" if cap["ok"] else "○")
            mark.setStyleSheet(f"color: {theme.OK if cap['ok'] else theme.TEXT_FAINT}; font-size: 12px;")
            mark.setFixedWidth(16)
            name = QLabel(cap["name"])
            name.setStyleSheet("font-size: 12.5px;")
            detail = QLabel(cap["detail"])
            detail.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11.5px;")
            hl.addWidget(mark)
            hl.addWidget(name)
            hl.addStretch(1)
            hl.addWidget(detail)
            self.caps_body.addWidget(row)
