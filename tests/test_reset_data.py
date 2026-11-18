"""Tests for scripts/reset_data.py."""

from scripts import reset_data
from src import config, ingest, ocr, review
from src.run_pipeline import process_single_image
from tests.helpers import image_bytes


def count(conn, table):
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_delete_files_removes_rows_and_images(db_conn, tmp_path):
    sample = process_single_image(db_conn, (config.SAMPLE_DIR / "receipt_003.png").read_bytes(),
                                  "s.png", "upload", raw_dir=tmp_path)
    review.set_review_status(db_conn, sample["receipt_id"], "approved")
    _, other = ingest.ingest_image_bytes(image_bytes(), "mine.jpg", "camera", conn=db_conn, raw_dir=tmp_path)
    assert len(list(tmp_path.iterdir())) == 2

    removed = reset_data.delete_files(db_conn, reset_data.file_ids_with_hashes(db_conn, ocr.sample_hashes()))
    assert removed == 1
    assert count(db_conn, "clean.receipt") == 0
    assert count(db_conn, "clean.correction") == 0
    assert count(db_conn, "raw.ocr_run") == 0
    # The non-sample file is kept
    assert [row[0] for row in db_conn.execute("SELECT file_id FROM raw.receipt_file").fetchall()] == [other]
    assert len(list(tmp_path.iterdir())) == 1


def test_delete_nothing(db_conn):
    assert reset_data.delete_files(db_conn, []) == 0
