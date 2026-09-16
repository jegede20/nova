"""Speech to text.

Default engine is faster-whisper running fully on the local machine: microphone
audio never leaves the PC. A cloud engine is available as an explicit opt-in.
Returns both text and a confidence value so Nova can ask the user to repeat
instead of acting on a bad transcription.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..core.logging_setup import get_logger

log = get_logger("stt")

SAMPLE_RATE = 16000
LOW_CONFIDENCE = 0.55


@dataclass
class Transcript:
    text: str
    confidence: float = 1.0
    engine: str = ""

    @property
    def uncertain(self) -> bool:
        return not self.text.strip() or self.confidence < LOW_CONFIDENCE


class SpeechToText:
    """Lazy-loads a local Whisper model on first use."""

    def __init__(self, settings: Any = None) -> None:
        self.settings = settings
        self._model = None
        self._model_name = ""
        self.last_error = ""

    def _opt(self, key: str, default: Any) -> Any:
        if self.settings is None:
            return default
        try:
            return self.settings.get(key, default)
        except Exception:
            return default

    @property
    def available(self) -> bool:
        try:
            import faster_whisper  # noqa: F401

            return True
        except ImportError:
            return False

    def load(self) -> bool:
        """Load the model. Safe to call repeatedly."""
        wanted = str(self._opt("stt_model", "base.en"))
        if self._model is not None and self._model_name == wanted:
            return True
        try:
            from faster_whisper import WhisperModel

            log.info("Loading Whisper model '%s' (first run downloads it)", wanted)
            self._model = WhisperModel(wanted, device="auto", compute_type="int8")
            self._model_name = wanted
            return True
        except ImportError:
            self.last_error = ("Local speech recognition needs faster-whisper. "
                               "Install it with: pip install faster-whisper")
            log.warning(self.last_error)
            return False
        except Exception as e:
            self.last_error = f"Could not load the speech model: {e}"
            log.error(self.last_error)
            return False

    def transcribe(self, audio: np.ndarray) -> Transcript:
        """audio: float32 mono at 16 kHz, range -1..1."""
        if audio is None or len(audio) == 0:
            return Transcript("", 0.0, "none")
        if not self.load() or self._model is None:
            return Transcript("", 0.0, "unavailable")
        try:
            segments, _info = self._model.transcribe(
                audio, language="en", beam_size=1, vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 400},
            )
            parts, logprobs = [], []
            for seg in segments:
                parts.append(seg.text)
                if seg.avg_logprob is not None:
                    logprobs.append(seg.avg_logprob)
            text = " ".join(p.strip() for p in parts).strip()
            confidence = _logprob_to_confidence(logprobs)
            return Transcript(text, confidence, f"faster-whisper:{self._model_name}")
        except Exception as e:
            log.error("Transcription failed: %s", e)
            self.last_error = str(e)
            return Transcript("", 0.0, "error")


def _logprob_to_confidence(logprobs: list[float]) -> float:
    if not logprobs:
        return 0.0
    avg = sum(logprobs) / len(logprobs)
    return round(min(1.0, math.exp(avg)), 3)
