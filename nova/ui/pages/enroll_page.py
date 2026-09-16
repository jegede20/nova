"""Voice enrollment: record a few samples so Nova recognises your voice."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...voice.listener import EnrollmentRecorder
from ...voice.speaker_id import REQUIRED_SAMPLES, SpeakerProfile
from .. import theme
from ..widgets import Card, PageHeader

PHRASES = [
    "Hey Nova, open my downloads folder.",
    "Hey Nova, what is on my screen right now?",
    "Hey Nova, create a folder called projects on my desktop.",
    "Hey Nova, find the document I saved yesterday.",
    "Hey Nova, watch this page and tell me when it changes.",
]


class _RecordWorker(QObject):
    done = Signal(object, str)

    def __init__(self, recorder: EnrollmentRecorder, seconds: float) -> None:
        super().__init__()
        self.recorder = recorder
        self.seconds = seconds

    def run(self) -> None:
        audio, message = self.recorder.record(self.seconds)
        self.done.emit(audio, message)


class EnrollPage(QWidget):
    def __init__(self, core: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.core = core
        self.recorder = EnrollmentRecorder(core.settings)
        self.profile = SpeakerProfile()
        self.samples = 0
        self._thread: QThread | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 20)
        layout.setSpacing(14)
        layout.addWidget(PageHeader(
            "Voice enrollment",
            "Record a few short phrases so Nova can tell your voice from other people's."))

        card = Card()
        self.status = QLabel()
        self.status.setStyleSheet("font-size: 14px; font-weight: 600;")
        card.add(self.status)

        self.phrase = QLabel()
        self.phrase.setWordWrap(True)
        self.phrase.setStyleSheet(
            f"font-size: 16px; color: {theme.TEXT}; padding: 16px; "
            f"background: {theme.BG}; border: 1px solid {theme.BORDER}; border-radius: 5px;"
        )
        self.phrase.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.add(self.phrase)

        self.progress = QProgressBar()
        self.progress.setRange(0, REQUIRED_SAMPLES)
        self.progress.setValue(0)
        card.add(self.progress)

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 12px;")
        card.add(self.hint)

        buttons = QHBoxLayout()
        self.record_btn = QPushButton("Record sample")
        self.record_btn.setObjectName("Primary")
        self.record_btn.clicked.connect(self._record)
        self.restart_btn = QPushButton("Start over")
        self.restart_btn.clicked.connect(self._restart)
        buttons.addWidget(self.record_btn)
        buttons.addWidget(self.restart_btn)
        buttons.addStretch(1)
        card.body().addLayout(buttons)
        layout.addWidget(card)

        note = Card("How this is stored")
        for line in [
            "Nova saves a mathematical voice signature, not your recordings.",
            "Audio is discarded as soon as the signature is computed.",
            "Voice matching is a convenience filter, not security — risky actions still need approval.",
        ]:
            label = QLabel("·  " + line)
            label.setWordWrap(True)
            label.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 12px;")
            note.add(label)
        layout.addWidget(note)
        layout.addStretch(1)
        self.refresh()

    # ---------- flow ----------
    def refresh(self) -> None:
        self.profile.load()
        if self.samples == 0 and self.profile.enrolled:
            self.status.setText("Your voice is enrolled")
            self.hint.setText("Record again if Nova often fails to recognise you.")
            self.phrase.setText("Press “Record sample” to enroll again.")
            self.progress.setValue(REQUIRED_SAMPLES)
        else:
            self.status.setText(f"Sample {min(self.samples + 1, REQUIRED_SAMPLES)} of {REQUIRED_SAMPLES}")
            self.phrase.setText(PHRASES[self.samples % len(PHRASES)])
            self.hint.setText("Press Record, then read the phrase aloud in your normal voice.")
            self.progress.setValue(self.samples)

    def _restart(self) -> None:
        self.samples = 0
        self.profile = SpeakerProfile()
        self.profile.vectors.clear()
        self.refresh()

    def _record(self) -> None:
        if self.samples == 0:
            self.profile.vectors.clear()
        self.record_btn.setEnabled(False)
        self.record_btn.setText("Listening…")
        self.hint.setText("Speak now.")

        self._thread = QThread()
        worker = _RecordWorker(self.recorder, 3.5)
        worker.moveToThread(self._thread)
        self._worker = worker
        self._thread.started.connect(worker.run)
        worker.done.connect(self._on_recorded)
        worker.done.connect(self._thread.quit)
        self._thread.start()

    def _on_recorded(self, audio: Any, message: str) -> None:
        self.record_btn.setEnabled(True)
        self.record_btn.setText("Record sample")
        if audio is None:
            self.hint.setText(message)
            self.status.setText("Recording failed")
            return
        ok, note = self.profile.add_sample(audio)
        if not ok:
            self.hint.setText(note)
            return
        self.samples += 1
        self.progress.setValue(self.samples)
        if self.samples >= REQUIRED_SAMPLES:
            saved, detail = self.profile.finalize()
            if saved:
                self.core.verifier.profile.load()
                self.status.setText("Voice profile saved")
                self.phrase.setText("Nova will now recognise your voice.")
                self.hint.setText(detail + "  You can re-record any time from Settings.")
                self.core.settings.set("voice_verification", True)
                self.samples = 0
            else:
                self.hint.setText(detail)
            return
        self.status.setText(f"Sample {self.samples + 1} of {REQUIRED_SAMPLES}")
        self.phrase.setText(PHRASES[self.samples % len(PHRASES)])
        self.hint.setText(note)
