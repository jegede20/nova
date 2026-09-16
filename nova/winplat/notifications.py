"""Windows toast notifications with graceful fallbacks.

Order of preference: win11toast -> plyer -> Qt tray balloon -> log only.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..core.logging_setup import get_logger
from ..core.paths import IS_WINDOWS

log = get_logger("notifications")

_tray_fallback: Callable[[str, str], None] | None = None


def set_tray_fallback(fn: Callable[[str, str], None]) -> None:
    """Let the Qt tray icon show balloons when no native backend exists."""
    global _tray_fallback
    _tray_fallback = fn


def _win11toast(title: str, body: str) -> bool:
    try:
        from win11toast import toast

        toast(title, body, app_id="Nova")
        return True
    except Exception:
        return False


def _plyer(title: str, body: str) -> bool:
    try:
        from plyer import notification

        notification.notify(title=title, message=body, app_name="Nova", timeout=8)
        return True
    except Exception:
        return False


class Notifier:
    def __init__(self, settings: Any = None, db: Any = None) -> None:
        self.settings = settings
        self.db = db

    def enabled(self) -> bool:
        if self.settings is None:
            return True
        try:
            return bool(self.settings.get("notifications_enabled", True))
        except Exception:
            return True

    def notify(self, title: str, body: str = "") -> bool:
        if self.db is not None:
            try:
                self.db.add_notification(title, body)
            except Exception:
                pass
        if not self.enabled():
            return False
        body = body[:300]
        if IS_WINDOWS and _win11toast(title, body):
            return True
        if _plyer(title, body):
            return True
        if _tray_fallback:
            try:
                _tray_fallback(title, body)
                return True
            except Exception:
                pass
        log.info("NOTIFY: %s - %s", title, body)
        return False
