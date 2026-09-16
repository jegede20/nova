"""Filesystem locations Nova uses. Works on Windows first, POSIX for dev/testing."""

from __future__ import annotations

import os
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"


def app_data_dir() -> Path:
    """Per-user writable directory for Nova's database, logs and voice profile."""
    override = os.environ.get("NOVA_HOME")
    if override:
        p = Path(override)
    elif IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        p = Path(base) / "Nova"
    else:
        p = Path.home() / ".local" / "share" / "nova"
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    return app_data_dir() / "nova.db"


def log_path() -> Path:
    d = app_data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / "nova.log"


def voice_profile_path() -> Path:
    d = app_data_dir() / "voice"
    d.mkdir(parents=True, exist_ok=True)
    return d / "profile.json"


def screenshots_dir() -> Path:
    d = app_data_dir() / "screenshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def downloads_dir() -> Path:
    return Path.home() / "Downloads"


def desktop_dir() -> Path:
    return Path.home() / "Desktop"


def documents_dir() -> Path:
    return Path.home() / "Documents"


KNOWN_FOLDERS: dict[str, Path] = {}


def known_folders() -> dict[str, Path]:
    """Friendly folder names -> real paths. Cached after first call."""
    global KNOWN_FOLDERS
    if KNOWN_FOLDERS:
        return KNOWN_FOLDERS
    home = Path.home()
    folders = {
        "home": home,
        "desktop": home / "Desktop",
        "downloads": home / "Downloads",
        "documents": home / "Documents",
        "pictures": home / "Pictures",
        "music": home / "Music",
        "videos": home / "Videos",
    }
    if IS_WINDOWS:
        folders["appdata"] = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        folders["temp"] = Path(os.environ.get("TEMP", home / "AppData" / "Local" / "Temp"))
    KNOWN_FOLDERS = folders
    return KNOWN_FOLDERS
