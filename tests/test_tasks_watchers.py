"""Background tasks, cancellation, watchers and voice identity."""

from __future__ import annotations

import asyncio
import time

import numpy as np

from nova.core.tasks import TaskManager, TaskState
from nova.core.watchers import WatcherService, folder_fingerprint, page_fingerprint
from nova.voice.speaker_id import SpeakerProfile, cosine, embed


# ---------------------------------------------------------------- tasks
def test_task_runs_to_completion(db):
    tm = TaskManager(db)
    tm.start()
    try:
        async def job(handle):
            await handle.checkpoint()
            handle.progress(0.5)
            return "all done"

        task_id = tm.submit("Test job", job)
        for _ in range(50):
            row = db.get_task(task_id)
            if row["state"] in {TaskState.COMPLETED.value, TaskState.FAILED.value}:
                break
            time.sleep(0.05)
        row = db.get_task(task_id)
        assert row["state"] == TaskState.COMPLETED.value
        assert row["result"] == "all done"
    finally:
        tm.stop()


def test_task_can_be_cancelled(db):
    tm = TaskManager(db)
    tm.start()
    try:
        async def long_job(handle):
            for _ in range(200):
                await handle.checkpoint()
                await asyncio.sleep(0.05)
            return "finished"

        task_id = tm.submit("Long job", long_job)
        time.sleep(0.3)
        assert tm.cancel(task_id)
        for _ in range(40):
            if db.get_task(task_id)["state"] == TaskState.CANCELLED.value:
                break
            time.sleep(0.05)
        assert db.get_task(task_id)["state"] == TaskState.CANCELLED.value
    finally:
        tm.stop()


def test_failing_task_is_marked_failed(db):
    tm = TaskManager(db)
    tm.start()
    try:
        async def bad(handle):
            raise ValueError("nope")

        task_id = tm.submit("Bad job", bad)
        for _ in range(50):
            if db.get_task(task_id)["state"] == TaskState.FAILED.value:
                break
            time.sleep(0.05)
        row = db.get_task(task_id)
        assert row["state"] == TaskState.FAILED.value
        assert "nope" in row["error"]
    finally:
        tm.stop()


def test_orphan_tasks_are_marked_on_restart(db):
    db.create_task("Ghost", "x")
    db.update_task(1, state="running")
    TaskManager(db)   # constructor cleans up
    assert db.get_task(1)["state"] == "failed"


# ---------------------------------------------------------------- watchers
def test_page_fingerprint_ignores_markup():
    a, _ = page_fingerprint("<html><body><p>Hello world</p></body></html>")
    b, _ = page_fingerprint("<html><body><div>Hello   world</div></body></html>")
    assert a == b


def test_page_fingerprint_detects_content_change():
    a, _ = page_fingerprint("<p>Version 1.0</p>")
    b, _ = page_fingerprint("<p>Version 1.1</p>")
    assert a != b


def test_page_fingerprint_ignores_scripts():
    a, _ = page_fingerprint("<p>Docs</p><script>var t=1;</script>")
    b, _ = page_fingerprint("<p>Docs</p><script>var t=999;</script>")
    assert a == b


def test_folder_fingerprint_changes_with_new_file(tmp_path):
    (tmp_path / "a.pdf").write_text("a")
    first, _ = folder_fingerprint(tmp_path)
    (tmp_path / "b.pdf").write_text("b")
    second, _ = folder_fingerprint(tmp_path)
    assert first != second


def test_folder_watcher_detects_new_file(db, tmp_path):
    (tmp_path / "one.pdf").write_text("x")
    svc = WatcherService(db)
    wid = svc.add_folder(str(tmp_path), 60, "new_file")
    svc._check_folder(db.get_watcher(wid))            # baseline
    (tmp_path / "two.pdf").write_text("y")
    result = svc._check_folder(db.get_watcher(wid))
    assert result["changed"] is True
    assert "two.pdf" in result["new_files"]


def test_watcher_interval_has_a_floor(db):
    svc = WatcherService(db)
    wid = svc.add_website("https://example.com", interval_s=5)
    assert db.get_watcher(wid)["interval_s"] >= 60


def test_watcher_can_be_stopped(db):
    svc = WatcherService(db)
    wid = svc.add_website("https://example.com")
    assert svc.stop_watcher(wid)
    assert db.get_watcher(wid)["active"] == 0
    assert svc.stop_watcher(9999) is False


# ---------------------------------------------------------------- voice identity
def _tone(freq: float, seconds: float = 2.5, sr: int = 16000) -> np.ndarray:
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    wave = 0.4 * np.sin(2 * np.pi * freq * t)
    wave += 0.2 * np.sin(2 * np.pi * freq * 2 * t)
    wave += 0.05 * np.random.RandomState(int(freq)).randn(len(t))
    return wave.astype(np.float32)


def test_same_voice_scores_higher_than_different_voice():
    a1, _ = embed(_tone(140))
    a2, _ = embed(_tone(142))
    b, _ = embed(_tone(430))
    assert cosine(a1, a2) > cosine(a1, b)


def test_enrollment_requires_enough_samples(tmp_path):
    profile = SpeakerProfile(tmp_path / "p.json")
    ok, _ = profile.add_sample(_tone(150))
    assert ok
    done, message = profile.finalize()
    assert done is False
    assert "need" in message.lower()


def test_enrollment_and_verification(tmp_path):
    profile = SpeakerProfile(tmp_path / "p.json")
    for freq in (150, 152, 148, 151):
        assert profile.add_sample(_tone(freq))[0]
    saved, _ = profile.finalize()
    assert saved and profile.enrolled

    match = profile.verify(_tone(150), threshold=0.5)
    assert match.authorized

    reloaded = SpeakerProfile(tmp_path / "p.json")
    assert reloaded.enrolled


def test_short_sample_is_rejected(tmp_path):
    profile = SpeakerProfile(tmp_path / "p.json")
    ok, message = profile.add_sample(_tone(150, seconds=0.3))
    assert ok is False
    assert "short" in message.lower()


def test_silence_is_rejected(tmp_path):
    profile = SpeakerProfile(tmp_path / "p.json")
    ok, message = profile.add_sample(np.zeros(16000 * 3, dtype=np.float32))
    assert ok is False
    assert "microphone" in message.lower()


def test_unenrolled_profile_allows_everyone(tmp_path):
    profile = SpeakerProfile(tmp_path / "missing.json")
    result = profile.verify(_tone(150))
    assert result.authorized is True


def test_profile_stores_no_audio(tmp_path):
    profile = SpeakerProfile(tmp_path / "p.json")
    for freq in (150, 152, 148, 151):
        profile.add_sample(_tone(freq))
    profile.finalize()
    content = (tmp_path / "p.json").read_text()
    assert "wav" not in content.lower()
    assert "No audio recordings are stored" in content
