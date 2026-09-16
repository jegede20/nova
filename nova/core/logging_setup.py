"""Logging with a secret-redacting filter, so tokens never reach disk."""

from __future__ import annotations

import logging
import logging.handlers
import re

from .paths import log_path

# Patterns for things that must never be written to the log file.
_SECRET_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9_\-]{12,})"),
    re.compile(r"(gsk_[A-Za-z0-9_\-]{12,})"),
    re.compile(r"(AIza[A-Za-z0-9_\-]{20,})"),
    re.compile(r"(?i)\b(api[_\- ]?key|token|password|passwd|secret|private[_\- ]?key)\b\s*[:=]\s*\S+"),
    re.compile(r"(?i)authorization\s*:\s*bearer\s+\S+"),
]


def redact(text: str) -> str:
    out = text
    for pat in _SECRET_PATTERNS:
        out = pat.sub(lambda m: m.group(0).split(m.group(1))[0] + "[REDACTED]" if m.groups() else "[REDACTED]", out)
    return out


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = redact(record.msg)
            if record.args:
                record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)  # type: ignore[assignment]
        except Exception:
            pass
        return True


_configured = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    global _configured
    logger = logging.getLogger("nova")
    if _configured:
        return logger
    logger.setLevel(level)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")

    fh = logging.handlers.RotatingFileHandler(log_path(), maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.addFilter(RedactFilter())
    logger.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    sh.addFilter(RedactFilter())
    logger.addHandler(sh)

    logger.propagate = False
    _configured = True
    return logger


def get_logger(name: str = "nova") -> logging.Logger:
    setup_logging()
    return logging.getLogger(name if name.startswith("nova") else f"nova.{name}")
