"""Background task manager.

Long jobs run on a dedicated asyncio loop in a worker thread so the Qt UI never
blocks. Every task is cancellable and pausable, and its state lives in SQLite so
it survives a restart (as a record -- running work does not auto-resume).
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .database import Database
from .logging_setup import get_logger

log = get_logger("tasks")


class TaskState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL = {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}


@dataclass
class TaskHandle:
    """Control surface handed to a running job."""

    id: int
    title: str
    db: Database
    _pause: asyncio.Event = field(default_factory=asyncio.Event)
    _cancel: asyncio.Event = field(default_factory=asyncio.Event)
    future: asyncio.Future | None = None
    on_update: Callable[[int], None] | None = None

    def __post_init__(self) -> None:
        self._pause.set()  # set == not paused

    # --- called by the job ---
    async def checkpoint(self) -> None:
        """Jobs call this between steps: raises when cancelled, blocks while paused."""
        if self._cancel.is_set():
            raise asyncio.CancelledError()
        if not self._pause.is_set():
            self.set_state(TaskState.PAUSED)
            await self._pause.wait()
            if self._cancel.is_set():
                raise asyncio.CancelledError()
            self.set_state(TaskState.RUNNING)

    def progress(self, value: float, note: str = "") -> None:
        self.db.update_task(self.id, progress=max(0.0, min(1.0, value)))
        if note:
            self.db.add_history("action", detail=note, task_id=self.id, status="ok")
        self._notify()

    def set_state(self, state: TaskState, result: str = "", error: str = "") -> None:
        fields: dict[str, Any] = {"state": state.value}
        if result:
            fields["result"] = result
        if error:
            fields["error"] = error
        self.db.update_task(self.id, **fields)
        self._notify()

    def _notify(self) -> None:
        if self.on_update:
            try:
                self.on_update(self.id)
            except Exception:
                log.exception("Task update listener failed")

    # --- called by the UI/agent ---
    def pause(self) -> None:
        self._pause.clear()

    def resume(self) -> None:
        self._pause.set()

    def cancel(self) -> None:
        self._cancel.set()
        self._pause.set()  # unblock a paused job so it can notice the cancel
        if self.future and not self.future.done():
            self.future.cancel()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()


JobFn = Callable[[TaskHandle], Coroutine[Any, Any, str]]


class TaskManager:
    """Runs async jobs on a background event loop thread."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._handles: dict[int, TaskHandle] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self.on_update: Callable[[int], None] | None = None
        self._mark_orphans()

    def _mark_orphans(self) -> None:
        """Tasks left 'running' by a crash are not actually running anymore."""
        for row in self.db.list_tasks(states=["running", "waiting", "pending"]):
            self.db.update_task(row["id"], state=TaskState.FAILED.value,
                                error="Nova was closed before this task finished.")

    # ---------- lifecycle ----------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        def runner() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            self._ready.set()
            loop.run_forever()

        self._thread = threading.Thread(target=runner, name="nova-tasks", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)
        log.info("Task manager started")

    def stop(self) -> None:
        for handle in list(self._handles.values()):
            handle.cancel()
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=3)
        log.info("Task manager stopped")

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            self.start()
        assert self._loop is not None
        return self._loop

    # ---------- submitting work ----------
    def submit(self, title: str, job: JobFn, command: str = "", plan: list[str] | None = None) -> int:
        task_id = self.db.create_task(title, command, plan)
        handle = TaskHandle(task_id, title, self.db, on_update=self.on_update)
        self._handles[task_id] = handle

        async def wrapper() -> None:
            handle.set_state(TaskState.RUNNING)
            try:
                result = await job(handle)
                if handle.cancelled:
                    handle.set_state(TaskState.CANCELLED, result="Cancelled by the user.")
                else:
                    handle.set_state(TaskState.COMPLETED, result=str(result or "Done."))
                    handle.progress(1.0)
            except asyncio.CancelledError:
                handle.set_state(TaskState.CANCELLED, result="Cancelled.")
            except Exception as e:
                log.exception("Task %s failed", task_id)
                handle.set_state(TaskState.FAILED, error=f"{type(e).__name__}: {e}")
            finally:
                self._handles.pop(task_id, None)

        future = asyncio.run_coroutine_threadsafe(wrapper(), self.loop)
        handle.future = future  # type: ignore[assignment]
        return task_id

    def run_soon(self, coro: Awaitable) -> Any:
        """Run a coroutine on the worker loop and return a concurrent Future."""
        return asyncio.run_coroutine_threadsafe(coro, self.loop)  # type: ignore[arg-type]

    # ---------- control ----------
    def pause(self, task_id: int) -> bool:
        h = self._handles.get(task_id)
        if not h:
            return False
        h.pause()
        return True

    def resume(self, task_id: int) -> bool:
        h = self._handles.get(task_id)
        if not h:
            return False
        h.resume()
        h.set_state(TaskState.RUNNING)
        return True

    def cancel(self, task_id: int) -> bool:
        h = self._handles.get(task_id)
        if not h:
            row = self.db.get_task(task_id)
            if row and row["state"] in {"pending", "running", "waiting", "paused"}:
                self.db.update_task(task_id, state=TaskState.CANCELLED.value)
                return True
            return False
        h.cancel()
        h.set_state(TaskState.CANCELLED)
        return True

    def cancel_all(self) -> int:
        count = 0
        for tid in list(self._handles):
            if self.cancel(tid):
                count += 1
        return count

    def active(self) -> list[dict]:
        return self.db.list_tasks(states=["pending", "running", "waiting", "paused"])

    def status(self, task_id: int) -> dict | None:
        return self.db.get_task(task_id)

    @property
    def running_count(self) -> int:
        return len(self._handles)
