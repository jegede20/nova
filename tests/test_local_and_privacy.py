"""Offline interpretation, secret redaction and settings storage."""

from __future__ import annotations

from nova.ai.local_intent import interpret
from nova.core.logging_setup import redact


def test_open_app_offline():
    intent = interpret("Hey Nova, open Chrome")
    assert intent and intent.tool == "open_app"
    assert intent.args["name"] == "chrome"


def test_open_folder_offline():
    intent = interpret("Hey Nova, open my Downloads folder")
    assert intent and intent.tool == "open_folder"
    assert "download" in intent.args["path"]


def test_create_folder_offline():
    intent = interpret("Nova, create a folder called Hackathon Projects on my Desktop")
    assert intent and intent.tool == "create_folder"
    assert intent.args["name"] == "Hackathon Projects"   # user's capitalisation is kept
    assert intent.args["parent"] == "desktop"


def test_find_pdf_offline():
    intent = interpret("find my latest pdf in downloads")
    assert intent and intent.tool == "find_file"
    assert intent.args["extension"] == "pdf"


def test_close_app_offline():
    intent = interpret("close chrome")
    assert intent and intent.tool == "close_app"


def test_stop_offline():
    assert interpret("Nova, stop everything").tool == "cancel_all"


def test_complex_request_is_not_handled_locally():
    assert interpret("summarise the quarterly numbers and email them to my manager") is None


# ---------- privacy ----------
def test_api_keys_are_redacted_from_logs():
    line = "calling openai with sk-abcdef1234567890abcdef"
    assert "sk-abcdef1234567890abcdef" not in redact(line)
    assert "REDACTED" in redact(line)


def test_password_assignments_are_redacted():
    assert "hunter2" not in redact("password: hunter2")
    assert "secret-token" not in redact("api_key=secret-token")


def test_bearer_tokens_are_redacted():
    assert "abc123xyz" not in redact("Authorization: Bearer abc123xyz")


def test_ordinary_text_survives_redaction():
    text = "Opened C:\\Users\\me\\Downloads"
    assert redact(text) == text


# ---------- settings ----------
def test_settings_defaults(settings):
    assert settings.get("wake_word") == "hey nova"
    assert settings.get("confirm_high_risk") is True


def test_settings_roundtrip(settings):
    settings.set("wake_word", "hey aurora")
    assert settings.get("wake_word") == "hey aurora"


def test_api_keys_never_land_in_the_database(settings, db):
    settings.set("openai_api_key", "sk-should-not-be-in-sqlite")
    rows = db.query("SELECT key, value FROM settings")
    assert all("sk-should-not-be-in-sqlite" not in str(r) for r in rows)


def test_history_and_permissions_storage(db):
    db.add_history("command", command="open chrome", detail="User command")
    db.record_permission("delete_file", "/tmp/x", "allow", remembered=True)
    assert db.recent_history(5)[0]["command"] == "open chrome"
    assert db.remembered_decision("delete_file", "/tmp/x") == "allow"


def test_task_state_transitions(db):
    task_id = db.create_task("Download PDFs", "download everything", ["step one", "step two"])
    db.update_task(task_id, state="running", progress=0.4)
    row = db.get_task(task_id)
    assert row["state"] == "running"
    assert row["progress"] == 0.4
    assert len(db.list_tasks(states=["running"])) == 1
