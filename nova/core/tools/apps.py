"""Application control: launch, focus, close, detect.

Apps are resolved from a friendly-name table first, then from the Start Menu /
PATH. If Nova cannot resolve a name it says so rather than guessing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from ..logging_setup import get_logger
from ..paths import IS_WINDOWS
from .registry import ToolResult, registry

log = get_logger("tools.apps")

# Friendly name -> (windows launch target, process names to look for)
APP_TABLE: dict[str, tuple[str, list[str]]] = {
    "chrome": ("chrome.exe", ["chrome.exe"]),
    "google chrome": ("chrome.exe", ["chrome.exe"]),
    "edge": ("msedge.exe", ["msedge.exe"]),
    "microsoft edge": ("msedge.exe", ["msedge.exe"]),
    "firefox": ("firefox.exe", ["firefox.exe"]),
    "vs code": ("code.cmd", ["Code.exe"]),
    "vscode": ("code.cmd", ["Code.exe"]),
    "visual studio code": ("code.cmd", ["Code.exe"]),
    "notepad": ("notepad.exe", ["notepad.exe"]),
    "calculator": ("calc.exe", ["CalculatorApp.exe", "Calculator.exe"]),
    "calc": ("calc.exe", ["CalculatorApp.exe"]),
    "explorer": ("explorer.exe", ["explorer.exe"]),
    "file explorer": ("explorer.exe", ["explorer.exe"]),
    "terminal": ("wt.exe", ["WindowsTerminal.exe"]),
    "windows terminal": ("wt.exe", ["WindowsTerminal.exe"]),
    "powershell": ("powershell.exe", ["powershell.exe"]),
    "cmd": ("cmd.exe", ["cmd.exe"]),
    "task manager": ("taskmgr.exe", ["Taskmgr.exe"]),
    "settings": ("ms-settings:", []),
    "paint": ("mspaint.exe", ["mspaint.exe"]),
    "snipping tool": ("snippingtool.exe", ["SnippingTool.exe"]),
    "word": ("winword.exe", ["WINWORD.EXE"]),
    "excel": ("excel.exe", ["EXCEL.EXE"]),
    "powerpoint": ("powerpnt.exe", ["POWERPNT.EXE"]),
    "outlook": ("outlook.exe", ["OUTLOOK.EXE"]),
    "spotify": ("spotify.exe", ["Spotify.exe"]),
    "discord": ("discord.exe", ["Discord.exe"]),
    "slack": ("slack.exe", ["slack.exe"]),
    "steam": ("steam.exe", ["steam.exe"]),
}

# Non-Windows equivalents so the tool layer is testable during development.
POSIX_TABLE = {
    "chrome": "google-chrome",
    "firefox": "firefox",
    "vs code": "code",
    "vscode": "code",
    "terminal": "x-terminal-emulator",
    "calculator": "gnome-calculator",
    "explorer": "xdg-open",
    "file explorer": "xdg-open",
}


def _start_menu_matches(name: str) -> list[Path]:
    """Search Start Menu .lnk shortcuts for a fuzzy name match."""
    if not IS_WINDOWS:
        return []
    roots = [
        Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    ]
    needle = name.lower().strip()
    hits: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        try:
            for lnk in root.rglob("*.lnk"):
                if needle in lnk.stem.lower():
                    hits.append(lnk)
                    if len(hits) >= 12:
                        return hits
        except OSError:
            continue
    return hits


def resolve_app(name: str) -> tuple[str | None, list[Path], list[str]]:
    """Return (launch_target, ambiguous_matches, process_names)."""
    key = name.lower().strip()
    if key in APP_TABLE:
        target, procs = APP_TABLE[key]
        if not IS_WINDOWS:
            return POSIX_TABLE.get(key, key), [], procs
        return target, [], procs
    if not IS_WINDOWS:
        found = shutil.which(key)
        return (found or None), [], [key]
    if shutil.which(key) or shutil.which(f"{key}.exe"):
        return (shutil.which(key) or shutil.which(f"{key}.exe")), [], [f"{key}.exe"]
    matches = _start_menu_matches(key)
    if len(matches) == 1:
        return str(matches[0]), [], [matches[0].stem + ".exe"]
    if len(matches) > 1:
        # prefer an exact stem match if one exists
        exact = [m for m in matches if m.stem.lower() == key]
        if len(exact) == 1:
            return str(exact[0]), [], [exact[0].stem + ".exe"]
        return None, matches, []
    return None, [], []


def _running_processes() -> list[str]:
    try:
        import psutil
    except ImportError:
        return []
    names = []
    for proc in psutil.process_iter(["name"]):
        try:
            n = proc.info.get("name")
            if n:
                names.append(n)
        except Exception:
            continue
    return names


@registry.tool(
    "open_app",
    "Open or launch a Windows application by its common name, e.g. 'Chrome', 'VS Code', 'Calculator'.",
    {"name": {"type": "string", "description": "Application name", "required": True},
     "arguments": {"type": "string", "description": "Optional argument, e.g. a file or folder to open with it"}},
    category="apps",
)
def open_app(name: str, arguments: str = "") -> ToolResult:
    target, ambiguous, _ = resolve_app(name)
    if ambiguous:
        options = [m.stem for m in ambiguous[:6]]
        return ToolResult(
            False,
            f"I found {len(ambiguous)} applications matching '{name}'. Which one do you mean?",
            {"options": options, "needs_choice": True},
        )
    if not target:
        return ToolResult.fail(
            f"I couldn't find an application called '{name}' on this PC.", app=name, resolved=False
        )
    try:
        if IS_WINDOWS:
            if target.startswith("ms-settings:"):
                os.startfile(target)  # type: ignore[attr-defined]
            elif target.lower().endswith(".lnk"):
                os.startfile(target)  # type: ignore[attr-defined]
            else:
                cmd = [target] + ([arguments] if arguments else [])
                subprocess.Popen(cmd, shell=False, close_fds=True)
        else:
            if not shutil.which(target):
                return ToolResult.fail(f"'{name}' is not installed on this machine.")
            subprocess.Popen([target] + ([arguments] if arguments else []),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        return ToolResult.fail(f"I couldn't start '{name}' - the program file was not found.")
    except OSError as e:
        return ToolResult.fail(f"I couldn't start '{name}': {e}")
    return ToolResult.success(f"Opening {name}.", app=name, target=str(target))


@registry.tool(
    "close_app",
    "Close a running application by name. Unsaved work may be lost, so this needs confirmation.",
    {"name": {"type": "string", "description": "Application name", "required": True},
     "force": {"type": "boolean", "description": "Force kill if it does not close politely", "default": False}},
    category="apps",
)
def close_app(name: str, force: bool = False) -> ToolResult:
    try:
        import psutil
    except ImportError:
        return ToolResult.fail("I can't manage processes because psutil isn't installed.")
    _, _, procnames = resolve_app(name)
    wanted = {p.lower() for p in procnames} or {f"{name.lower()}.exe", name.lower()}
    killed = 0
    for proc in psutil.process_iter(["name"]):
        try:
            pname = (proc.info.get("name") or "").lower()
            if pname in wanted:
                proc.kill() if force else proc.terminate()
                killed += 1
        except Exception:
            continue
    if killed == 0:
        return ToolResult.fail(f"{name} doesn't appear to be running.", app=name, closed=0)
    return ToolResult.success(f"Closed {name}.", app=name, closed=killed)


@registry.tool(
    "is_app_running",
    "Check whether an application is currently running.",
    {"name": {"type": "string", "description": "Application name", "required": True}},
    category="apps",
)
def is_app_running(name: str) -> ToolResult:
    _, _, procnames = resolve_app(name)
    wanted = {p.lower() for p in procnames} or {f"{name.lower()}.exe", name.lower()}
    running = [p for p in _running_processes() if p.lower() in wanted]
    if running:
        return ToolResult.success(f"Yes, {name} is running.", app=name, running=True, count=len(running))
    return ToolResult.success(f"No, {name} is not running.", app=name, running=False, count=0)


@registry.tool(
    "focus_app",
    "Bring an already-running application's window to the foreground.",
    {"name": {"type": "string", "description": "Application or window title", "required": True}},
    category="apps",
)
def focus_app(name: str) -> ToolResult:
    if not IS_WINDOWS:
        return ToolResult.fail("Focusing windows is only supported on Windows.")
    try:
        import win32con
        import win32gui
    except ImportError:
        return ToolResult.fail("Window control needs pywin32 installed.")

    needle = name.lower()
    matches: list[tuple[int, str]] = []

    def cb(hwnd: int, _: object) -> None:
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title and needle in title.lower():
                matches.append((hwnd, title))

    win32gui.EnumWindows(cb, None)
    if not matches:
        return ToolResult.fail(f"I couldn't find an open window for '{name}'.")
    hwnd, title = matches[0]
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    except Exception as e:
        return ToolResult.fail(f"I found the window but couldn't focus it: {e}")
    return ToolResult.success(f"Switched to {title}.", window=title)


@registry.tool(
    "list_windows",
    "List the titles of currently open application windows.",
    {},
    category="apps",
)
def list_windows() -> ToolResult:
    if not IS_WINDOWS:
        return ToolResult.success("No window list available on this platform.", windows=[])
    try:
        import win32gui
    except ImportError:
        return ToolResult.fail("Window listing needs pywin32 installed.")
    titles: list[str] = []

    def cb(hwnd: int, _: object) -> None:
        if win32gui.IsWindowVisible(hwnd):
            t = win32gui.GetWindowText(hwnd)
            if t.strip():
                titles.append(t)

    win32gui.EnumWindows(cb, None)
    return ToolResult.success(f"{len(titles)} windows are open.", windows=titles[:40])
