"""Tool registry validation and the file tools."""

from __future__ import annotations

import pytest

from nova.core.tools.files import create_folder, find_file, move_file, read_file_metadata, rename_file
from nova.core.tools.registry import ToolRegistry, ValidationError


def test_every_tool_has_a_schema(registry):
    for tool in registry.all():
        schema = tool.schema()
        assert schema["function"]["name"] == tool.name
        assert schema["function"]["description"], f"{tool.name} has no description"


def test_validation_rejects_missing_required(registry):
    with pytest.raises(ValidationError):
        registry.validate("create_folder", {})


def test_validation_rejects_unknown_tool(registry):
    with pytest.raises(ValidationError):
        registry.validate("format_hard_drive", {})


def test_validation_coerces_types(registry):
    clean = registry.validate("find_file", {"query": "a", "limit": "5"})
    assert clean["limit"] == 5


def test_validation_applies_defaults(registry):
    clean = registry.validate("find_file", {"query": "x"})
    assert clean["folder"] == "home"


def test_validation_rejects_bad_enum(registry):
    with pytest.raises(ValidationError):
        registry.validate("scroll", {"direction": "sideways"})


def test_unknown_arguments_are_dropped(registry):
    clean = registry.validate("create_folder", {"name": "X", "parent": "home", "sudo": True})
    assert "sudo" not in clean


async def test_tool_failure_is_captured_not_raised(registry):
    result = await registry.call("open_file", {"path": "/definitely/not/here.txt"})
    assert result.ok is False
    assert "couldn't find" in result.message.lower()


# ---------- file tools ----------
def test_create_folder_verifies_result(sandbox):
    result = create_folder("Reports", str(sandbox))
    assert result.ok
    assert (sandbox / "Reports").is_dir()


def test_create_folder_is_idempotent(sandbox):
    create_folder("Reports", str(sandbox))
    again = create_folder("Reports", str(sandbox))
    assert again.ok and again.data["created"] is False


def test_create_folder_strips_invalid_characters(sandbox):
    result = create_folder('my<>:"project', str(sandbox))
    assert result.ok
    assert (sandbox / "myproject").exists()


def test_find_file_by_extension(sandbox):
    result = find_file(query="", folder=str(sandbox), extension="pdf")
    assert result.ok
    assert result.data["files"][0]["name"] == "report.pdf"


def test_find_file_reports_nothing_found(sandbox):
    result = find_file(query="nosuchfile", folder=str(sandbox))
    assert result.ok is False
    assert result.data["files"] == []


def test_move_file_verifies(sandbox):
    (sandbox / "docs").mkdir(exist_ok=True)
    result = move_file(str(sandbox / "report.pdf"), str(sandbox / "docs"))
    assert result.ok
    assert (sandbox / "docs" / "report.pdf").exists()
    assert not (sandbox / "report.pdf").exists()


def test_move_missing_file_fails_honestly(sandbox):
    result = move_file(str(sandbox / "ghost.pdf"), str(sandbox / "docs"))
    assert result.ok is False
    assert "couldn't find" in result.message.lower()


def test_rename_keeps_extension(sandbox):
    result = rename_file(str(sandbox / "report.pdf"), "Final Report")
    assert result.ok
    assert (sandbox / "Final Report.pdf").exists()


def test_rename_refuses_to_overwrite(sandbox):
    (sandbox / "taken.txt").write_text("x")
    result = rename_file(str(sandbox / "notes.txt"), "taken.txt")
    assert result.ok is False


def test_metadata(sandbox):
    result = read_file_metadata(str(sandbox / "notes.txt"))
    assert result.ok
    assert result.data["type"] == "txt"


def test_delete_refuses_protected_paths_even_when_called_directly():
    """Defense in depth: the tool guards itself, not just the safety gate."""
    from nova.core.tools.files import delete_file

    result = delete_file([r"C:\Windows\System32\kernel32.dll"])
    assert result.ok is False
    assert "protected" in result.message.lower()


def test_registry_is_isolated():
    r = ToolRegistry()
    assert r.names() == []
