"""Microphone listener: wake word -> speaker check -> command capture.

Audio stays on the machine. We keep a small rolling buffer, transcribe short
chunks locally with Whisper to spot the wake phrase, and only after the wake
word and speaker check does the resulting *text* go to the AI provider.
"""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..core.logging_setup import get_logger
from .speaker_id import SpeakerVerifier
from .stt import SAMPLE_RATE, SpeechToText, Transcript

log = get_logger("listener")

CHUNK = 1600                 # 100 ms frames
WAKE_WINDOW_S = 2.0          # audio examined for the wake word
COMMAND_MAX_S = 12.0
SILENCE_END_S = 1.1
SILENCE_RMS = 0.012


@dataclass
class VoiceCommand:
    text: str
    confidence: float
    authorized: bool
    speaker_score: float
    reason: str = ""


def list_microphones() -> list[dict[str, Any]]:
    try:
        import sounddevice as sd

        return [
            {"index": i, "name": d["name"], "channels": d["max_input_channels"]}
            for i, d in enumerate(sd.query_devices())
            if d["max_input_channels"] > 0
        ]
    except Exception as e:
        log.debug("Could not list microphones: %s", e)
        return []


def microphone_available() -> bool:
    return bool(list_microphones())


def rms(audio: np.ndarray) -> float:
    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(audio))))


