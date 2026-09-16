"""Website and folder watchers.

A single background loop wakes up once a minute and only checks watchers whose
interval has elapsed, so CPU and network use stay tiny. Website checks hash the
visible text (not the raw HTML) so ads and timestamps don't cause false alarms.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from .database import Database
from .logging_setup import get_logger

log = get_logger("watchers")

MIN_INTERVAL = 60          # never poll a site faster than once a minute
DEFAULT_INTERVAL = 600     # 10 minutes
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Nova-Assistant/1.0"

_TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_HTML_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def page_fingerprint(html: str) -> tuple[str, str]:
    """Return (hash, plain text) of a page's visible content."""
    text = _TAG_RE.sub(" ", html)
    text = _HTML_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest(), text


def folder_fingerprint(path: Path, pattern: str = "*") -> tuple[str, list[str]]:
    try:
        names = sorted(p.name for p in path.glob(pattern) if p.is_file())
    except OSError:
        return "", []
    return hashlib.sha256("|".join(names).encode()).hexdigest(), names


class WatcherService:
    def __init__(self, db: Database, notifier: Callable[[str, str], Any] | None = None) -> None:
        self.db = db
        self.notifier = notifier
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._last_text: dict[int, str] = {}
        self.on_change: Callable[[dict, str], None] | None = None

    # ---------- CRUD ----------
    def add_website(self, url: str, interval_s: int = DEFAULT_INTERVAL, condition: str = "changed",
                    name: str = "") -> int:
        url = url if url.startswith(("http://", "https://")) else f"https://{url}"
        interval = max(MIN_INTERVAL, int(interval_s))
        return self.db.create_watcher(name or _short_url(url), url, "website", interval, condition)

    def add_folder(self, path: str, interval_s: int = 120, condition: str = "new_file", name: str = "") -> int:
        interval = max(30, int(interval_s))
        return self.db.create_watcher(name or Path(path).name, str(path), "folder", interval, condition)

    def stop_watcher(self, watcher_id: int) -> bool:
        if not self.db.get_watcher(watcher_id):
            return False
        self.db.update_watcher(watcher_id, active=0)
        return True

    def resume_watcher(self, watcher_id: int) -> bool:
        if not self.db.get_watcher(watcher_id):
            return False
        self.db.update_watcher(watcher_id, active=1)
        return True

    def list(self, active_only: bool = False) -> list[dict]:
        return self.db.list_watchers(active_only)

    # ---------- loop ----------
    async def run(self) -> None:
        """Main loop. Run this on the task manager's background loop."""
        self._stop.clear()
        log.info("Watcher service started")
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception:
                log.exception("Watcher tick failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=30)
            except asyncio.TimeoutError:
                pass
        log.info("Watcher service stopped")

    def stop(self) -> None:
        self._stop.set()

    async def _tick(self) -> None:
        now = time.time()
        for w in self.db.list_watchers(active_only=True):
            last = w.get("last_checked") or 0
            if now - last < w["interval_s"]:
                continue
            await self.check(w)

    async def check(self, w: dict) -> dict[str, Any]:
        """Check one watcher and notify if its condition is met."""
        wid = w["id"]
        self.db.update_watcher(wid, last_checked=time.time())
        try:
            if w["wtype"] == "website":
                return await self._check_website(w)
            return self._check_folder(w)
        except Exception as e:
            log.warning("Watcher %s check failed: %s", wid, e)
            return {"changed": False, "error": str(e)}

    async def _check_website(self, w: dict) -> dict[str, Any]:
        wid, url, condition = w["id"], w["target"], w["condition"]
        try:
            async with httpx.AsyncClient(timeout=25, follow_redirects=True,
                                         headers={"User-Agent": USER_AGENT}) as client:
                resp = await client.get(url)
        except httpx.HTTPError as e:
            return {"changed": False, "error": f"Could not reach {url}: {type(e).__name__}"}

        if condition == "available":
            if resp.status_code < 400:
                self._fire(w, f"{_short_url(url)} is now available.", "The page responded successfully.")
                self.db.update_watcher(wid, active=0, last_change="available")  # one-shot
                return {"changed": True, "reason": "available"}
            return {"changed": False}

        if resp.status_code >= 400:
            return {"changed": False, "error": f"HTTP {resp.status_code}"}

        digest, text = page_fingerprint(resp.text)
        previous = w.get("last_state")
        prev_text = self._last_text.get(wid, "")
        self._last_text[wid] = text[:20000]

        if previous is None:
            self.db.update_watcher(wid, last_state=digest)
            return {"changed": False, "reason": "baseline recorded"}

        if digest != previous:
            summary = _diff_summary(prev_text, text)
            self.db.update_watcher(wid, last_state=digest, last_change=summary[:500])
            self._fire(w, f"{_short_url(url)} changed.", summary)
            return {"changed": True, "summary": summary}
        return {"changed": False}

    def _check_folder(self, w: dict) -> dict[str, Any]:
        wid, target = w["id"], Path(w["target"])
        if not target.exists():
            return {"changed": False, "error": f"{target} does not exist."}
        pattern = "*"
        cond = w["condition"]
        if cond.startswith("new_file:"):
            pattern = cond.split(":", 1)[1] or "*"
        digest, names = folder_fingerprint(target, pattern)
        previous = w.get("last_state")
        if previous is None:
            self.db.update_watcher(wid, last_state=digest)
            return {"changed": False, "reason": "baseline recorded"}
        if digest != previous:
            prev_names = set((w.get("last_change") or "").split("|"))
            new_items = [n for n in names if n not in prev_names]
            self.db.update_watcher(wid, last_state=digest, last_change="|".join(names)[:500])
            detail = ", ".join(new_items[:5]) if new_items else "Folder contents changed"
            self._fire(w, f"New files in {target.name}", detail)
            return {"changed": True, "new_files": new_items}
        return {"changed": False}

    def _fire(self, w: dict, title: str, body: str) -> None:
        self.db.add_notification(title, body)
        self.db.add_history("system", detail=f"Watcher: {title}", status="ok")
        if self.notifier:
            try:
                self.notifier(title, body[:250])
            except Exception:
                log.exception("Notifier failed")
        if self.on_change:
            try:
                self.on_change(w, body)
            except Exception:
                log.exception("Watcher listener failed")


def _short_url(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url).split("/")[0] or url


def _diff_summary(old: str, new: str, limit: int = 240) -> str:
    """A cheap, readable description of what appeared on the page."""
    if not old:
        return "The page content changed."
    old_words = set(old.split())
    added = [w for w in new.split() if w not in old_words]
    if not added:
        return "The page content changed (text was removed or reordered)."
    snippet = " ".join(added[:40])
    return f"New content appeared: {snippet[:limit]}"
