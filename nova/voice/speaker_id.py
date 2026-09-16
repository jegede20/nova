"""Speaker verification (voice identity).

Enrollment records a few short samples, turns each into an embedding and stores
the averaged profile locally. Verification compares a new sample by cosine
similarity against that profile.

Two embedding backends:
  * resemblyzer (accurate, optional install)
  * a built-in MFCC-style spectral fingerprint using numpy only (always works)

This is a convenience filter, NOT security. Every risky action still requires
explicit confirmation, exactly as the safety layer enforces.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..core.logging_setup import get_logger
from ..core.paths import voice_profile_path

log = get_logger("speaker")

SAMPLE_RATE = 16000
REQUIRED_SAMPLES = 4
MIN_SAMPLE_SECONDS = 1.2


@dataclass
class VerificationResult:
    authorized: bool
    score: float
    reason: str = ""


# ---------------------------------------------------------------- embeddings
def _resemblyzer_embed(audio: np.ndarray) -> np.ndarray | None:
    try:
        from resemblyzer import VoiceEncoder, preprocess_wav

        encoder = _resemblyzer_embed._encoder  # type: ignore[attr-defined]
    except (ImportError, AttributeError):
        try:
            from resemblyzer import VoiceEncoder, preprocess_wav

            encoder = VoiceEncoder(verbose=False)
            _resemblyzer_embed._encoder = encoder  # type: ignore[attr-defined]
        except Exception:
            return None
    try:
        wav = preprocess_wav(audio, source_sr=SAMPLE_RATE)
        return np.asarray(encoder.embed_utterance(wav), dtype=np.float32)
    except Exception as e:
        log.debug("resemblyzer embedding failed: %s", e)
        return None


def _spectral_embed(audio: np.ndarray) -> np.ndarray:
    """Lightweight fallback: log-mel-ish band energies + deltas, numpy only."""
    audio = np.asarray(audio, dtype=np.float32)
    if audio.size < SAMPLE_RATE // 4:
        return np.zeros(64, dtype=np.float32)

    # pre-emphasis then framed FFT
    emphasized = np.append(audio[0], audio[1:] - 0.97 * audio[:-1])
    frame_len, hop = 400, 160  # 25 ms / 10 ms
    n_frames = max(1, 1 + (len(emphasized) - frame_len) // hop)
    window = np.hamming(frame_len)
    bands = 32
    edges = np.logspace(np.log10(80), np.log10(7600), bands + 1)
    freqs = np.fft.rfftfreq(512, 1 / SAMPLE_RATE)
    feats = np.zeros((n_frames, bands), dtype=np.float32)

    for i in range(n_frames):
        start = i * hop
        frame = emphasized[start:start + frame_len]
        if len(frame) < frame_len:
            frame = np.pad(frame, (0, frame_len - len(frame)))
        spec = np.abs(np.fft.rfft(frame * window, n=512)) ** 2
        for b in range(bands):
            mask = (freqs >= edges[b]) & (freqs < edges[b + 1])
            feats[i, b] = spec[mask].mean() if mask.any() else 0.0

    feats = np.log1p(feats)
    # discard near-silent frames so background noise doesn't dominate
    energy = feats.sum(axis=1)
    keep = energy > np.percentile(energy, 35)
    if keep.sum() >= 3:
        feats = feats[keep]

    mean = feats.mean(axis=0)
    std = feats.std(axis=0)
    emb = np.concatenate([mean, std]).astype(np.float32)
    norm = np.linalg.norm(emb)
    return emb / norm if norm > 0 else emb


def embed(audio: np.ndarray) -> tuple[np.ndarray, str]:
    vec = _resemblyzer_embed(audio)
    if vec is not None and vec.size:
        norm = np.linalg.norm(vec)
        return (vec / norm if norm else vec), "resemblyzer"
    return _spectral_embed(audio), "spectral"


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    if a.size != b.size or a.size == 0:
        return 0.0
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


# ---------------------------------------------------------------- profile
class SpeakerProfile:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or voice_profile_path()
        self.vectors: list[np.ndarray] = []
        self.centroid: np.ndarray | None = None
        self.backend = ""
        self.created_at: float = 0.0
        self.load()

    @property
    def enrolled(self) -> bool:
        return self.centroid is not None and self.centroid.size > 0

    def load(self) -> bool:
        if not self.path.exists():
            return False
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.vectors = [np.array(v, dtype=np.float32) for v in data.get("vectors", [])]
            centroid = data.get("centroid")
            self.centroid = np.array(centroid, dtype=np.float32) if centroid else None
            self.backend = data.get("backend", "")
            self.created_at = data.get("created_at", 0.0)
            return self.enrolled
        except (json.JSONDecodeError, OSError, ValueError) as e:
            log.warning("Could not read the voice profile: %s", e)
            return False

    def save(self) -> None:
        payload = {
            "vectors": [v.tolist() for v in self.vectors],
            "centroid": self.centroid.tolist() if self.centroid is not None else None,
            "backend": self.backend,
            "created_at": self.created_at or time.time(),
            "note": "Voice embeddings only. No audio recordings are stored.",
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        try:
            import os

            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def add_sample(self, audio: np.ndarray) -> tuple[bool, str]:
        if len(audio) < SAMPLE_RATE * MIN_SAMPLE_SECONDS:
            return False, "That sample was too short. Please speak for at least two seconds."
        if float(np.abs(audio).max()) < 0.01:
            return False, "I couldn't hear anything. Check your microphone and try again."
        vec, backend = embed(audio)
        if not vec.size:
            return False, "I couldn't analyse that recording. Please try again."
        if self.backend and backend != self.backend:
            self.vectors.clear()  # never mix backends
        self.backend = backend
        self.vectors.append(vec)
        return True, f"Sample {len(self.vectors)} of {REQUIRED_SAMPLES} recorded."

    def finalize(self) -> tuple[bool, str]:
        if len(self.vectors) < REQUIRED_SAMPLES:
            return False, f"I need {REQUIRED_SAMPLES} samples, I have {len(self.vectors)}."
        stacked = np.vstack(self.vectors)
        centroid = stacked.mean(axis=0)
        norm = np.linalg.norm(centroid)
        self.centroid = centroid / norm if norm else centroid
        self.created_at = time.time()
        self.save()
        consistency = float(np.mean([cosine(v, self.centroid) for v in self.vectors]))
        return True, f"Voice profile saved (internal consistency {consistency:.2f})."

    def reset(self) -> None:
        self.vectors.clear()
        self.centroid = None
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass

    def verify(self, audio: np.ndarray, threshold: float = 0.70) -> VerificationResult:
        if not self.enrolled:
            return VerificationResult(True, 1.0, "No voice profile enrolled - verification is off.")
        if len(audio) < SAMPLE_RATE * 0.6:
            return VerificationResult(False, 0.0, "The command was too short to verify.")
        vec, backend = embed(audio)
        if backend != self.backend:
            return VerificationResult(True, 1.0, "Voice backend changed; please re-enroll.")
        score = cosine(vec, self.centroid)  # type: ignore[arg-type]
        if score >= threshold:
            return VerificationResult(True, round(score, 3), "Voice matched.")
        return VerificationResult(False, round(score, 3), "That didn't sound like the enrolled user.")


class SpeakerVerifier:
    """Thin wrapper the rest of Nova uses."""

    def __init__(self, settings: Any = None) -> None:
        self.settings = settings
        self.profile = SpeakerProfile()

    @property
    def enrolled(self) -> bool:
        return self.profile.enrolled

    def threshold(self) -> float:
        if self.settings is None:
            return 0.70
        try:
            return float(self.settings.get("voice_threshold", 0.70))
        except Exception:
            return 0.70

    def enabled(self) -> bool:
        if self.settings is None:
            return True
        try:
            return bool(self.settings.get("voice_verification", True))
        except Exception:
            return True

    def verify(self, audio: np.ndarray) -> VerificationResult:
        if not self.enabled():
            return VerificationResult(True, 1.0, "Voice verification is turned off.")
        return self.profile.verify(audio, self.threshold())
