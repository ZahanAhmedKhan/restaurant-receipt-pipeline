"""Tests for the 'Canadian receipts only' rule (src/country.py + the quality check)."""

import json

import pytest

from src import config, country, quality, review
from src.run_pipeline import process_single_image

CANADIAN_COSTCO = """COSTCO WHOLESALE
#535 Mississauga
5995 Mavis Rd
Mississauga ON L5R 3T7
GST/HST # 121476329 RT0001
SUBTOTAL 45.97
HST 13% 1.30
TOTAL 47.27"""

AUSTRALIAN_COSTCO = """COSTCO WHOLESALE AUSTRALIA
Auburn NSW 2144
ABN 57 104 012 893
SUBTOTAL 45.97
GST 4.18
TOTAL 50.15"""

US_COSTCO = """COSTCO WHOLESALE
Issaquah WA 98027
SUBTOTAL 45.97
SALES TAX 4.60
TOTAL 50.57"""

QUEBEC = "Marché Central\nMontréal QC H4N 1J9\nTPS 2.30\nTVQ 4.59\nTOTAL 52.89"
NO_SIGNS = "SOME SHOP\nSUBTOTAL 10.00\nGST 1.00\nTOTAL 11.00"


@pytest.mark.parametrize("text, expected", [
    (CANADIAN_COSTCO, "CA"),
    (QUEBEC, "CA"),
    (AUSTRALIAN_COSTCO, "AU"),
    (US_COSTCO, "US"),
    (NO_SIGNS, None),                       # plain GST is used in Australia too
])
def test_detect_country(text, expected):
    assert country.detect_country(text)[0] == expected


def test_mixed_signs_are_not_decided():
    detected, signs = country.detect_country(CANADIAN_COSTCO + "\nABN 57 104 012 893")
    assert detected is None
    assert set(signs) == {"CA", "AU"}


def test_check_country_results():
    assert quality.check_country(CANADIAN_COSTCO, "CA") == (True, None, False)
    passed, details, foreign = quality.check_country(AUSTRALIAN_COSTCO, "CA")
    assert (passed, foreign) == (False, True)
    assert details.startswith("looks Australian: ")
    passed, details, foreign = quality.check_country(NO_SIGNS, "CA")
    assert (passed, foreign) == (False, False)
    assert details == "no Canadian address, postal code or tax number found"


def test_friendly_message():
    assert review.friendly_problem("from_allowed_country", "no Canadian address, postal code or tax number found") \
        == "Can't confirm this receipt is from Canada (no Canadian address, postal code or tax number found)."


# --- through the database ----------------------------------------------------------
def receipt_with_text(conn, number, text):
    """A receipt whose OCR run has the given text."""
    from tests.test_quality import insert_receipt
    receipt_id = insert_receipt(conn, number)
    file_id = conn.execute("SELECT file_id FROM clean.receipt WHERE receipt_id = %s",
                           (receipt_id,)).fetchone()[0]
    ocr_run_id = conn.execute(
        "INSERT INTO raw.ocr_run (file_id, method, raw_text) VALUES (%s, 'tesseract', %s) "
        "RETURNING ocr_run_id", (file_id, text)).fetchone()[0]
    conn.execute("UPDATE clean.receipt SET ocr_run_id = %s WHERE receipt_id = %s",
                 (ocr_run_id, receipt_id))
    return receipt_id


def status_of(conn, receipt_id):
    return conn.execute("SELECT review_status FROM clean.receipt WHERE receipt_id = %s",
                        (receipt_id,)).fetchone()[0]


@pytest.fixture
def canada_only(monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_COUNTRY", "CA")


def test_canadian_receipt_passes(db_conn, canada_only):
    receipt_id = receipt_with_text(db_conn, 1, CANADIAN_COSTCO)
    results = quality.run_checks(db_conn, receipt_id)
    assert results["from_allowed_country"] == (True, None)
    assert status_of(db_conn, receipt_id) == "pending"


def test_foreign_receipt_rejected_automatically_and_logged(db_conn, canada_only):
    receipt_id = receipt_with_text(db_conn, 1, AUSTRALIAN_COSTCO)
    quality.run_checks(db_conn, receipt_id)
    assert status_of(db_conn, receipt_id) == "rejected"
    field, old, new = db_conn.execute(
        "SELECT field_name, old_value, new_value FROM clean.correction WHERE receipt_id = %s",
        (receipt_id,)).fetchone()
    assert (field, old) == ("review_status", "pending")
    assert new.startswith("rejected (automatic: looks Australian")
    # Kept, not deleted
    assert db_conn.execute("SELECT count(*) FROM clean.receipt").fetchone()[0] == 1


def test_receipt_without_signs_goes_to_review(db_conn, canada_only):
    receipt_id = receipt_with_text(db_conn, 1, NO_SIGNS)
    quality.run_checks(db_conn, receipt_id)
    assert status_of(db_conn, receipt_id) == "needs_review"


def test_approved_receipt_is_not_auto_rejected(db_conn, canada_only):
    receipt_id = receipt_with_text(db_conn, 1, AUSTRALIAN_COSTCO)
    db_conn.execute("UPDATE clean.receipt SET review_status = 'approved' WHERE receipt_id = %s",
                    (receipt_id,))
    quality.run_checks(db_conn, receipt_id)
    assert status_of(db_conn, receipt_id) == "approved"


def test_check_can_be_switched_off(db_conn):
    receipt_id = receipt_with_text(db_conn, 1, AUSTRALIAN_COSTCO)   # ALLOWED_COUNTRY is "" here
    assert "from_allowed_country" not in quality.run_checks(db_conn, receipt_id)


def test_sample_australian_receipt_rejected_on_upload(db_conn, canada_only, tmp_path):
    truth = next(json.loads(p.read_text()) for p in config.SAMPLE_DIR.glob("receipt_*.json")
                 if "not_canadian" in json.loads(p.read_text())["deliberate_errors"])
    data = (config.SAMPLE_DIR / truth["file"]).read_bytes()
    result = process_single_image(db_conn, data, truth["file"], "upload", raw_dir=tmp_path)
    assert result["status"] == "wrong_country"
    assert "Australian" in result["reason"]


def test_sample_canadian_receipt_accepted_on_upload(db_conn, canada_only, tmp_path):
    data = (config.SAMPLE_DIR / "receipt_003.png").read_bytes()
    result = process_single_image(db_conn, data, "receipt_003.png", "upload", raw_dir=tmp_path)
    assert result["status"] == "new"
    checks = quality.run_checks(db_conn, result["receipt_id"])
    assert checks["from_allowed_country"] == (True, None)
