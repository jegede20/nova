"""The safety rules are the most important thing to get right."""

from __future__ import annotations

import pytest

from nova.core.safety import Risk, SafetyGate, contains_sensitive_words, is_protected_path


def test_low_risk_runs_immediately(gate):
    d = gate.evaluate("open_app", {"name": "Chrome"})
    assert d.risk is Risk.LOW
    assert d.allowed and not d.needs_confirmation


def test_delete_always_requires_confirmation(gate, settings):
    settings.set("confirm_medium_risk", False)  # must not weaken high risk
    d = gate.evaluate("delete_file", {"paths": ["/home/u/a.txt"]})
    assert d.risk is Risk.HIGH
    assert d.needs_confirmation and not d.allowed


def test_bulk_move_escalates_to_high(gate, settings):
    settings.set("bulk_file_threshold", 3)
    d = gate.evaluate("move_file", {"paths": [f"/home/u/{i}.txt" for i in range(9)],
                                    "source": "/home/u/0.txt", "destination": "/home/u/docs"})
    assert d.risk is Risk.HIGH
    assert "9 files" in " ".join(d.details)


def test_small_move_is_medium(gate):
    d = gate.evaluate("move_file", {"source": "/home/u/a.pdf", "destination": "/home/u/Documents"})
    assert d.risk is Risk.MEDIUM
    assert d.needs_confirmation


def test_medium_confirmation_can_be_disabled(gate, settings):
    settings.set("confirm_medium_risk", False)
    d = gate.evaluate("move_file", {"source": "/home/u/a.pdf", "destination": "/home/u/Documents"})
    assert d.allowed and not d.needs_confirmation


@pytest.mark.parametrize("path", [
    r"C:\Windows\System32", r"C:\Program Files\app", "/etc/passwd", "/usr/bin/python",
])
def test_protected_paths_are_blocked(gate, path):
    d = gate.evaluate("delete_file", {"paths": [path]})
    assert d.risk is Risk.BLOCKED
    assert not d.allowed and not d.needs_confirmation


def test_protected_path_detection():
    assert is_protected_path(r"C:\Windows\explorer.exe")
    assert not is_protected_path(r"C:\Users\me\Downloads\a.pdf")


def test_typing_credentials_is_refused(gate):
    d = gate.evaluate("type_text", {"text": "my password is hunter2"})
    assert d.risk is Risk.BLOCKED


def test_sensitive_button_escalates(gate):
    d = gate.evaluate("browser_click", {"text": "Place order"})
    assert d.risk is Risk.HIGH
    assert d.needs_confirmation


def test_ordinary_button_is_medium(gate):
    d = gate.evaluate("browser_click", {"text": "Read more"})
    assert d.risk is Risk.MEDIUM


def test_sensitive_words():
    assert contains_sensitive_words("Confirm purchase")
    assert contains_sensitive_words("Delete account")
    assert not contains_sensitive_words("Open settings")


def test_unknown_tool_defaults_to_medium():
    g = SafetyGate()
    assert g.base_risk("something_new") is Risk.MEDIUM


def test_delete_summary_is_explicit(gate):
    d = gate.evaluate("delete_file", {"paths": [f"/home/u/Downloads/{i}.pdf" for i in range(28)]})
    assert "28" in d.summary
    assert "cannot easily be undone" in d.summary.lower()
