"""Tests for scheduled runs: lock file, exit codes, logging, crash handling."""

import logging
import os
import time

import pytest

from src import clean, ingest, run_pipeline
from tests.helpers import image_bytes


# --- lock file ----------------------------------------------------------------------
def test_only_one_lock_at_a_time(tmp_path):
    first = run_pipeline.PipelineLock(tmp_path / "p.lock")
    second = run_pipeline.PipelineLock(tmp_path / "p.lock")
    assert first.acquire() is True
    assert second.acquire() is False
    first.release()
    assert second.acquire() is True
    second.release()
    assert not (tmp_path / "p.lock").exists()


def test_stale_lock_is_replaced(tmp_path):
    lock_path = tmp_path / "p.lock"
    lock_path.write_text("12345")
    old = time.time() - 3 * 60 * 60                      # 3 hours old
    os.utime(lock_path, (old, old))
    lock = run_pipeline.PipelineLock(lock_path)
    assert lock.acquire() is True
    lock.release()


def test_lock_released_after_with_block(tmp_path):
    lock = run_pipeline.PipelineLock(tmp_path / "p.lock")
    with lock as got_it:
        assert got_it
        assert (tmp_path / "p.lock").exists()
    assert not (tmp_path / "p.lock").exists()


# --- main(): exit codes -------------------------------------------------------------
@pytest.fixture
def no_logging_setup(monkeypatch):
    monkeypatch.setattr(run_pipeline, "setup_logging", lambda: None)


def test_main_skips_when_another_run_holds_the_lock(tmp_path, monkeypatch, no_logging_setup):
    ran = []
    monkeypatch.setattr(run_pipeline, "run", lambda: ran.append(1) or {})
    holder = run_pipeline.PipelineLock(tmp_path / "p.lock")
    holder.acquire()
    try:
        code = run_pipeline.main([], lock=run_pipeline.PipelineLock(tmp_path / "p.lock"))
    finally:
        holder.release()
    assert code == 2
    assert ran == []


def test_main_success_and_releases_lock(tmp_path, monkeypatch, no_logging_setup):
    monkeypatch.setattr(run_pipeline, "run", lambda: {"ingested_new": 0})
    code = run_pipeline.main([], lock=run_pipeline.PipelineLock(tmp_path / "p.lock"))
    assert code == 0
    assert not (tmp_path / "p.lock").exists()


def test_main_error_returns_1_and_releases_lock(tmp_path, monkeypatch, no_logging_setup):
    def broken_run():
        raise RuntimeError("database down")
    monkeypatch.setattr(run_pipeline, "run", broken_run)
    code = run_pipeline.main([], lock=run_pipeline.PipelineLock(tmp_path / "p.lock"))
    assert code == 1
    assert not (tmp_path / "p.lock").exists()


def test_setup_logging_writes_log_file(tmp_path):
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        run_pipeline.setup_logging(tmp_path / "logs" / "pipeline.log")
        logging.getLogger("test").info("Pipeline summary: {'ingested_new': 1}")
        for handler in root.handlers:
            handler.flush()
        assert "Pipeline summary" in (tmp_path / "logs" / "pipeline.log").read_text(encoding="utf-8")
    finally:
        for handler in root.handlers:
            handler.close()
        root.handlers = saved_handlers
        root.setLevel(saved_level)


# --- crash handling -----------------------------------------------------------------------
def test_inbox_file_that_crashes_goes_to_failed(db_conn, tmp_path, monkeypatch):
    inbox, failed = tmp_path / "inbox", tmp_path / "failed"
    inbox.mkdir()
    (inbox / "a.jpg").write_bytes(image_bytes())
    os.utime(inbox / "a.jpg", (0, 0))

    def crash(*args, **kwargs):
        raise OSError("disk problem")
    monkeypatch.setattr(ingest, "ingest_image_bytes", crash)

    counts = ingest.scan_inbox(conn=db_conn, inbox_dir=inbox, raw_dir=tmp_path / "raw", failed_dir=failed)
    assert counts["crashed"] == 1
    assert not (inbox / "a.jpg").exists()
    assert len(list(failed.iterdir())) == 1


def test_cleaning_crash_marks_file_failed_and_continues(db_conn, tmp_path, monkeypatch):
    status, file_id = ingest.ingest_image_bytes(image_bytes(), "a.jpg", "upload",
                                                conn=db_conn, raw_dir=tmp_path)
    db_conn.execute("INSERT INTO raw.ocr_run (file_id, method, raw_text) VALUES (%s, 'tesseract', 'x')",
                    (file_id,))
    db_conn.execute("UPDATE raw.receipt_file SET status = 'ocr_done' WHERE file_id = %s", (file_id,))

    def crash(*args, **kwargs):
        raise ValueError("parser bug")
    monkeypatch.setattr(clean, "process_file", crash)

    assert clean.process_pending(db_conn) == []
    status = db_conn.execute("SELECT status FROM raw.receipt_file WHERE file_id = %s",
                             (file_id,)).fetchone()[0]
    assert status == "failed"
