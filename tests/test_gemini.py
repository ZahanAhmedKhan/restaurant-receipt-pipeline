"""Tests for the optional Gemini extraction. The real API is never called:
_call_gemini is replaced with a fake that returns fixed JSON."""

import json

import pytest

from src import clean, config, ingest, ocr
from tests.helpers import image_bytes

SAMPLE_IMAGE = config.SAMPLE_DIR / "receipt_003.png"

FAKE_ANSWER = json.dumps({
    "vendor": "HARBOR FRESH FOODS",
    "date": "06/07/2026",
    "receipt_number": "HF-10210",
    "lines": [
        {"description": "OIL CANOLA 35LB", "quantity": "5", "unit": "JUG",
         "unit_price": "$41.20", "line_total": "206.00"},
        {"description": "CHKN BRST 10LB", "quantity": 1, "unit": "CS",
         "unit_price": "32.50", "line_total": "32.50"},
    ],
    "subtotal": "238.50", "tax": "0.00", "total": "238.50",
    "extra_key": "ignored",
})


@pytest.fixture
def fake_gemini(monkeypatch):
    """Pretend Gemini is configured and answers with FAKE_ANSWER. Records calls."""
    calls = []

    def fake_call(image_bytes_, mime_type):
        calls.append(mime_type)
        return FAKE_ANSWER

    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(config, "ALLOW_EXTERNAL_AI_ON_PRIVATE", False)
    monkeypatch.setattr(ocr, "_call_gemini", fake_call)
    return calls


def test_run_gemini_normalizes_answer(fake_gemini):
    result = ocr.run_gemini(SAMPLE_IMAGE)
    data = result["json"]
    assert fake_gemini == ["image/png"]
    assert data["vendor"] == "HARBOR FRESH FOODS"
    assert "extra_key" not in data
    assert data["lines"][0]["unit_price"] == "41.20"      # $ removed
    assert data["lines"][1]["quantity"] == "1"            # number -> text, like parse.py


def test_run_gemini_needs_api_key(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", None)
    with pytest.raises(RuntimeError):
        ocr.run_gemini(SAMPLE_IMAGE)


def test_real_receipt_is_refused_without_permission(fake_gemini, tmp_path):
    real = tmp_path / "real_receipt.jpg"
    real.write_bytes(image_bytes("JPEG"))              # not one of the sample images
    with pytest.raises(ocr.PrivateDataError):
        ocr.run_gemini(real)
    assert fake_gemini == []                           # nothing was sent


def test_real_receipt_allowed_when_owner_says_so(fake_gemini, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ALLOW_EXTERNAL_AI_ON_PRIVATE", True)
    real = tmp_path / "real_receipt.jpg"
    real.write_bytes(image_bytes("JPEG"))
    ocr.run_gemini(real)
    assert fake_gemini == ["image/jpeg"]


def test_sample_copy_in_raw_folder_is_allowed(fake_gemini, tmp_path):
    copy = tmp_path / "abc123.png"                      # sample image stored under a hash name
    copy.write_bytes(SAMPLE_IMAGE.read_bytes())
    ocr.run_gemini(copy)
    assert len(fake_gemini) == 1


def test_pipeline_uses_gemini_json_when_enabled(fake_gemini, monkeypatch, db_conn, tmp_path):
    monkeypatch.setattr(config, "OCR_METHOD", "gemini")
    _, file_id = ingest.ingest_image_bytes(SAMPLE_IMAGE.read_bytes(), "r.png", "upload",
                                           conn=db_conn, raw_dir=tmp_path)
    ocr_run_id = ocr.ocr_file(db_conn, file_id)
    method, raw_text, raw_json = db_conn.execute(
        "SELECT method, raw_text, raw_json FROM raw.ocr_run WHERE ocr_run_id = %s", (ocr_run_id,)
    ).fetchone()
    assert method == "gemini"
    assert raw_text is None
    assert raw_json["receipt_number"] == "HF-10210"

    receipt_id = clean.process_file(db_conn, file_id)
    total, lines = db_conn.execute(
        "SELECT total, (SELECT count(*) FROM clean.receipt_line WHERE receipt_id = r.receipt_id) "
        "FROM clean.receipt r WHERE receipt_id = %s", (receipt_id,)
    ).fetchone()
    assert str(total) == "238.50"
    assert lines == 2


def test_private_file_falls_back_to_tesseract(fake_gemini, monkeypatch, db_conn, tmp_path):
    monkeypatch.setattr(config, "OCR_METHOD", "gemini")
    _, file_id = ingest.ingest_image_bytes(image_bytes("JPEG"), "real.jpg", "camera",
                                           conn=db_conn, raw_dir=tmp_path)
    ocr_run_id = ocr.ocr_file(db_conn, file_id)
    method = db_conn.execute("SELECT method FROM raw.ocr_run WHERE ocr_run_id = %s",
                             (ocr_run_id,)).fetchone()[0]
    assert method == "tesseract"
    assert fake_gemini == []


def test_tesseract_used_when_gemini_not_configured(monkeypatch):
    monkeypatch.setattr(config, "OCR_METHOD", "gemini")
    monkeypatch.setattr(config, "GEMINI_API_KEY", None)
    assert ocr.gemini_enabled() is False
