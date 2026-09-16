"""SQLite storage for Nova: settings, history, tasks, watchers, permissions.

One small wrapper class, thread-safe via a lock, no ORM.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .paths import db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         REAL NOT NULL,
    kind       TEXT NOT NULL,          -- command | action | response | error | system
    command    TEXT,                   -- what the user said/typed
    detail     TEXT,                   -- human readable description
    tool       TEXT,
    status     TEXT,                   -- ok | failed | cancelled | denied
    task_id    INTEGER
);

CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    command     TEXT,
    state       TEXT NOT NULL,         -- pending|running|waiting|paused|completed|failed|cancelled
    progress    REAL DEFAULT 0.0,
    plan        TEXT,                  -- JSON list of steps
    result      TEXT,
    error       TEXT,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS watchers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    target        TEXT NOT NULL,
    wtype         TEXT NOT NULL,       -- website | folder
    interval_s    INTEGER NOT NULL,
    condition     TEXT NOT NULL,       -- changed | available | new_file
    last_state    TEXT,
    last_checked  REAL,
    notify        TEXT DEFAULT 'notification',
    active        INTEGER DEFAULT 1,
    created_at    REAL NOT NULL,
    last_change   TEXT
);

CREATE TABLE IF NOT EXISTS permissions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    action     TEXT NOT NULL,
    scope      TEXT,
    decision   TEXT NOT NULL,          -- allow | deny
    remembered INTEGER DEFAULT 0,
    ts         REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      REAL NOT NULL,
    title   TEXT NOT NULL,
    body    TEXT,
    seen    INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_history_ts ON history(ts DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state);
"""


class Database:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else db_path()
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # ---------- low level ----------
    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def query_one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---------- settings ----------
    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.query_one("SELECT value FROM settings WHERE key=?", (key,))
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return row["value"]

    def set_setting(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )

    def all_settings(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for row in self.query("SELECT key,value FROM settings"):
            try:
                out[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:
                out[row["key"]] = row["value"]
        return out

    # ---------- history ----------
    def add_history(
        self,
        kind: str,
        command: str | None = None,
        detail: str | None = None,
        tool: str | None = None,
        status: str | None = None,
        task_id: int | None = None,
    ) -> int:
        cur = self.execute(
            "INSERT INTO history(ts,kind,command,detail,tool,status,task_id) VALUES(?,?,?,?,?,?,?)",
            (time.time(), kind, command, detail, tool, status, task_id),
        )
        return int(cur.lastrowid or 0)

    def recent_history(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.query("SELECT * FROM history ORDER BY ts DESC LIMIT ?", (limit,))

    def clear_history(self) -> None:
        self.execute("DELETE FROM history")

    # ---------- tasks ----------
    def create_task(self, title: str, command: str = "", plan: list[str] | None = None) -> int:
        now = time.time()
        cur = self.execute(
            "INSERT INTO tasks(title,command,state,progress,plan,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (title, command, "pending", 0.0, json.dumps(plan or []), now, now),
        )
        return int(cur.lastrowid or 0)

    def update_task(self, task_id: int, **fields: Any) -> None:
        if not fields:
            return
        allowed = {"title", "command", "state", "progress", "plan", "result", "error"}
        sets, params = [], []
        for k, v in fields.items():
            if k not in allowed:
                continue
            sets.append(f"{k}=?")
            params.append(json.dumps(v) if k == "plan" else v)
        if not sets:
            return
        sets.append("updated_at=?")
        params.extend([time.time(), task_id])
        self.execute(f"UPDATE tasks SET {','.join(sets)} WHERE id=?", tuple(params))

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        return self.query_one("SELECT * FROM tasks WHERE id=?", (task_id,))

    def list_tasks(self, states: list[str] | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if states:
            marks = ",".join("?" * len(states))
            return self.query(
                f"SELECT * FROM tasks WHERE state IN ({marks}) ORDER BY created_at DESC LIMIT ?",
                (*states, limit),
            )
        return self.query("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,))

    # ---------- watchers ----------
    def create_watcher(
        self,
        name: str,
        target: str,
        wtype: str,
        interval_s: int,
        condition: str,
        notify: str = "notification",
    ) -> int:
        cur = self.execute(
            "INSERT INTO watchers(name,target,wtype,interval_s,condition,notify,active,created_at)"
            " VALUES(?,?,?,?,?,?,1,?)",
            (name, target, wtype, interval_s, condition, notify, time.time()),
        )
        return int(cur.lastrowid or 0)

    def update_watcher(self, watcher_id: int, **fields: Any) -> None:
        allowed = {"name", "target", "interval_s", "condition", "last_state", "last_checked", "active", "last_change"}
        sets, params = [], []
        for k, v in fields.items():
            if k in allowed:
                sets.append(f"{k}=?")
                params.append(v)
        if not sets:
            return
        params.append(watcher_id)
        self.execute(f"UPDATE watchers SET {','.join(sets)} WHERE id=?", tuple(params))

    def list_watchers(self, active_only: bool = False) -> list[dict[str, Any]]:
        if active_only:
            return self.query("SELECT * FROM watchers WHERE active=1 ORDER BY created_at DESC")
        return self.query("SELECT * FROM watchers ORDER BY created_at DESC")

    def get_watcher(self, watcher_id: int) -> dict[str, Any] | None:
        return self.query_one("SELECT * FROM watchers WHERE id=?", (watcher_id,))

    def delete_watcher(self, watcher_id: int) -> None:
        self.execute("DELETE FROM watchers WHERE id=?", (watcher_id,))

    # ---------- permissions ----------
    def record_permission(self, action: str, scope: str, decision: str, remembered: bool = False) -> None:
        self.execute(
            "INSERT INTO permissions(action,scope,decision,remembered,ts) VALUES(?,?,?,?,?)",
            (action, scope, decision, int(remembered), time.time()),
        )

    def remembered_decision(self, action: str, scope: str) -> str | None:
        row = self.query_one(
            "SELECT decision FROM permissions WHERE action=? AND scope=? AND remembered=1 ORDER BY ts DESC LIMIT 1",
            (action, scope),
        )
        return row["decision"] if row else None

    # ---------- notifications ----------
    def add_notification(self, title: str, body: str = "") -> int:
        cur = self.execute(
            "INSERT INTO notifications(ts,title,body) VALUES(?,?,?)", (time.time(), title, body)
        )
        return int(cur.lastrowid or 0)

    def recent_notifications(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.query("SELECT * FROM notifications ORDER BY ts DESC LIMIT ?", (limit,))


_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        _db = Database()
    return _db


def reset_db_for_tests(path: Path | str) -> Database:
    global _db
    _db = Database(path)
    return _db
