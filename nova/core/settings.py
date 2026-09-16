"""Nova settings: plain preferences in SQLite, secrets in Windows Credential Manager.

API keys are never written to the SQLite file. On Windows we use the Credential
Manager via pywin32/keyring; elsewhere (dev) we fall back to an env var or a
0600 file so the app still runs.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .database import Database, get_db
from .logging_setup import get_logger
from .paths import IS_WINDOWS, app_data_dir

log = get_logger("settings")

DEFAULTS: dict[str, Any] = {
    # voice
    "wake_word": "hey nova",
    "voice_activation": True,
    "microphone_index": -1,  # -1 = system default
    "voice_verification": True,
    "voice_threshold": 0.70,  # cosine similarity needed to accept speaker
    "stt_provider": "faster-whisper",
    "stt_model": "base.en",
    # ai
    "ai_provider": "openai",
    "ai_model": "gpt-4o-mini",
    "vision_model": "gpt-4o-mini",
    "ai_base_url": "",
    "ai_temperature": 0.2,
    # speech out
    "tts_enabled": True,
    "tts_rate": 185,
    "tts_voice": "",
    # behaviour
    "confirm_medium_risk": True,
    "confirm_high_risk": True,  # cannot be turned off in the UI
    "bulk_file_threshold": 5,  # more files than this => confirmation
    "notifications_enabled": True,
    "start_with_windows": False,
    "minimize_to_tray": True,
    # browser
    "browser_channel": "chrome",  # chrome | msedge | chromium
    "browser_headless": False,
    "browser_download_dir": "",
    # privacy
    "store_history": True,
    "history_retention_days": 30,
    "allow_screen_capture": True,
}

_SECRET_KEYS = {"openai_api_key", "anthropic_api_key", "google_api_key", "groq_api_key", "custom_api_key"}


class SecretStore:
    """Small abstraction so secrets live in the OS keychain when possible."""

    SERVICE = "Nova Assistant"

    def __init__(self) -> None:
        self._backend = self._pick_backend()

    def _pick_backend(self) -> str:
        if IS_WINDOWS:
            try:
                import keyring  # noqa: F401

                return "keyring"
            except Exception:
                try:
                    import win32cred  # noqa: F401

                    return "wincred"
                except Exception:
                    log.warning("No secure credential backend available; falling back to a local file.")
        else:
            try:
                import keyring  # noqa: F401

                return "keyring"
            except Exception:
                pass
        return "file"

    @property
    def backend(self) -> str:
        return self._backend

    def _file(self) -> Path:
        p = app_data_dir() / "secrets.json"
        if not p.exists():
            p.write_text("{}", encoding="utf-8")
            try:
                os.chmod(p, 0o600)
            except OSError:
                pass
        return p

    def get(self, key: str) -> str | None:
        env = os.environ.get(key.upper())
        if env:
            return env
        try:
            if self._backend == "keyring":
                import keyring

                return keyring.get_password(self.SERVICE, key)
            if self._backend == "wincred":
                import win32cred

                cred = win32cred.CredRead(f"{self.SERVICE}:{key}", win32cred.CRED_TYPE_GENERIC)
                return cred["CredentialBlob"].decode("utf-16-le")
        except Exception:
            return None
        import json

        try:
            return json.loads(self._file().read_text(encoding="utf-8")).get(key)
        except Exception:
            return None

    def set(self, key: str, value: str) -> bool:
        try:
            if self._backend == "keyring":
                import keyring

                keyring.set_password(self.SERVICE, key, value)
                return True
            if self._backend == "wincred":
                import win32cred

                win32cred.CredWrite(
                    {
                        "Type": win32cred.CRED_TYPE_GENERIC,
                        "TargetName": f"{self.SERVICE}:{key}",
                        "CredentialBlob": value,
                        "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
                    },
                    0,
                )
                return True
            import json

            f = self._file()
            data = json.loads(f.read_text(encoding="utf-8"))
            data[key] = value
            f.write_text(json.dumps(data), encoding="utf-8")
            try:
                os.chmod(f, 0o600)
            except OSError:
                pass
            return True
        except Exception as e:
            log.error("Could not store secret %s: %s", key, type(e).__name__)
            return False

    def delete(self, key: str) -> None:
        try:
            if self._backend == "keyring":
                import keyring

                keyring.delete_password(self.SERVICE, key)
            elif self._backend == "wincred":
                import win32cred

                win32cred.CredDelete(f"{self.SERVICE}:{key}", win32cred.CRED_TYPE_GENERIC)
            else:
                import json

                f = self._file()
                data = json.loads(f.read_text(encoding="utf-8"))
                data.pop(key, None)
                f.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            pass


class Settings:
    def __init__(self, db: Database | None = None) -> None:
        self.db = db or get_db()
        self.secrets = SecretStore()

    def get(self, key: str, default: Any = None) -> Any:
        if key in _SECRET_KEYS:
            return self.secrets.get(key) or default
        return self.db.get_setting(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any) -> None:
        if key in _SECRET_KEYS:
            self.secrets.set(key, str(value))
            return
        self.db.set_setting(key, value)

    def all(self) -> dict[str, Any]:
        merged = dict(DEFAULTS)
        merged.update(self.db.all_settings())
        return merged

    def reset(self, key: str) -> None:
        if key in DEFAULTS:
            self.db.set_setting(key, DEFAULTS[key])

    def api_key_for(self, provider: str) -> str | None:
        return self.secrets.get(f"{provider}_api_key")
