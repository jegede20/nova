#!/usr/bin/env python3
"""Nova system check.

Tells you in plain language what works, what's missing, and the exact command
to fix each problem. Safe to run any time - it changes nothing.
"""

from __future__ import annotations

import importlib.util
import platform
import sys

OK = "[ OK ]"
NO = "[MISS]"
WARN = "[WARN]"


def have(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def line(status: str, name: str, detail: str = "") -> None:
    print(f"  {status}  {name:<26} {detail}")


def main() -> int:
    print()
    print("  ============================================")
    print("    NOVA - System Check")
    print("  ============================================")
    print()

    problems: list[str] = []
    warnings: list[str] = []

    # ---------- platform ----------
    print("  SYSTEM")
    is_windows = sys.platform == "win32"
    line(OK if is_windows else WARN, "Operating system",
         f"{platform.system()} {platform.release()}")
    if not is_windows:
        warnings.append("Nova's app control, screen reading and startup features need Windows.")

    version = sys.version_info
    ok_version = version >= (3, 10)
    line(OK if ok_version else NO, "Python",
         f"{version.major}.{version.minor}.{version.micro}")
    if not ok_version:
        problems.append("Install Python 3.10 or newer from python.org")

    in_venv = sys.prefix != sys.base_prefix
    line(OK if in_venv else WARN, "Virtual environment",
         "active" if in_venv else "not active - run start_nova.bat instead of python directly")
    print()

    # ---------- required ----------
    print("  REQUIRED  (Nova will not start without these)")
    required = [
        ("PySide6", "PySide6", "pip install PySide6"),
        ("httpx", "httpx", "pip install httpx"),
        ("numpy", "numpy", "pip install numpy"),
    ]
    for label, module, fix in required:
        present = have(module)
        line(OK if present else NO, label, "" if present else fix)
        if not present:
            problems.append(fix)
    print()

    # ---------- voice ----------
    print("  VOICE")
    voice = [
        ("Speech recognition", "faster_whisper", "pip install faster-whisper",
         "Wake word and voice commands will not work."),
        ("Microphone input", "sounddevice", "pip install sounddevice",
         "Nova cannot hear you."),
        ("Spoken replies", "pyttsx3", "pip install pyttsx3",
         "Nova will reply in text only."),
    ]
    for label, module, fix, consequence in voice:
        present = have(module)
        line(OK if present else NO, label, "" if present else f"{fix}   ({consequence})")
        if not present:
            warnings.append(f"{label}: {fix}")

    # actual microphone hardware
    if have("sounddevice"):
        try:
            import sounddevice as sd

            mics = [d for d in sd.query_devices() if d["max_input_channels"] > 0]
            if mics:
                line(OK, "Microphone detected", mics[0]["name"][:40])
            else:
                line(NO, "Microphone detected", "No input device found - plug one in")
                warnings.append("No microphone detected.")
        except Exception as e:
            line(WARN, "Microphone detected", f"could not check ({type(e).__name__})")
    print()

    # ---------- control ----------
    print("  PC CONTROL")
    control = [
        ("Screen and input", "pyautogui", "pip install pyautogui pillow"),
        ("Find buttons by name", "uiautomation", "pip install uiautomation"),
        ("Detect running apps", "psutil", "pip install psutil"),
        ("Focus windows", "win32gui", "pip install pywin32"),
        ("Recycle Bin deletes", "send2trash", "pip install send2trash"),
        ("Windows notifications", "win11toast", "pip install win11toast"),
        ("Secure key storage", "keyring", "pip install keyring"),
    ]
    for label, module, fix in control:
        present = have(module)
        if not present and module in {"win32gui", "uiautomation", "win11toast"} and not is_windows:
            line(WARN, label, "Windows only - skipped")
            continue
        line(OK if present else NO, label, "" if present else fix)
        if not present:
            warnings.append(f"{label}: {fix}")
    print()

    # ---------- browser ----------
    print("  WEB AUTOMATION")
    if have("playwright"):
        line(OK, "Playwright", "")
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                path = p.chromium.executable_path
                import os

                if os.path.exists(path):
                    line(OK, "Browser engine", "chromium ready")
                else:
                    line(NO, "Browser engine", "run: playwright install chromium")
                    warnings.append("Browser engine missing: playwright install chromium")
        except Exception:
            line(NO, "Browser engine", "run: playwright install chromium")
            warnings.append("Browser engine missing: playwright install chromium")
    else:
        line(NO, "Playwright", "pip install playwright && playwright install chromium")
        warnings.append("Web automation unavailable: pip install playwright")
    print()

    # ---------- Nova's own state ----------
    print("  NOVA")
    try:
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
        from nova.core.database import get_db
        from nova.core.paths import app_data_dir
        from nova.core.settings import Settings
        from nova.voice.speaker_id import SpeakerProfile

        settings = Settings(get_db())
        provider = str(settings.get("ai_provider", "openai"))
        key = settings.api_key_for(provider)
        needs_key = provider != "ollama"

        line(OK, "Data folder", str(app_data_dir()))
        line(OK, "AI provider", f"{provider} / {settings.get('ai_model')}")
        if key or not needs_key:
            line(OK, "API key", "configured" if key else "not needed for ollama")
        else:
            line(NO, "API key", "add it in Settings -> AI provider")
            warnings.append("No API key yet: open Settings and paste one.")

        line(OK, "Key storage", settings.secrets.backend)

        enrolled = SpeakerProfile().enrolled
        line(OK if enrolled else NO, "Voice profile",
             "enrolled" if enrolled else "not enrolled - open Voice enrollment")
        if not enrolled:
            warnings.append("Voice not enrolled: sidebar -> Voice enrollment.")
    except Exception as e:
        line(WARN, "Nova internals", f"{type(e).__name__}: {e}")
    print()

    # ---------- verdict ----------
    print("  ============================================")
    if problems:
        print("    CANNOT START - fix these first:")
        for p in dict.fromkeys(problems):
            print(f"      - {p}")
    elif warnings:
        print("    READY TO RUN, with some features unavailable:")
        for w in list(dict.fromkeys(warnings))[:8]:
            print(f"      - {w}")
    else:
        print("    Everything is installed. Nova is fully ready.")
    print("  ============================================")
    print()
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
