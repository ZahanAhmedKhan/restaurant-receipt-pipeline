"""Tests for src/quality.py."""

from datetime import date
from decimal import Decimal as D

import pandas as pd

from src import clean, quality


def good_receipt():
    receipt = {"receipt_id": 1, "vendor_name": "Harbor Fresh Foods", "receipt_date_raw": "06/07/2026",
               "receipt_date": date(2026, 6, 7), "receipt_number": "HF-1", "subtotal": D("30.00"),
               "tax": D("0.00"), "total": D("30.00"), "review_status": "pending"}
    lines = [
        {"line_no": 1, "description": "A", "quantity": D("1"), "unit_price": D("10.00"), "line_total": D("10.00")},
        {"line_no": 2, "description": "B", "quantity": D("2"), "unit_price": D("10.00"), "line_total": D("20.00")},
    ]
    return receipt, lines


def test_good_receipt_passes_all_simple_checks():
    receipt, lines = good_receipt()
    for name, check in quality.SIMPLE_CHECKS.items():
        passed, details = check(receipt, lines)
        assert passed, f"{name}: {details}"


def test_missing_fields():
    receipt, lines = good_receipt()
    receipt["receipt_number"] = None
    lines[1]["quantity"] = None
    passed, details = quality.check_required_fields(receipt, lines)
    assert not passed
    assert "receipt_number" in details
    assert "line(s) 2" in details


def test_no_lines_is_missing_field():
    receipt, _ = good_receipt()
    assert quality.check_required_fields(receipt, [])[0] is False


def test_future_and_unreadable_dates():
    receipt, lines = good_receipt()
    receipt["receipt_date"] = date(2030, 1, 1)
    assert quality.check_valid_date(receipt, lines, today=date(2026, 11, 16))[0] is False
    receipt["receipt_date"] = None
    passed, details = quality.check_valid_date(receipt, lines)
    assert not passed and details == "date could not be read"


def test_negative_values():
    receipt, lines = good_receipt()
    lines[0]["line_total"] = D("-10.00")
    passed, details = quality.check_no_negative_values(receipt, lines)
    assert not passed and "line 1 line_total" in details


def test_lines_not_adding_up():
    receipt, lines = good_receipt()
    receipt["subtotal"] = D("25.00")
    assert quality.check_lines_match_subtotal(receipt, lines)[0] is False


def test_lines_within_tolerance_pass():
    receipt, lines = good_receipt()
    receipt["subtotal"] = D("30.01")
    assert quality.check_lines_match_subtotal(receipt, lines)[0] is True


def test_unreadable_line_amount_fails_subtotal_check():
    receipt, lines = good_receipt()
    lines[0]["line_total"] = None
    assert quality.check_lines_match_subtotal(receipt, lines)[0] is False


def test_wrong_total():
    receipt, lines = good_receipt()
    receipt["total"] = D("40.00")
    passed, details = quality.check_total_is_subtotal_plus_tax(receipt, lines)
    assert not passed and "40.00" in details


# --- database tests ----------------------------------------------------------
def insert_receipt(conn, file_number, total="30.00", number="HF-1"):
    """Insert a file + clean receipt directly (no OCR) and return receipt_id."""
    file_id = conn.execute(
        "INSERT INTO raw.receipt_file (sha256, stored_path, source) VALUES (%s, 'x', 'upload') "
        "RETURNING file_id",
        (f"{file_number:064d}",),
    ).fetchone()[0]
    header = {"vendor_raw": "HARBOR FRESH FOODS", "vendor_name": "Harbor Fresh Foods",
              "receipt_date_raw": "06/07/2026", "receipt_date": date(2026, 6, 7),
              "receipt_number": number, "subtotal": D("30.00"), "tax": D("0.00"), "total": D(total)}
    lines = pd.DataFrame({
        "line_no": [1, 2], "description_raw": ["A", "B"], "description": ["A", "B"],
        "quantity": [D("1"), D("2")], "unit_raw": ["CS", "CS"],
        "unit_price": [D("10.00"), D("10.00")], "line_total": [D("10.00"), D("20.00")],
    }, dtype=object)
    return clean.insert_receipt(conn, file_id, None, header, lines)


def status_of(conn, receipt_id):
    return conn.execute(
        "SELECT review_status FROM clean.receipt WHERE receipt_id = %s", (receipt_id,)
    ).fetchone()[0]


def test_all_pass_stays_pending_and_results_saved(db_conn):
    receipt_id = insert_receipt(db_conn, 1)
    results = quality.run_checks(db_conn, receipt_id)
    assert all(passed for passed, _ in results.values())
    assert status_of(db_conn, receipt_id) == "pending"
    count = db_conn.execute("SELECT count(*) FROM dq.check_result WHERE receipt_id = %s",
                            (receipt_id,)).fetchone()[0]
    assert count == 6


def test_failure_sets_needs_review_and_keeps_data(db_conn):
    receipt_id = insert_receipt(db_conn, 1, total="99.00")
    results = quality.run_checks(db_conn, receipt_id)
    assert results["total_is_subtotal_plus_tax"][0] is False
    assert status_of(db_conn, receipt_id) == "needs_review"
    assert db_conn.execute("SELECT count(*) FROM clean.receipt").fetchone()[0] == 1


def test_duplicate_receipt_flags_the_later_one(db_conn):
    first = insert_receipt(db_conn, 1)
    second = insert_receipt(db_conn, 2)       # same vendor, number and total
    assert quality.run_checks(db_conn, first)["not_duplicate"][0] is True
    passed, details = quality.run_checks(db_conn, second)["not_duplicate"]
    assert not passed
    assert details == f"same as receipt #{first}"


def test_rerun_replaces_results(db_conn):
    receipt_id = insert_receipt(db_conn, 1)
    quality.run_checks(db_conn, receipt_id)
    quality.run_checks(db_conn, receipt_id)
    count = db_conn.execute("SELECT count(*) FROM dq.check_result").fetchone()[0]
    assert count == 6


def test_approved_receipt_status_not_changed(db_conn):
    receipt_id = insert_receipt(db_conn, 1, total="99.00")
    db_conn.execute("UPDATE clean.receipt SET review_status = 'approved' WHERE receipt_id = %s",
                    (receipt_id,))
    quality.run_checks(db_conn, receipt_id)
    assert status_of(db_conn, receipt_id) == "approved"