class VoiceListener:
    """Background wake-word listener. Start/stop freely; safe when no mic exists."""

    def __init__(
        self,
        settings: Any,
        stt: SpeechToText | None = None,
        verifier: SpeakerVerifier | None = None,
        on_command: Callable[[VoiceCommand], None] | None = None,
        on_state: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings
        self.stt = stt or SpeechToText(settings)
        self.verifier = verifier or SpeakerVerifier(settings)
        self.on_command = on_command
        self.on_state = on_state
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._audio_q: queue.Queue[np.ndarray] = queue.Queue(maxsize=200)
        self.last_error = ""
        self.running = False

    # ---------- control ----------
    def start(self) -> tuple[bool, str]:
        if self.running:
            return True, "Already listening."
        if not self.settings.get("voice_activation", True):
            return False, "Voice activation is turned off in Settings."
        try:
            import sounddevice  # noqa: F401
        except ImportError:
            self.last_error = ("Voice input needs the sounddevice package. "
                               "Install it with: pip install sounddevice")
            return False, self.last_error
        if not microphone_available():
            self.last_error = "No microphone was detected."
            return False, self.last_error
        if not self.stt.available:
            self.last_error = ("Speech recognition needs faster-whisper. "
                               "Install it with: pip install faster-whisper")
            return False, self.last_error

        self._stop.clear()
        self._paused.clear()
        self._thread = threading.Thread(target=self._run, name="nova-listener", daemon=True)
        self._thread.start()
        self.running = True
        self._emit("listening")
        return True, "Listening for the wake word."

    def stop(self) -> None:
        self._stop.set()
        self.running = False
        if self._thread:
            self._thread.join(timeout=3)
        self._emit("stopped")

    def pause(self) -> None:
        self._paused.set()
        self._emit("paused")

    def resume(self) -> None:
        self._paused.clear()
        self._emit("listening")

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def _emit(self, state: str) -> None:
        if self.on_state:
            try:
                self.on_state(state)
            except Exception:
                log.exception("Listener state callback failed")

    # ---------- audio ----------
    def _device(self) -> int | None:
        idx = int(self.settings.get("microphone_index", -1))
        return None if idx < 0 else idx

    def _run(self) -> None:
        import sounddevice as sd

        def callback(indata, frames, time_info, status):  # noqa: ANN001
            if status:
                log.debug("Audio status: %s", status)
            try:
                self._audio_q.put_nowait(indata[:, 0].copy())
            except queue.Full:
                pass

        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                                blocksize=CHUNK, device=self._device(), callback=callback):
                self._loop()
        except Exception as e:
            self.last_error = f"Microphone error: {e}"
            log.error(self.last_error)
            self.running = False
            self._emit("error")

    def _loop(self) -> None:
        frames_needed = max(1, int(WAKE_WINDOW_S * SAMPLE_RATE / CHUNK))
        window: deque[np.ndarray] = deque(maxlen=frames_needed)
        last_check = 0.0
        while not self._stop.is_set():
            try:
                chunk = self._audio_q.get(timeout=0.5)
            except queue.Empty:
                continue
            if self._paused.is_set():
                window.clear()
                continue
            window.append(chunk)

            # Only run recognition when there is actual sound, roughly twice a second.
            now = time.time()
            if now - last_check < 0.5 or len(window) < frames_needed:
                continue
            audio = np.concatenate(list(window))
            if rms(audio) < SILENCE_RMS:
                continue
            last_check = now

            transcript = self.stt.transcribe(audio)
            if self._has_wake_word(transcript.text):
                window.clear()
                self._handle_wake(transcript)

    def _has_wake_word(self, text: str) -> bool:
        wake = str(self.settings.get("wake_word", "hey nova")).lower().strip()
        cleaned = "".join(c for c in text.lower() if c.isalnum() or c.isspace())
        if wake in cleaned:
            return True
        # tolerate common mishearings of "nova"
        variants = {"hey nova", "hi nova", "hey noca", "hey nouva", "a nova", "hey novah"}
        return wake == "hey nova" and any(v in cleaned for v in variants)

    def _handle_wake(self, wake_transcript: Transcript) -> None:
        self._emit("wake")
        log.info("Wake word detected")

        # The command may already be in the same utterance ("hey nova, open chrome").
        inline = self._strip_wake(wake_transcript.text)
        audio = self._record_command()

        if inline and len(inline.split()) >= 2:
            text, confidence = inline, wake_transcript.confidence
            if audio is not None and len(audio) > SAMPLE_RATE * 0.8:
                extra = self.stt.transcribe(audio)
                if extra.text.strip():
                    text = f"{inline} {extra.text}".strip()
                    confidence = min(confidence, extra.confidence)
        else:
            if audio is None or len(audio) < SAMPLE_RATE * 0.4:
                self._deliver(VoiceCommand("", 0.0, True, 1.0, "I didn't hear a command after the wake word."))
                return
            result = self.stt.transcribe(audio)
            text, confidence = result.text, result.confidence

        # Speaker verification on the captured command audio.
        authorized, score, reason = True, 1.0, ""
        if audio is not None and len(audio) > SAMPLE_RATE * 0.6:
            verification = self.verifier.verify(audio)
            authorized, score, reason = verification.authorized, verification.score, verification.reason
            if not authorized:
                log.info("Command ignored: speaker not recognised (score %.2f)", score)
                self._emit("unauthorized")

        self._deliver(VoiceCommand(text.strip(), confidence, authorized, score, reason))

    @staticmethod
    def _strip_wake(text: str) -> str:
        import re

        return re.sub(r"(?i)^.*?\b(hey|hi|ok|okay)?\s*nova\b[,.\s]*", "", text).strip()

    def _record_command(self) -> np.ndarray | None:
        """Record until the user stops talking or the limit is reached."""
        self._emit("recording")
        frames: list[np.ndarray] = []
        silent_for = 0.0
        started = time.time()
        while time.time() - started < COMMAND_MAX_S and not self._stop.is_set():
            try:
                chunk = self._audio_q.get(timeout=0.6)
            except queue.Empty:
                break
            frames.append(chunk)
            if rms(chunk) < SILENCE_RMS:
                silent_for += len(chunk) / SAMPLE_RATE
                if silent_for >= SILENCE_END_S and len(frames) > 8:
                    break
            else:
                silent_for = 0.0
        self._emit("thinking")
        return np.concatenate(frames) if frames else None

    def _deliver(self, command: VoiceCommand) -> None:
        if self.on_command:
            try:
                self.on_command(command)
            except Exception:
                log.exception("Command handler failed")


class EnrollmentRecorder:
    """Records fixed-length samples for voice enrollment."""

    def __init__(self, settings: Any = None) -> None:
        self.settings = settings

    def record(self, seconds: float = 3.0) -> tuple[np.ndarray | None, str]:
        try:
            import sounddevice as sd
        except ImportError:
            return None, "Recording needs the sounddevice package (pip install sounddevice)."
        device = None
        if self.settings is not None:
            idx = int(self.settings.get("microphone_index", -1))
            device = None if idx < 0 else idx
        try:
            audio = sd.rec(int(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE,
                           channels=1, dtype="float32", device=device)
            sd.wait()
        except Exception as e:
            return None, f"Recording failed: {e}"
        flat = audio[:, 0]
        if rms(flat) < 0.01:
            return flat, "I barely heard anything - check your microphone level."
        return flat, "Recorded."
