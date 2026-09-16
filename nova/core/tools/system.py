"""Tools that reach back into Nova itself: tasks, watchers, notifications, speech.

These are wired up by NovaCore at startup via `bind_services`, which keeps the
tool functions free of import cycles.
"""

from __future__ import annotations

from typing import Any

from ..logging_setup import get_logger
from .registry import ToolResult, registry

log = get_logger("tools.system")

_services: dict[str, Any] = {}


def bind_services(**services: Any) -> None:
    """Called once by NovaCore: task_manager, watchers, notifier, tts, agent_runner."""
    _services.update(services)


def _svc(name: str) -> Any:
    return _services.get(name)


# ---------------------------------------------------------------- tasks
@registry.tool(
    "create_task",
    "Start a long-running job in the background so the user can keep working. Use for multi-step jobs like downloading many files.",
    {"title": {"type": "string", "description": "Short task name", "required": True},
     "instruction": {"type": "string", "description": "Full description of the work to carry out", "required": True}},
    category="tasks",
)
def create_task(title: str, instruction: str) -> ToolResult:
    runner = _svc("background_runner")
    if runner is None:
        return ToolResult.fail("Background tasks aren't available right now.")
    try:
        task_id = runner(title, instruction)
    except Exception as e:
        return ToolResult.fail(f"I couldn't start that task: {e}")
    return ToolResult.success(f"Started '{title}' in the background. I'll let you know when it's done.",
                              task_id=task_id, state="running")


@registry.tool(
    "get_task_status",
    "Check the status of a background task.",
    {"task_id": {"type": "integer", "description": "Task number, or 0 for the most recent"}},
    category="tasks",
)
def get_task_status(task_id: int = 0) -> ToolResult:
    tm = _svc("task_manager")
    if tm is None:
        return ToolResult.fail("The task system isn't running.")
    if task_id:
        row = tm.status(task_id)
        if not row:
            return ToolResult.fail(f"I don't have a task number {task_id}.")
    else:
        rows = tm.db.list_tasks(limit=1)
        if not rows:
            return ToolResult.success("You don't have any tasks yet.", tasks=[])
        row = rows[0]
    pct = int((row.get("progress") or 0) * 100)
    detail = row.get("result") or row.get("error") or ""
    msg = f"'{row['title']}' is {row['state']}"
    msg += f" at {pct} percent." if row["state"] == "running" and pct else "."
    if detail:
        msg += f" {detail}"
    return ToolResult.success(msg, task_id=row["id"], state=row["state"], progress=pct)


@registry.tool(
    "list_tasks",
    "List the user's background tasks and their states.",
    {"active_only": {"type": "boolean", "description": "Only unfinished tasks", "default": True}},
    category="tasks",
)
def list_tasks(active_only: bool = True) -> ToolResult:
    tm = _svc("task_manager")
    if tm is None:
        return ToolResult.fail("The task system isn't running.")
    rows = tm.active() if active_only else tm.db.list_tasks(limit=20)
    if not rows:
        return ToolResult.success("Nothing is running right now.", tasks=[])
    tasks = [{"id": r["id"], "title": r["title"], "state": r["state"],
              "progress": int((r.get("progress") or 0) * 100)} for r in rows]
    names = ", ".join(f"{t['title']} ({t['state']})" for t in tasks[:4])
    return ToolResult.success(f"You have {len(tasks)} task{'s' if len(tasks) != 1 else ''}: {names}.", tasks=tasks)


@registry.tool(
    "cancel_task",
    "Cancel a running background task.",
    {"task_id": {"type": "integer", "description": "Task number, or 0 to cancel everything"}},
    category="tasks",
)
def cancel_task(task_id: int = 0) -> ToolResult:
    tm = _svc("task_manager")
    if tm is None:
        return ToolResult.fail("The task system isn't running.")
    if task_id == 0:
        count = tm.cancel_all()
        return ToolResult.success(f"Cancelled {count} task{'s' if count != 1 else ''}." if count
                                  else "There was nothing running to cancel.", cancelled=count)
    if tm.cancel(task_id):
        return ToolResult.success(f"Cancelled task {task_id}.", task_id=task_id)
    return ToolResult.fail(f"Task {task_id} isn't running.")


@registry.tool(
    "pause_task",
    "Pause a running background task.",
    {"task_id": {"type": "integer", "description": "Task number", "required": True}},
    category="tasks",
)
def pause_task(task_id: int) -> ToolResult:
    tm = _svc("task_manager")
    if tm is None or not tm.pause(task_id):
        return ToolResult.fail(f"I couldn't pause task {task_id} - it may not be running.")
    return ToolResult.success(f"Paused task {task_id}.")


@registry.tool(
    "resume_task",
    "Resume a paused background task.",
    {"task_id": {"type": "integer", "description": "Task number", "required": True}},
    category="tasks",
)
def resume_task(task_id: int) -> ToolResult:
    tm = _svc("task_manager")
    if tm is None or not tm.resume(task_id):
        return ToolResult.fail(f"I couldn't resume task {task_id}.")
    return ToolResult.success(f"Resumed task {task_id}.")


