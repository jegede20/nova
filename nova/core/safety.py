"""Risk classification and confirmation gate.

Every tool call passes through `SafetyGate.evaluate()` before it runs. The gate
decides: run now, ask the user, or refuse outright. Nothing here talks to the
LLM -- the rules are static and readable on purpose.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class Risk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCKED = "blocked"


# Base risk per tool. Some tools escalate dynamically (see escalate()).
TOOL_RISK: dict[str, Risk] = {
    # low
    "open_app": Risk.LOW,
    "focus_app": Risk.LOW,
    "is_app_running": Risk.LOW,
    "open_folder": Risk.LOW,
    "open_file": Risk.LOW,
    "find_file": Risk.LOW,
    "find_folder": Risk.LOW,
    "read_file_metadata": Risk.LOW,
    "recent_files": Risk.LOW,
    "create_folder": Risk.LOW,
    "take_screenshot": Risk.LOW,
    "read_screen": Risk.LOW,
    "scroll": Risk.LOW,
    "wait": Risk.LOW,
    "get_task_status": Risk.LOW,
    "list_tasks": Risk.LOW,
    "create_task": Risk.LOW,
    "cancel_task": Risk.LOW,
    "pause_task": Risk.LOW,
    "resume_task": Risk.LOW,
    "watch_website": Risk.LOW,
    "watch_folder": Risk.LOW,
    "list_watchers": Risk.LOW,
    "stop_watcher": Risk.LOW,
    "send_notification": Risk.LOW,
    "speak": Risk.LOW,
    "browser_open": Risk.LOW,
    "browser_search": Risk.LOW,
    "browser_read": Risk.LOW,
    "browser_screenshot": Risk.LOW,
    "browser_scroll": Risk.LOW,
    "browser_wait": Risk.LOW,
    # medium
    "close_app": Risk.MEDIUM,
    "rename_file": Risk.MEDIUM,
    "move_file": Risk.MEDIUM,
    "copy_file": Risk.MEDIUM,
    "click": Risk.MEDIUM,
    "double_click": Risk.MEDIUM,
    "right_click": Risk.MEDIUM,
    "type_text": Risk.MEDIUM,
    "press_key": Risk.MEDIUM,
    "browser_click": Risk.MEDIUM,
    "browser_type": Risk.MEDIUM,
    "browser_download": Risk.MEDIUM,
    # high
    "delete_file": Risk.HIGH,
    "empty_recycle_bin": Risk.HIGH,
    "browser_upload": Risk.HIGH,
    "browser_submit": Risk.HIGH,
    "run_powershell": Risk.HIGH,
    "shutdown": Risk.HIGH,
}

# Paths Nova must never modify, whatever the LLM asks for.
PROTECTED_PATTERNS = [
    r"^[A-Za-z]:\\Windows",
    r"^[A-Za-z]:\\Program Files",
    r"^[A-Za-z]:\\ProgramData",
    r"^[A-Za-z]:\\\\?$",
    r"^/(etc|bin|sbin|usr|boot|sys|proc|dev)(/|$)",
]

# Words in a page/button that mean "this is a consequential click".
SENSITIVE_UI_WORDS = [
    "buy", "purchase", "checkout", "place order", "pay", "payment", "confirm order",
    "send", "transfer", "withdraw", "delete account", "close account", "deactivate",
    "change password", "reset password", "sign out all", "publish", "submit application",
]


@dataclass
class SafetyDecision:
    risk: Risk
    allowed: bool                     # may run without asking
    needs_confirmation: bool
    reason: str = ""
    summary: str = ""                 # human sentence shown in the confirm dialog
    details: list[str] = field(default_factory=list)


def is_protected_path(path: str | Path) -> bool:
    p = str(path)
    return any(re.match(pat, p, re.IGNORECASE) for pat in PROTECTED_PATTERNS)


def contains_sensitive_words(text: str) -> bool:
    t = (text or "").lower()
    return any(w in t for w in SENSITIVE_UI_WORDS)


class SafetyGate:
    def __init__(self, settings: Any = None) -> None:
        self.settings = settings

    def _opt(self, key: str, default: Any) -> Any:
        if self.settings is None:
            return default
        try:
            return self.settings.get(key, default)
        except Exception:
            return default

    def base_risk(self, tool: str) -> Risk:
        return TOOL_RISK.get(tool, Risk.MEDIUM)  # unknown tool => be cautious

    def evaluate(self, tool: str, args: dict[str, Any]) -> SafetyDecision:
        risk = self.base_risk(tool)
        details: list[str] = []
        summary = f"Run {tool}"
        reason = ""

        # --- hard blocks -------------------------------------------------
        for key in ("path", "source", "destination", "folder", "target", "paths", "file_path"):
            val = args.get(key)
            candidates = val if isinstance(val, list) else [val]
            for item in candidates:
                if isinstance(item, str) and item and is_protected_path(item):
                    return SafetyDecision(
                        Risk.BLOCKED, False, False,
                        reason=f"{item} is a protected system location.",
                        summary=f"Refused: {tool} on protected path {item}",
                    )

        # --- dynamic escalation -----------------------------------------
        paths = args.get("paths")
        count = len(paths) if isinstance(paths, list) else 1
        threshold = int(self._opt("bulk_file_threshold", 5))

        if tool in {"move_file", "copy_file", "rename_file"}:
            summary = self._describe_file_op(tool, args, count)
            if count > threshold:
                risk = Risk.HIGH
                details.append(f"{count} files affected")

        elif tool == "delete_file":
            risk = Risk.HIGH
            summary = self._describe_delete(args, count)
            details.append("Deleted files go to the Recycle Bin when possible, but this is hard to undo.")

        elif tool in {"click", "double_click", "browser_click", "browser_submit"}:
            label = str(args.get("label") or args.get("selector") or args.get("text") or "")
            summary = f"Click '{label}'" if label else "Click at the given position"
            if contains_sensitive_words(label):
                risk = Risk.HIGH
                details.append("This control looks like it performs a purchase, payment, send or delete action.")

        elif tool == "type_text":
            text = str(args.get("text", ""))
            summary = f"Type {len(text)} characters"
            if re.search(r"(?i)(password|secret|api[_ -]?key|seed phrase|private key)", text):
                return SafetyDecision(
                    Risk.BLOCKED, False, False,
                    reason="Nova will not type credentials or secrets on your behalf.",
                    summary="Refused: typing credentials",
                )

        elif tool == "close_app":
            summary = f"Close {args.get('name', 'the application')}"
            details.append("Unsaved work in that application could be lost.")

        elif tool == "run_powershell":
            risk = Risk.HIGH
            summary = "Run a PowerShell command"
            details.append(str(args.get("command", ""))[:200])

        elif tool == "browser_upload":
            summary = f"Upload {args.get('file_path', 'a file')} to the current page"

        elif tool == "open_app":
            summary = f"Open {args.get('name', 'application')}"

        elif tool == "open_folder":
            summary = f"Open folder {args.get('path', '')}"

        # --- confirmation policy ----------------------------------------
        if risk is Risk.LOW:
            return SafetyDecision(risk, True, False, reason=reason, summary=summary, details=details)

        if risk is Risk.MEDIUM:
            need = bool(self._opt("confirm_medium_risk", True))
            return SafetyDecision(risk, not need, need, reason=reason, summary=summary, details=details)

        # HIGH: always confirm, regardless of settings
        return SafetyDecision(risk, False, True, reason=reason, summary=summary, details=details)

    # ---------- readable summaries ----------
    @staticmethod
    def _describe_file_op(tool: str, args: dict[str, Any], count: int) -> str:
        verb = {"move_file": "Move", "copy_file": "Copy", "rename_file": "Rename"}[tool]
        src = args.get("source") or args.get("path") or (args.get("paths") or [""])[0]
        dst = args.get("destination") or args.get("new_name") or ""
        if count > 1:
            return f"{verb} {count} files to {dst}"
        return f"{verb} {Path(str(src)).name} -> {dst}" if dst else f"{verb} {Path(str(src)).name}"

    @staticmethod
    def _describe_delete(args: dict[str, Any], count: int) -> str:
        if count > 1:
            where = Path(str((args.get("paths") or [""])[0])).parent
            return f"Delete {count} files from {where}. This cannot easily be undone."
        target = args.get("path") or (args.get("paths") or [""])[0]
        return f"Delete {Path(str(target)).name}. This cannot easily be undone."


ConfirmCallback = Callable[[SafetyDecision, str, dict], bool]
