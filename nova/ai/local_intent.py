"""Offline command interpreter.

When no AI provider is configured or the network is down, Nova still handles the
common cases with plain pattern matching: open apps, open folders, create
folders, find files, task control. Anything else returns None so the caller can
tell the user honestly that it needs the AI service.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..core.paths import known_folders
from ..core.tools.apps import APP_TABLE


def _original_case(raw: str, lowered: str) -> str:
    """Recover the user's capitalisation for a phrase matched in lowercase."""
    idx = raw.lower().find(lowered)
    return raw[idx:idx + len(lowered)] if idx >= 0 else lowered


@dataclass
class LocalIntent:
    tool: str
    args: dict[str, Any]
    say: str


FOLDER_WORDS = set(known_folders()) | {"download", "picture", "video", "document"}

_STOP_WORDS = {"please", "for me", "now", "nova", "hey nova", "can you", "could you"}


def _clean(text: str) -> str:
    t = text.lower().strip().strip(".?!")
    t = re.sub(r"^(hey |ok |okay )?nova[, ]*", "", t)
    for w in _STOP_WORDS:
        t = t.replace(w, " ")
    return re.sub(r"\s+", " ", t).strip()


def interpret(text: str) -> LocalIntent | None:
    raw = (text or "").strip()
    t = _clean(text)
    if not t:
        return None

    # --- stop / cancel ---
    if t in {"stop", "stop everything", "cancel", "cancel that", "cancel everything", "abort"}:
        return LocalIntent("cancel_all", {}, "Stopping.")

    # --- open folder ---
    m = re.match(r"^(?:open|show|go to)\s+(?:my\s+|the\s+)?(\w+)\s*(?:folder)?$", t)
    if m:
        word = m.group(1)
        if word in FOLDER_WORDS or word + "s" in FOLDER_WORDS:
            name = word if word in known_folders() else word + "s"
            return LocalIntent("open_folder", {"path": name}, f"Opening {word}.")

    m = re.match(r"^open\s+(?:the\s+)?folder\s+(.+)$", t)
    if m:
        return LocalIntent("open_folder", {"path": m.group(1)}, f"Opening {m.group(1)}.")

    # --- open app ---
    m = re.match(r"^(?:open|launch|start|run)\s+(.+?)(?:\s+app(?:lication)?)?$", t)
    if m:
        target = m.group(1).strip()
        if target in APP_TABLE:
            return LocalIntent("open_app", {"name": target}, f"Opening {target}.")
        if target in known_folders():
            return LocalIntent("open_folder", {"path": target}, f"Opening {target}.")
        # a single word that isn't a known folder is probably an app
        if " " not in target:
            return LocalIntent("open_app", {"name": target}, f"Opening {target}.")

    # --- close app ---
    m = re.match(r"^(?:close|quit|exit|kill)\s+(.+)$", t)
    if m:
        return LocalIntent("close_app", {"name": m.group(1).strip()}, f"Closing {m.group(1)}.")

    # --- create folder ---
    m = re.match(r"^(?:create|make|new)\s+(?:a\s+)?folder\s+(?:called|named)?\s*[\"']?(.+?)[\"']?"
                 r"(?:\s+(?:on|in)\s+(?:my\s+|the\s+)?(\w+))?$", t)
    if m:
        name, where = m.group(1).strip(), (m.group(2) or "desktop")
        name = _original_case(raw, name)   # "Hackathon Projects", not "hackathon projects"
        return LocalIntent("create_folder", {"name": name, "parent": where},
                           f"Creating {name}.")

    # --- find files ---
    m = re.match(r"^(?:find|search for|look for|locate)\s+(?:my\s+|the\s+)?(?:latest\s+|last\s+|recent\s+)?"
                 r"(\w+)?\s*(?:files?|documents?)?(?:\s+in\s+(?:my\s+)?(\w+))?$", t)
    if m and (m.group(1) or m.group(2)):
        word = (m.group(1) or "").strip()
        folder = (m.group(2) or "downloads").strip()
        ext = word if word in {"pdf", "png", "jpg", "docx", "xlsx", "txt", "zip", "mp4", "csv"} else ""
        query = "" if ext else word
        return LocalIntent("find_file", {"query": query, "extension": ext, "folder": folder, "limit": 10},
                           "Searching.")

    # --- screenshot ---
    if t in {"take a screenshot", "screenshot", "capture my screen", "take screenshot"}:
        return LocalIntent("take_screenshot", {}, "Taking a screenshot.")

    # --- task queries ---
    if re.match(r"^(what|which)\s+tasks?\s+(are\s+)?(running|active)", t) or t in {"list tasks", "show tasks"}:
        return LocalIntent("list_tasks", {}, "Checking your tasks.")

    if t in {"what watchers are running", "list watchers", "show watchers"}:
        return LocalIntent("list_watchers", {}, "Checking your watchers.")

    return None


def offline_reply(text: str) -> str:
    """Message shown when nothing local matched and the AI is unreachable."""
    return (
        "I can't reach the AI service right now, so I can only handle simple commands "
        "like opening apps and folders, creating folders or finding files."
    )
