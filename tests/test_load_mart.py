"""Tests for src/load_mart.py and the example analytics queries."""

from datetime import date
from decimal import Decimal as D

import pytest

from src import config, db, load_mart, review
from tests.test_quality import insert_receipt

QUERY_FILES = sorted((config.SQL_DIR / "queries").glob("*.sql"))


def approve(conn, receipt_id):
    review.set_review_status(conn, receipt_id, "approved")


def fact_sum(conn):
    return conn.execute("SELECT COALESCE(sum(line_total), 0) FROM mart.fact_purchase_line").fetchone()[0]


def approved_lines_sum(conn):
    return conn.execute(
        """
        SELECT COALESCE(sum(l.line_total), 0)
        FROM clean.receipt_line l JOIN clean.receipt r USING (receipt_id)
        WHERE r.review_status = 'approved'
        """
    ).fetchone()[0]


@pytest.fixture
def approved_data(db_conn):
    approve(db_conn, insert_receipt(db_conn, 1, number="A-1"))
    approve(db_conn, insert_receipt(db_conn, 2, number="A-2"))
    insert_receipt(db_conn, 3, number="A-3")              # pending: must not reach the mart
    rejected = insert_receipt(db_conn, 4, number="A-4")
    review.set_review_status(db_conn, rejected, "rejected")
    return db_conn


def test_running_twice_gives_same_counts(approved_data):
    first = load_mart.build_mart(approved_data)
    second = load_mart.build_mart(approved_data)
    assert first == second
    assert first["fact_purchase_line"] == 4                # 2 approved receipts x 2 lines


def test_reconciliation_fact_total_equals_approved_lines(approved_data):
    load_mart.build_mart(approved_data)
    assert fact_sum(approved_data) == approved_lines_sum(approved_data) == D("60.00")


def test_correction_after_approval_fixes_facts(approved_data):
    load_mart.build_mart(approved_data)
    approved_data.execute(
        "UPDATE clean.receipt_line SET line_total = 25.00 WHERE receipt_id = 1 AND line_no = 2"
    )
    load_mart.build_mart(approved_data)
    assert fact_sum(approved_data) == D("65.00")
    assert fact_sum(approved_data) == approved_lines_sum(approved_data)


def test_unapproving_removes_facts(approved_data):
    load_mart.build_mart(approved_data)
    review.set_review_status(approved_data, 1, "rejected")
    counts = load_mart.build_mart(approved_data)
    assert counts["fact_purchase_line"] == 2


def test_dimensions_and_lineage(approved_data):
    load_mart.build_mart(approved_data)
    row = approved_data.execute(
        """
        SELECT v.vendor_name, i.item_name, d.full_date, d.month_name, d.day_of_week, l.description
        FROM mart.fact_purchase_line f
        JOIN mart.dim_vendor v USING (vendor_key)
        JOIN mart.dim_item i USING (item_key)
        JOIN mart.dim_date d USING (date_key)
        JOIN clean.receipt_line l ON l.line_id = f.line_id
        ORDER BY f.line_id LIMIT 1
        """
    ).fetchone()
    assert row == ("Harbor Fresh Foods", "UNMAPPED", date(2026, 6, 7), "June", "Sunday", "A")


def test_receipt_without_date_uses_unknown_date(db_conn):
    receipt_id = insert_receipt(db_conn, 1)
    db_conn.execute("UPDATE clean.receipt SET receipt_date = NULL WHERE receipt_id = %s", (receipt_id,))
    approve(db_conn, receipt_id)
    load_mart.build_mart(db_conn)
    keys = {r[0] for r in db_conn.execute("SELECT date_key FROM mart.fact_purchase_line").fetchall()}
    assert keys == {0}


def test_readonly_role_can_read_mart(approved_data):
    load_mart.build_mart(approved_data)
    with db.get_connection(readonly=True) as ro:
        assert ro.execute("SELECT count(*) FROM mart.fact_purchase_line").fetchone()[0] == 4


def test_there_are_five_example_queries():
    assert len(QUERY_FILES) == 5


@pytest.mark.parametrize("path", QUERY_FILES, ids=lambda p: p.stem)
def test_example_query_runs(approved_data, path):
    load_mart.build_mart(approved_data)
    rows = approved_data.execute(path.read_text(encoding="utf-8")).fetchall()
    assert len(rows) >= 1
