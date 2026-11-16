"""Tests for src/ocr.py. These call the real Tesseract (installed locally)."""

from src import config, ingest, ocr

SAMPLE_IMAGE = config.SAMPLE_DIR / "receipt_003.png"


def test_run_tesseract_reads_sample_receipt():
    result = ocr.run_tesseract(SAMPLE_IMAGE)
    assert "INVOICE" in result["text"]
    assert "TOTAL" in result["text"]
    assert result["duration_ms"] > 0


def _ingest_sample(conn, raw_dir):
    status, file_id = ingest.ingest_image_bytes(
        SAMPLE_IMAGE.read_bytes(), SAMPLE_IMAGE.name, "inbox", conn=conn, raw_dir=raw_dir
    )
    assert status == "new"
    return file_id


def test_ocr_file_stores_run_and_updates_status(db_conn, tmp_path):
    file_id = _ingest_sample(db_conn, tmp_path)
    ocr_run_id = ocr.ocr_file(db_conn, file_id)

    method, text, error = db_conn.execute(
        "SELECT method, raw_text, error FROM raw.ocr_run WHERE ocr_run_id = %s", (ocr_run_id,)
    ).fetchone()
    status = db_conn.execute(
        "SELECT status FROM raw.receipt_file WHERE file_id = %s", (file_id,)
    ).fetchone()[0]
    assert method == "tesseract"
    assert "INVOICE" in text
    assert error is None
    assert status == "ocr_done"


def test_missing_image_marks_file_failed(db_conn, tmp_path):
    file_id = _ingest_sample(db_conn, tmp_path)
    for stored in tmp_path.iterdir():
        stored.unlink()                      # the stored copy disappears

    ocr_run_id = ocr.ocr_file(db_conn, file_id)
    error = db_conn.execute(
        "SELECT error FROM raw.ocr_run WHERE ocr_run_id = %s", (ocr_run_id,)
    ).fetchone()[0]
    status = db_conn.execute(
        "SELECT status FROM raw.receipt_file WHERE file_id = %s", (file_id,)
    ).fetchone()[0]
    assert error == "FileNotFoundError"      # only the error type is stored
    assert status == "failed"


def test_ocr_pending_only_processes_new_files(db_conn, tmp_path):
    _ingest_sample(db_conn, tmp_path)
    assert ocr.ocr_pending(db_conn) == 1
    assert ocr.ocr_pending(db_conn) == 0     # second run: nothing new
