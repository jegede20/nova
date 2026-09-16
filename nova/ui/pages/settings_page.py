"""Settings page: simple, grouped, beginner-friendly."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...ai.provider import PROVIDER_DEFAULTS
from ...core.settings import DEFAULTS
from ...voice.listener import list_microphones
from ...winplat.startup import is_startup_enabled, set_startup
from .. import theme
from ..widgets import Card, PageHeader, SettingRow, Toggle


class SettingsPage(QWidget):
    def __init__(self, core: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.core = core
        self.s = core.settings
        self._building = True

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        self.layout_ = QVBoxLayout(host)
        self.layout_.setContentsMargins(26, 22, 26, 20)
        self.layout_.setSpacing(14)

        self.layout_.addWidget(PageHeader("Settings", "Nova stores all of this on your PC."))
        self._voice_section()
        self._ai_section()
        self._speech_section()
        self._behaviour_section()
        self._browser_section()
        self._privacy_section()
        self.layout_.addStretch(1)

        scroll.setWidget(host)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self._building = False

    # ---------- helpers ----------
    def _save(self, key: str, value: Any) -> None:
        if self._building:
            return
        self.s.set(key, value)

    def _toggle(self, key: str) -> Toggle:
        t = Toggle(bool(self.s.get(key, DEFAULTS.get(key, False))))
        t.toggled.connect(lambda v, k=key: self._save(k, v))
        return t

    # ---------- sections ----------
    def _voice_section(self) -> None:
        card = Card("Voice")

        wake = QLineEdit(str(self.s.get("wake_word", "hey nova")))
        wake.editingFinished.connect(lambda: self._save("wake_word", wake.text().strip().lower() or "hey nova"))
        card.add(SettingRow("Wake word", wake, "What you say to get Nova's attention."))

        activation = self._toggle("voice_activation")
        activation.toggled.connect(self._on_activation)
        card.add(SettingRow("Voice activation", activation, "Listen for the wake word in the background."))

        self.mic = QComboBox()
        self.mic.addItem("System default", -1)
        for m in list_microphones():
            self.mic.addItem(m["name"][:40], m["index"])
        current = int(self.s.get("microphone_index", -1))
        idx = self.mic.findData(current)
        self.mic.setCurrentIndex(max(0, idx))
        self.mic.currentIndexChanged.connect(lambda: self._save("microphone_index", self.mic.currentData()))
        card.add(SettingRow("Microphone", self.mic, "Which input device Nova listens to."))

        verify = self._toggle("voice_verification")
        card.add(SettingRow("Verify my voice", verify, "Ignore commands from voices Nova doesn't recognise."))

        sens = QDoubleSpinBox()
        sens.setRange(0.40, 0.95)
        sens.setSingleStep(0.05)
        sens.setValue(float(self.s.get("voice_threshold", 0.70)))
        sens.valueChanged.connect(lambda v: self._save("voice_threshold", round(v, 2)))
        card.add(SettingRow("Verification strictness", sens,
                            "Higher is stricter. 0.70 suits most people."))

        enroll = QPushButton("Enroll or re-record my voice")
        enroll.clicked.connect(self._open_enrollment)
        card.add(SettingRow("Voice profile", enroll,
                            "Enrolled." if self.core.verifier.enrolled else "Not enrolled yet."))

        model = QComboBox()
        model.addItems(["tiny.en", "base.en", "small.en", "medium.en"])
        model.setCurrentText(str(self.s.get("stt_model", "base.en")))
        model.currentTextChanged.connect(lambda v: self._save("stt_model", v))
        card.add(SettingRow("Speech recognition model", model,
                            "Runs locally. Larger is more accurate but slower."))
        self.layout_.addWidget(card)

    def _open_enrollment(self) -> None:
        window = self.window()
        if hasattr(window, "show_page"):
            window.show_page("enroll")

    def _on_activation(self, enabled: bool) -> None:
        self._save("voice_activation", enabled)
        if enabled:
            ok, msg = self.core.start_listening()
            if not ok:
                QMessageBox.information(self, "Voice activation", msg)
        else:
            self.core.stop_listening()

    def _ai_section(self) -> None:
        card = Card("AI provider")

        self.provider = QComboBox()
        self.provider.addItems(list(PROVIDER_DEFAULTS))
        self.provider.setCurrentText(str(self.s.get("ai_provider", "openai")))
        self.provider.currentTextChanged.connect(self._on_provider)
        card.add(SettingRow("Provider", self.provider, "Which service interprets your commands."))

        self.model = QLineEdit(str(self.s.get("ai_model", "gpt-4o-mini")))
        self.model.editingFinished.connect(lambda: self._save("ai_model", self.model.text().strip()))
        card.add(SettingRow("Model", self.model, "Must support tool calling."))

        self.vision = QLineEdit(str(self.s.get("vision_model", "gpt-4o-mini")))
        self.vision.editingFinished.connect(lambda: self._save("vision_model", self.vision.text().strip()))
        card.add(SettingRow("Vision model", self.vision, "Used for “what's on my screen”."))

        self.base_url = QLineEdit(str(self.s.get("ai_base_url", "")))
        self.base_url.setPlaceholderText("Leave blank for the default endpoint")
        self.base_url.editingFinished.connect(lambda: self._save("ai_base_url", self.base_url.text().strip()))
        card.add(SettingRow("API endpoint", self.base_url, "For self-hosted or compatible servers."))

        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        existing = self.s.api_key_for(str(self.s.get("ai_provider", "openai")))
        self.api_key.setPlaceholderText("Saved securely" if existing else "Paste your API key")
        self.api_key.editingFinished.connect(self._save_key)
        card.add(SettingRow("API key", self.api_key,
                            f"Stored in {self.s.secrets.backend} — never in the database or logs."))

        test = QPushButton("Test connection")
        test.clicked.connect(self._test)
        self.test_label = QLabel("")
        self.test_label.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11.5px;")
        row = QHBoxLayout()
        row.addWidget(test)
        row.addWidget(self.test_label, 1)
        card.body().addLayout(row)
        self.layout_.addWidget(card)

    def _on_provider(self, name: str) -> None:
        self._save("ai_provider", name)
        defaults = PROVIDER_DEFAULTS.get(name, {})
        if defaults.get("model"):
            self.model.setText(defaults["model"])
            self._save("ai_model", defaults["model"])
        self.base_url.setText(defaults.get("base_url", ""))
        self._save("ai_base_url", defaults.get("base_url", ""))
        self.core.agent.reload_provider()

    def _save_key(self) -> None:
        key = self.api_key.text().strip()
        if not key:
            return
        provider = str(self.s.get("ai_provider", "openai"))
        self.s.set(f"{provider}_api_key", key)
        self.api_key.clear()
        self.api_key.setPlaceholderText("Saved securely")
        self.core.agent.reload_provider()

    def _test(self) -> None:
        self.test_label.setText("Testing…")
        self.core.agent.reload_provider()

        async def check() -> None:
            from ...ai.provider import AIError, build_provider

            provider = build_provider(self.s)
            if not provider.available():
                self._set_test("No API key configured.", theme.WARN)
                return
            try:
                resp = await provider.chat([{"role": "user", "content": "Reply with the single word: ready"}])
                self._set_test(f"Connected — {provider.model} replied.", theme.OK) if resp else None
            except AIError as e:
                self._set_test(str(e)[:70], theme.ERROR)
            except Exception as e:
                self._set_test(f"{type(e).__name__}", theme.ERROR)

        self.core.tasks.run_soon(check())

    def _set_test(self, text: str, color: str) -> None:
        self.test_label.setText(text)
        self.test_label.setStyleSheet(f"color: {color}; font-size: 11.5px;")

    def _speech_section(self) -> None:
        card = Card("Spoken responses")
        card.add(SettingRow("Speak replies out loud", self._toggle("tts_enabled")))
        rate = QSpinBox()
        rate.setRange(110, 260)
        rate.setValue(int(self.s.get("tts_rate", 185)))
        rate.setSuffix(" wpm")
        rate.valueChanged.connect(lambda v: self._save("tts_rate", v))
        card.add(SettingRow("Speaking speed", rate))

        voice = QComboBox()
        voice.addItem("System default", "")
        for name in self.core.tts.list_voices():
            voice.addItem(name, name)
        voice.setCurrentText(str(self.s.get("tts_voice", "")) or "System default")
        voice.currentTextChanged.connect(lambda v: self._save("tts_voice", "" if v == "System default" else v))
        card.add(SettingRow("Voice", voice))

        test = QPushButton("Test voice")
        test.clicked.connect(lambda: self.core.tts.speak("Nova is ready when you are."))
        card.add(SettingRow("Preview", test))
        self.layout_.addWidget(card)

    def _behaviour_section(self) -> None:
        card = Card("Safety and behaviour")
        card.add(SettingRow("Confirm medium-risk actions", self._toggle("confirm_medium_risk"),
                            "Moving files, closing apps, clicking and typing."))

        always = QLabel("Always on")
        always.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 12px;")
        card.add(SettingRow("Confirm high-risk actions", always,
                            "Deleting, uploading, purchases — this cannot be disabled."))

        bulk = QSpinBox()
        bulk.setRange(1, 100)
        bulk.setValue(int(self.s.get("bulk_file_threshold", 5)))
        bulk.valueChanged.connect(lambda v: self._save("bulk_file_threshold", v))
        card.add(SettingRow("Bulk file warning above", bulk,
                            "Ask before touching more files than this at once."))

        card.add(SettingRow("Windows notifications", self._toggle("notifications_enabled")))

        startup = Toggle(is_startup_enabled())
        startup.toggled.connect(self._on_startup)
        card.add(SettingRow("Start Nova with Windows", startup, "Nova starts minimised in the system tray."))

        card.add(SettingRow("Close to tray", self._toggle("minimize_to_tray"),
                            "Keep Nova running when you close the window."))
        self.layout_.addWidget(card)

    def _on_startup(self, enabled: bool) -> None:
        ok, msg = set_startup(enabled)
        self._save("start_with_windows", enabled and ok)
        if not ok:
            QMessageBox.information(self, "Start with Windows", msg)

    def _browser_section(self) -> None:
        card = Card("Browser")
        channel = QComboBox()
        channel.addItems(["chrome", "msedge", "chromium"])
        channel.setCurrentText(str(self.s.get("browser_channel", "chrome")))
        channel.currentTextChanged.connect(lambda v: self._save("browser_channel", v))
        card.add(SettingRow("Browser to automate", channel))
        card.add(SettingRow("Run browser hidden", self._toggle("browser_headless"),
                            "Off means you can watch Nova work."))
        folder = QLineEdit(str(self.s.get("browser_download_dir", "")))
        folder.setPlaceholderText("Default Downloads folder")
        folder.editingFinished.connect(lambda: self._save("browser_download_dir", folder.text().strip()))
        card.add(SettingRow("Download folder", folder))
        self.layout_.addWidget(card)

    def _privacy_section(self) -> None:
        card = Card("Privacy and data")
        card.add(SettingRow("Store command history", self._toggle("store_history")))
        card.add(SettingRow("Allow screen capture", self._toggle("allow_screen_capture"),
                            "Needed for “what's on my screen”. Screenshots are only sent when you ask."))
        clear = QPushButton("Clear local history")
        clear.setObjectName("Danger")
        clear.clicked.connect(self._clear_history)
        card.add(SettingRow("History", clear))

        forget = QPushButton("Delete voice profile")
        forget.setObjectName("Danger")
        forget.clicked.connect(self._forget_voice)
        card.add(SettingRow("Voice profile", forget))
        self.layout_.addWidget(card)

    def _clear_history(self) -> None:
        if QMessageBox.question(self, "Clear history", "Delete all stored history?") == \
                QMessageBox.StandardButton.Yes:
            self.core.db.clear_history()

    def _forget_voice(self) -> None:
        if QMessageBox.question(self, "Delete voice profile",
                                "Remove your enrolled voice profile?") == QMessageBox.StandardButton.Yes:
            self.core.verifier.profile.reset()

    def refresh(self) -> None:
        pass
