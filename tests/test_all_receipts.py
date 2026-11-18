"""Tests for the All receipts list (review.all_receipts) and its page."""

from datetime import date

from streamlit.testing.v1 import AppTest

from src import config, review
from tests.helpers import make_approved_receipt
from tests.test_quality import insert_receipt


def setup_receipts(conn):
    make_approved_receipt(conn, 1, "Harbor Fresh Foods", date(2026, 6, 5), [("CHKN BRST 10LB", 2, "CS", "30.00")])
    make_approved_receipt(conn, 2, "Sunrise Meat Co.", date(2026, 7, 6), [("GOAT CUBES", 10, "LB", "6.25")])
    insert_receipt(conn, 3, number="P-1")              # pending, Harbor Fresh Foods, 2 lines


def test_lists_every_receipt_newest_first(db_conn):
    setup_receipts(db_conn)
    rows = review.all_receipts(db_conn)
    assert len(rows) == 3
    assert rows[0]["receipt_date"] == date(2026, 7, 6)
    assert {r["review_status"] for r in rows} == {"approved", "pending"}


def test_filters(db_conn):
    setup_receipts(db_conn)
    assert len(review.all_receipts(db_conn, status="approved")) == 2
    assert len(review.all_receipts(db_conn, vendor="Sunrise Meat Co.")) == 1
    assert [r["receipt_number"] for r in review.all_receipts(db_conn, search="p-1")] == ["P-1"]
    goat = review.all_receipts(db_conn, search="goat")            # item description
    assert [r["vendor_name"] for r in goat] == ["Sunrise Meat Co."]
    assert goat[0]["items"] == 1


def test_vendor_names(db_conn):
    setup_receipts(db_conn)
    assert review.vendor_names(db_conn) == ["Harbor Fresh Foods", "Sunrise Meat Co."]


def test_page_renders_for_staff(db_conn):
    setup_receipts(db_conn)
    app = AppTest.from_file(str(config.PROJECT_ROOT / "app" / "pages" / "All_Receipts.py"))
    app.session_state["role"] = "staff"
    app.run()
    assert not app.exception
    assert "3 receipt(s)" in app.caption[0].value
    assert len(app.dataframe) == 2                      # the list + the opened receipt's items
