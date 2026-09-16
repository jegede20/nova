"""Text-to-speech.

Speech runs on its own thread with a queue so speaking never blocks the UI or
the agent. Uses pyttsx3 (SAPI5 on Windows); silently no-ops if unavailable.
"""

from __future__ import annotations

import queue
import threading
from typing import Any

from ..core.logging_setup import get_logger

log = get_logger("tts")


class TextToSpeech:
    def __init__(self, settings: Any = None) -> None:
        self.settings = settings
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._engine = None
        self._available: bool | None = None
        self._lock = threading.Lock()

    # ---------- setup ----------
    def _make_engine(self):
        try:
            import pyttsx3

            engine = pyttsx3.init()
            rate = int(self._opt("tts_rate", 185))
            engine.setProperty("rate", rate)
            voice = self._opt("tts_voice", "")
            if voice:
                for v in engine.getProperty("voices"):
                    if voice.lower() in (v.name or "").lower() or voice == v.id:
                        engine.setProperty("voice", v.id)
                        break
            return engine
        except Exception as e:
            log.warning("Text to speech unavailable: %s", e)
            return None

    def _opt(self, key: str, default: Any) -> Any:
        if self.settings is None:
            return default
        try:
            return self.settings.get(key, default)
        except Exception:
            return default

    @property
    def available(self) -> bool:
        if self._available is None:
            try:
                import pyttsx3  # noqa: F401

                self._available = True
            except Exception:
                self._available = False
        return bool(self._available)

    def list_voices(self) -> list[str]:
        try:
            import pyttsx3

            engine = pyttsx3.init()
            names = [v.name for v in engine.getProperty("voices")]
            engine.stop()
            return names
        except Exception:
            return []

    # ---------- speaking ----------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._worker, name="nova-tts", daemon=True)
        self._thread.start()

    def _worker(self) -> None:
        engine = self._make_engine()
        if engine is None:
            return
        self._engine = engine
        while True:
            text = self._queue.get()
            if text is None:
                break
            try:
                engine.say(text)
                engine.runAndWait()
            except Exception as e:
                log.warning("Speech failed: %s", e)
            finally:
                self._queue.task_done()

    def speak(self, text: str) -> None:
        if not text or not self._opt("tts_enabled", True):
            return
        if not self.available:
            return
        self.start()
        clean = _spoken_form(text)
        if clean:
            self._queue.put(clean[:600])

    def stop(self) -> None:
        """Interrupt current speech and clear the queue."""
        with self._lock:
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                except queue.Empty:
                    break
        if self._engine:
            try:
                self._engine.stop()
            except Exception:
                pass

    def shutdown(self) -> None:
        self.stop()
        self._queue.put(None)


def _spoken_form(text: str) -> str:
    """Strip markdown/paths noise so spoken output stays natural."""
    import re

    t = re.sub(r"[*_`#]+", "", text)
    t = re.sub(r"\s+", " ", t).strip()
    return t