# ---------------------------------------------------------------- watchers
@registry.tool(
    "watch_website",
    "Monitor a web page and notify the user when it changes or becomes available.",
    {"url": {"type": "string", "description": "Page to monitor", "required": True},
     "interval_minutes": {"type": "integer", "description": "How often to check (minimum 1)", "default": 10},
     "condition": {"type": "string", "description": "What to watch for",
                   "enum": ["changed", "available"], "default": "changed"}},
    category="watchers",
)
def watch_website(url: str, interval_minutes: int = 10, condition: str = "changed") -> ToolResult:
    svc = _svc("watchers")
    if svc is None:
        return ToolResult.fail("The watcher system isn't running.")
    minutes = max(1, int(interval_minutes))
    try:
        wid = svc.add_website(url, minutes * 60, condition)
    except Exception as e:
        return ToolResult.fail(f"I couldn't set up that watcher: {e}")
    what = "becomes available" if condition == "available" else "changes"
    return ToolResult.success(f"I'll check that page every {minutes} minutes and tell you when it {what}.",
                              watcher_id=wid, interval_minutes=minutes)


@registry.tool(
    "watch_folder",
    "Monitor a folder and notify the user when new files appear.",
    {"path": {"type": "string", "description": "Folder to monitor", "required": True},
     "file_type": {"type": "string", "description": "Optional extension filter such as pdf"},
     "interval_minutes": {"type": "integer", "description": "How often to check", "default": 2}},
    category="watchers",
)
def watch_folder(path: str, file_type: str = "", interval_minutes: int = 2) -> ToolResult:
    svc = _svc("watchers")
    if svc is None:
        return ToolResult.fail("The watcher system isn't running.")
    from .files import resolve_path

    target = resolve_path(path)
    if not target.exists():
        return ToolResult.fail(f"There is no folder at {target}.")
    condition = f"new_file:*.{file_type.lstrip('.')}" if file_type else "new_file"
    wid = svc.add_folder(str(target), max(1, interval_minutes) * 60, condition)
    what = f"new {file_type.upper()} files" if file_type else "new files"
    return ToolResult.success(f"I'm watching {target.name} for {what}.", watcher_id=wid)


@registry.tool(
    "list_watchers",
    "List active monitors for websites and folders.",
    {},
    category="watchers",
)
def list_watchers() -> ToolResult:
    svc = _svc("watchers")
    if svc is None:
        return ToolResult.fail("The watcher system isn't running.")
    rows = svc.list(active_only=True)
    if not rows:
        return ToolResult.success("You aren't monitoring anything right now.", watchers=[])
    items = [{"id": r["id"], "name": r["name"], "type": r["wtype"],
              "interval_minutes": r["interval_s"] // 60, "last_change": r.get("last_change")} for r in rows]
    names = ", ".join(i["name"] for i in items[:4])
    return ToolResult.success(f"You're monitoring {len(items)}: {names}.", watchers=items)


@registry.tool(
    "stop_watcher",
    "Stop monitoring a website or folder.",
    {"watcher_id": {"type": "integer", "description": "Watcher number", "required": True}},
    category="watchers",
)
def stop_watcher(watcher_id: int) -> ToolResult:
    svc = _svc("watchers")
    if svc is None:
        return ToolResult.fail("The watcher system isn't running.")
    if svc.stop_watcher(watcher_id):
        return ToolResult.success(f"Stopped watcher {watcher_id}.")
    return ToolResult.fail(f"I don't have a watcher number {watcher_id}.")


# ---------------------------------------------------------------- output
@registry.tool(
    "send_notification",
    "Show a Windows notification to the user.",
    {"title": {"type": "string", "description": "Notification title", "required": True},
     "message": {"type": "string", "description": "Notification body", "default": ""}},
    category="system",
)
def send_notification(title: str, message: str = "") -> ToolResult:
    notifier = _svc("notifier")
    if notifier is None:
        return ToolResult.fail("Notifications aren't available.")
    shown = notifier.notify(title, message)
    return ToolResult.success("Notification sent." if shown else "Notification saved (system toasts are off).")


@registry.tool(
    "speak",
    "Say something out loud to the user.",
    {"text": {"type": "string", "description": "What to say", "required": True}},
    category="system",
)
def speak(text: str) -> ToolResult:
    tts = _svc("tts")
    if tts is None:
        return ToolResult.fail("Speech output isn't available.")
    tts.speak(text)
    return ToolResult.success("Spoken.")


@registry.tool(
    "get_system_status",
    "Report Nova's own status: listening state, running tasks, active watchers, AI provider.",
    {},
    category="system",
)
def get_system_status() -> ToolResult:
    status = _svc("status_fn")
    if status is None:
        return ToolResult.fail("Status information isn't available.")
    try:
        data = status()
    except Exception as e:
        return ToolResult.fail(f"I couldn't read my own status: {e}")
    return ToolResult.success(
        f"I'm {data.get('state', 'ready')}. {data.get('tasks', 0)} tasks and "
        f"{data.get('watchers', 0)} watchers are active.", **data
    )
