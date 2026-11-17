"""Tests for src/ingest.py (uses the receipts_test database)."""

import os
import time

import pytest

from src import ingest
from tests.helpers import image_bytes


def count_files(conn):
    return conn.execute("SELECT count(*) FROM raw.receipt_file").fetchone()[0]


def test_new_then_duplicate(db_conn, tmp_path):
    data = image_bytes("JPEG")
    first = ingest.ingest_image_bytes(data, "r.jpg", "upload", conn=db_conn, raw_dir=tmp_path)
    second = ingest.ingest_image_bytes(data, "other.jpg", "inbox", conn=db_conn, raw_dir=tmp_path)
    assert first[0] == "new"
    assert second == ("duplicate", first[1])
    assert count_files(db_conn) == 1


def test_file_saved_under_hash_name(db_conn, tmp_path):
    status, file_id = ingest.ingest_image_bytes(
        image_bytes("PNG"), "../../evil.png", "camera", conn=db_conn, raw_dir=tmp_path
    )
    sha, path, name, source = db_conn.execute(
        "SELECT sha256, stored_path, original_name, source FROM raw.receipt_file WHERE file_id = %s",
        (file_id,),
    ).fetchone()
    assert (tmp_path / f"{sha}.png").exists()
    assert path.endswith(f"{sha}.png")
    assert name == "evil.png"           # only the base name is kept, as a label
    assert source == "camera"


def test_real_format_decides_extension(db_conn, tmp_path):
    # JPEG bytes with a .png name: accepted, but saved as .jpg
    status, _ = ingest.ingest_image_bytes(image_bytes("JPEG"), "x.png", "upload", conn=db_conn, raw_dir=tmp_path)
    assert status == "new"
    assert len(list(tmp_path.glob("*.jpg"))) == 1


def test_non_image_file_rejected(db_conn, tmp_path):
    result = ingest.ingest_image_bytes(b"hello, not an image", "notes.jpg", "upload", conn=db_conn, raw_dir=tmp_path)
    assert result == ("rejected", "not a valid image")
    assert count_files(db_conn) == 0


def test_corrupted_png_rejected(db_conn, tmp_path):
    data = bytearray(image_bytes("PNG"))
    data[60:80] = b"\x00" * 20                  # damage the image data
    result = ingest.ingest_image_bytes(bytes(data), "broken.png", "upload", conn=db_conn, raw_dir=tmp_path)
    assert result[0] == "rejected"


def test_wrong_extension_rejected(db_conn, tmp_path):
    result = ingest.ingest_image_bytes(image_bytes("JPEG"), "photo.gif", "upload", conn=db_conn, raw_dir=tmp_path)
    assert result == ("rejected", "not a JPG or PNG file")


def test_gif_content_rejected(db_conn, tmp_path):
    result = ingest.ingest_image_bytes(image_bytes("GIF"), "photo.png", "upload", conn=db_conn, raw_dir=tmp_path)
    assert result == ("rejected", "not a JPG or PNG file")


def test_oversized_file_rejected(db_conn, tmp_path):
    data = b"x" * (ingest.MAX_BYTES + 1)
    result = ingest.ingest_image_bytes(data, "big.jpg", "upload", conn=db_conn, raw_dir=tmp_path)
    assert result == ("rejected", "over 10 MB")


def test_empty_file_rejected(db_conn, tmp_path):
    assert ingest.ingest_image_bytes(b"", "e.jpg", "upload", conn=db_conn, raw_dir=tmp_path) == ("rejected", "empty file")


def test_too_many_pixels_rejected(db_conn, tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "MAX_PIXELS", 100)
    result = ingest.ingest_image_bytes(image_bytes("PNG"), "big.png", "upload", conn=db_conn, raw_dir=tmp_path)
    assert result == ("rejected", "image has too many pixels")


def test_unknown_source_raises(db_conn, tmp_path):
    with pytest.raises(ValueError):
        ingest.ingest_image_bytes(image_bytes(), "r.jpg", "email", conn=db_conn, raw_dir=tmp_path)


def _make_old(path):
    """Pretend the file was copied a minute ago."""
    old = time.time() - 60
    os.utime(path, (old, old))


def test_scan_inbox_twice_inserts_each_file_once(db_conn, tmp_path):
    inbox, raw, failed = tmp_path / "inbox", tmp_path / "raw", tmp_path / "failed"
    inbox.mkdir()
    (inbox / "a.jpg").write_bytes(image_bytes("JPEG", color=(1, 2, 3)))
    (inbox / "b.png").write_bytes(image_bytes("PNG", color=(4, 5, 6)))
    (inbox / "readme.txt").write_text("not a receipt")
    for path in inbox.iterdir():
        _make_old(path)

    first = ingest.scan_inbox(conn=db_conn, inbox_dir=inbox, raw_dir=raw, failed_dir=failed)
    second = ingest.scan_inbox(conn=db_conn, inbox_dir=inbox, raw_dir=raw, failed_dir=failed)

    assert first == {"new": 2, "duplicate": 0, "rejected": 1, "skipped": 0, "crashed": 0}
    assert second == {"new": 0, "duplicate": 0, "rejected": 0, "skipped": 0, "crashed": 0}
    assert count_files(db_conn) == 2
    assert len(list(failed.iterdir())) == 1        # the .txt file


def test_scan_inbox_same_file_dropped_again_is_duplicate(db_conn, tmp_path):
    inbox, raw = tmp_path / "inbox", tmp_path / "raw"
    inbox.mkdir()
    data = image_bytes("JPEG")
    (inbox / "a.jpg").write_bytes(data)
    _make_old(inbox / "a.jpg")
    ingest.scan_inbox(conn=db_conn, inbox_dir=inbox, raw_dir=raw, failed_dir=tmp_path / "f")

    (inbox / "a_copy.jpg").write_bytes(data)       # staff drop the same photo again
    _make_old(inbox / "a_copy.jpg")
    counts = ingest.scan_inbox(conn=db_conn, inbox_dir=inbox, raw_dir=raw, failed_dir=tmp_path / "f")
    assert counts["duplicate"] == 1
    assert count_files(db_conn) == 1


def test_scan_inbox_skips_files_still_copying(db_conn, tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "new.jpg").write_bytes(image_bytes())  # modified just now
    counts = ingest.scan_inbox(conn=db_conn, inbox_dir=inbox, raw_dir=tmp_path / "raw", failed_dir=tmp_path / "f")
    assert counts["skipped"] == 1
    assert (inbox / "new.jpg").exists()
