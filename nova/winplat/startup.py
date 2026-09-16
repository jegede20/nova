"""'Start Nova with Windows' via the per-user Run registry key.

Per-user HKCU means no admin rights are needed and nothing system-wide changes.
"""

from __future__ import annotations

import sys
from pathlib import Path

from ..core.logging_setup import get_logger
from ..core.paths import IS_WINDOWS

log = get_logger("startup")

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Nova Assistant"


def _command() -> str:
    """The command Windows should run at login."""
    if getattr(sys, "frozen", False):          # packaged exe
        return f'"{sys.executable}" --tray'
    # Prefer pythonw.exe so no console window appears.
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    runner = pythonw if pythonw.exists() else exe
    main = Path(__file__).resolve().parents[2] / "run_nova.py"
    return f'"{runner}" "{main}" --tray'


def is_startup_enabled() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(value)
    except FileNotFoundError:
        return False
    except OSError as e:
        log.debug("Could not read the startup key: %s", e)
        return False


def set_startup(enabled: bool) -> tuple[bool, str]:
    if not IS_WINDOWS:
        return False, "Starting with Windows is only available on Windows."
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _command())
                return True, "Nova will start with Windows."
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
            return True, "Nova will no longer start with Windows."
    except PermissionError:
        return False, "Windows blocked the change. Try running Nova once as administrator."
    except OSError as e:
        return False, f"Could not update the startup setting: {e}"
