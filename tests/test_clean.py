"""Tests for src/clean.py and src/run_pipeline.py."""

import os
from datetime import date
from decimal import Decimal

from src import clean, config, run_pipeline

VENDOR_MAP = {"HARBOR FRESH FOODS": "Harbor Fresh Foods", "SUNRISE MEAT CO.": "Sunrise Meat Co."}

PARSED = {
    "vendor": "  harbor   fresh foods ",
    "date": "Jul 12, 2026",
    "receipt_number": "hf-10210",
    "lines": [
        {"description": " chkn  brst 10LB", "quantity": "2", "unit": "cs",
         "unit_price": "32.50", "line_total": "65.00"},
        {"description": "BEEF BRISKET", "quantity": None, "unit": "LB",
         "unit_price": None, "line_total": "58.51"},
    ],
    "subtotal": "123.51",
    "tax": "0.00",
    "total": "123.51",
}


# --- value cleaners -------------------------------------------------------
def test_clean_date_all_vendor_formats():
    assert clean.clean_date("06/14/2026") == date(2026, 6, 14)
    assert clean.clean_date("2026-06-14") == date(2026, 6, 14)
    assert clean.clean_date("Jun 14, 2026") == date(2026, 6, 14)
    assert clean.clean_date("JUN 14 2026") == date(2026, 6, 14)
    assert clean.clean_date("06/14/26") == date(2026, 6, 14)


def test_clean_date_bad_values():
    assert clean.clean_date("13/45/2026") is None
    assert clean.clean_date("garbage") is None
    assert clean.clean_date(None) is None


def test_clean_money_is_decimal_not_float():
    value = clean.clean_money("32.5")
    assert value == Decimal("32.50")
    assert isinstance(value, Decimal)
    assert clean.clean_money(None) is None
    assert clean.clean_money("abc") is None


def test_clean_text():
    assert clean.clean_text("  chkn   brst ") == "CHKN BRST"
    assert clean.clean_text("   ") is None


def test_vendor_exact_close_and_unknown():
    assert clean.standardize_vendor("harbor fresh foods", VENDOR_MAP) == "Harbor Fresh Foods"
    assert clean.standardize_vendor("HARB0R FRESH FOODS", VENDOR_MAP) == "Harbor Fresh Foods"  # OCR typo
    assert clean.standardize_vendor("NEW FISH MARKET", VENDOR_MAP) == "New Fish Market"
    assert clean.standardize_vendor(None, VENDOR_MAP) is None


def test_clean_receipt_keeps_raw_next_to_clean():
    header, lines = clean.clean_receipt(PARSED, VENDOR_MAP)
    assert header["vendor_raw"] == "  harbor   fresh foods "
    assert header["vendor_name"] == "Harbor Fresh Foods"
    assert header["receipt_date_raw"] == "Jul 12, 2026"
    assert header["receipt_date"] == date(2026, 7, 12)
    assert header["receipt_number"] == "HF-10210"
    assert header["total"] == Decimal("123.51")
    assert list(lines["line_no"]) == [1, 2]
    assert lines.loc[0, "description_raw"] == " chkn  brst 10LB"
    assert lines.loc[0, "description"] == "CHKN BRST 10LB"
    assert lines.loc[0, "unit_raw"] == "CS"
    assert lines.loc[1, "quantity"] is None           # missing stays missing


def test_clean_receipt_with_no_lines():
    header, lines = clean.clean_receipt({"vendor": None, "lines": []}, VENDOR_MAP)
    assert header["vendor_name"] is None
    assert len(lines) == 0


# --- loading and the full pipeline (test database) --------------------------
def _sample_inbox(tmp_path, names):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    for name in names:
        (inbox / name).write_bytes((config.SAMPLE_DIR / name).read_bytes())
    for path in inbox.iterdir():
        os.utime(path, (0, 0))      # make files look old (fully copied)
    return inbox


def _count(conn, table):
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_pipeline_loads_receipts_and_rerun_creates_no_duplicates(db_conn, tmp_path):
    # receipt_050 is a byte-for-byte copy of receipt_007
    inbox = _sample_inbox(tmp_path, ["receipt_003.png", "receipt_007.jpg", "receipt_050.jpg"])
    dirs = dict(inbox_dir=inbox, raw_dir=tmp_path / "raw", failed_dir=tmp_path / "failed")

    first = run_pipeline.run(conn=db_conn, **dirs)
    assert first["ingested_new"] == 2
    assert first["duplicates"] == 1
    assert first["receipts_loaded"] == 2

    # Drop the same file in again and rerun
    (inbox / "receipt_003.png").write_bytes((config.SAMPLE_DIR / "receipt_003.png").read_bytes())
    os.utime(inbox / "receipt_003.png", (0, 0))
    second = run_pipeline.run(conn=db_conn, **dirs)
    assert second["duplicates"] == 1
    assert second["receipts_loaded"] == 0
    assert _count(db_conn, "clean.receipt") == 2
    assert _count(db_conn, "raw.receipt_file") == 2


def test_loaded_receipt_values(db_conn, tmp_path):
    inbox = _sample_inbox(tmp_path, ["receipt_003.png"])
    run_pipeline.run(conn=db_conn, inbox_dir=inbox, raw_dir=tmp_path / "raw",
                     failed_dir=tmp_path / "failed")
    vendor, number, status = db_conn.execute(
        "SELECT vendor_name, receipt_number, review_status FROM clean.receipt"
    ).fetchone()
    assert vendor == "Harbor Fresh Foods"
    assert number == "HF-10210"
    assert status == "pending"
    file_status = db_conn.execute("SELECT status FROM raw.receipt_file").fetchone()[0]
    assert file_status == "parsed"
    assert _count(db_conn, "clean.receipt_line") > 0
