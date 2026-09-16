from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Point Nova at a throwaway data directory before anything imports paths.
_TMP = tempfile.mkdtemp(prefix="nova-test-")
os.environ["NOVA_HOME"] = _TMP


@pytest.fixture()
def db(tmp_path: Path):
    from nova.core.database import Database

    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture()
def settings(db):
    from nova.core.settings import Settings

    return Settings(db)


@pytest.fixture()
def gate(settings):
    from nova.core.safety import SafetyGate

    return SafetyGate(settings)


@pytest.fixture()
def registry():
    from nova.core.tools import apps, browser, files, screen, system  # noqa: F401
    from nova.core.tools.registry import registry as reg

    return reg


@pytest.fixture()
def sandbox(tmp_path: Path):
    """A folder with a few files to act on."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "report.pdf").write_text("pdf")
    (tmp_path / "notes.txt").write_text("hello")
    return tmp_path
