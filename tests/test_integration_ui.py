"""End-to-end checks against the real Qt window.

Covers the things unit tests can't: closing to tray, the cross-thread
confirmation round trip, and the Stop button cancelling live work.
"""

from __future__ import annotations

import asyncio
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtGui import QCloseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from nova.ai.provider import AIProvider, AIResponse, ToolCall  # noqa: E402
from nova.core.database import Database  # noqa: E402
from nova.core.nova_core import NovaCore  # noqa: E402
from nova.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


@pytest.fixture()
def core(tmp_path, app):
    c = NovaCore(Database(tmp_path / "ui.db"))
    c.settings.set("voice_activation", False)
    c.settings.set("tts_enabled", False)
    c.tasks.start()
    yield c
    c.shutdown()


@pytest.fixture()
def window(core, app):
    w = MainWindow(core, start_hidden=True)
    yield w
    w.timer.stop()
    w.tray.hide()


def pump(app, seconds: float = 0.4) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def test_all_pages_open_without_error(window, app):
    for key in ["dashboard", "tasks", "watchers", "history", "settings",
                "enroll", "security", "about"]:
        window.show_page(key)
        pump(app, 0.05)
    assert window.stack.currentWidget() is window.pages["about"]


def test_closing_the_window_keeps_nova_running(window, core, app):
    core.settings.set("minimize_to_tray", True)
    window.show()
    pump(app, 0.1)
    event = QCloseEvent()
    window.closeEvent(event)
    pump(app, 0.1)
    assert not event.isAccepted()      # close was intercepted
    assert window.isHidden()
    assert QApplication.instance() is not None
    assert core.tasks.loop.is_running()


def test_tray_menu_has_the_expected_entries(window):
    labels = [a.text() for a in window.tray.contextMenu().actions() if a.text()]
    for expected in ["Nova", "Open Nova", "Tasks", "Watchers", "History",
                     "Settings", "Pause listening", "Resume listening", "Exit"]:
        assert expected in labels


def test_tray_open_restores_the_window(window, app):
    window.hide()
    window.tray.on_open()
    pump(app, 0.1)
    assert window.isVisible()


class ConfirmingProvider(AIProvider):
    """Asks to delete a file, then reports what happened."""

    name = "confirming"

    def __init__(self, target):
        super().__init__("k", "m")
        self.target = target
        self.turn = 0

    def available(self):
        return True

    async def chat(self, messages, tools=None, timeout=60.0):
        self.turn += 1
        if self.turn == 1:
            return AIResponse(tool_calls=[ToolCall("1", "delete_file", {"paths": [str(self.target)]})])
        return AIResponse(text="Finished.")


def test_confirmation_round_trip_through_the_ui(window, core, app, tmp_path):
    """The agent runs on a worker loop; the user answers on the UI thread."""
    victim = tmp_path / "delete_me.txt"
    victim.write_text("data")
    core.agent._provider = ConfirmingProvider(victim)

    future = core.submit_command("delete that file", speak=False)

    # Wait for the confirmation banner to appear.
    deadline = time.time() + 5
    while time.time() < deadline and not window.dashboard.confirm.isVisible():
        pump(app, 0.05)
    assert window.dashboard.confirm.isVisible(), "Nova should have asked before deleting"
    assert "delete_me.txt" in window.dashboard.confirm.title.text()
    assert victim.exists(), "nothing may be deleted before approval"

    window._answer_confirm(True)          # user clicks Approve
    deadline = time.time() + 5
    while time.time() < deadline and future.running():
        pump(app, 0.05)
    reply = future.result(timeout=5)
    assert reply.ok
    assert not victim.exists(), "the file should be gone after approval"


def test_declining_leaves_the_file_alone(window, core, app, tmp_path):
    victim = tmp_path / "keep_me.txt"
    victim.write_text("data")
    core.agent._provider = ConfirmingProvider(victim)

    future = core.submit_command("delete that file", speak=False)
    deadline = time.time() + 5
    while time.time() < deadline and not window.dashboard.confirm.isVisible():
        pump(app, 0.05)
    assert window.dashboard.confirm.isVisible()

    window._answer_confirm(False)          # user clicks Cancel
    future.result(timeout=5)
    assert victim.exists(), "declining must not delete anything"
    assert not window.dashboard.confirm.isVisible()


def test_stop_button_cancels_running_tasks(window, core, app):
    async def long_job(handle):
        for _ in range(200):
            await handle.checkpoint()
            await asyncio.sleep(0.05)
        return "done"

    task_id = core.tasks.submit("Slow job", long_job)
    pump(app, 0.3)
    assert core.tasks.running_count == 1

    window._stop_everything()

    deadline = time.time() + 5
    while time.time() < deadline and core.db.get_task(task_id)["state"] not in {"cancelled", "failed"}:
        pump(app, 0.05)
    assert core.db.get_task(task_id)["state"] == "cancelled"


def test_status_updates_reach_the_ui(window, core, app):
    window._set_state("executing")
    assert "Executing" in window.dashboard.status_label.text()
    window._set_state("waiting_confirmation")
    assert "confirmation" in window.dashboard.status_label.text().lower()
    window._set_state("idle")
    assert window.dashboard.status_label.text() == "Ready"


def test_activity_feed_is_capped(window, app):
    for i in range(80):
        window.dashboard.add_activity(f"entry {i}")
    assert window.dashboard.activity_body.count() <= 42
