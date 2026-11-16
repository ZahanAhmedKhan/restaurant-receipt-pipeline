"""Tests for src/review.py and the review page."""

from datetime import date
from decimal import Decimal as D

from streamlit.testing.v1 import AppTest

from src import auth, config, review
from tests.test_quality import insert_receipt


def current_lines(conn, receipt_id):
    return review.get_receipt(conn, receipt_id)["lines"]


def header_of(data):
    r = data["receipt"]
    return {f: review.as_text(r[f]) for f in review.HEADER_FIELDS}


def lines_as_typed(lines):
    return [{"line_no": l["line_no"], **{f: review.as_text(l.get(f)) for f in review.LINE_FIELDS}}
            for l in lines]


def corrections(conn, receipt_id):
    return conn.execute(
        "SELECT field_name, old_value, new_value FROM clean.correction "
        "WHERE receipt_id = %s ORDER BY correction_id", (receipt_id,)
    ).fetchall()


def test_as_text_and_values_equal():
    assert review.as_text(D("32.50")) == "32.50"
    assert review.as_text(D("2.000")) == "2"
    assert review.as_text(D("14.620")) == "14.62"
    assert review.as_text(date(2026, 6, 7)) == "2026-06-07"
    assert review.as_text(None) == ""
    assert review.values_equal(D("2"), D("2.000"))
    assert not review.values_equal(D("2"), None)


def test_saving_unchanged_values_logs_nothing(db_conn):
    receipt_id = insert_receipt(db_conn, 1)
    data = review.get_receipt(db_conn, receipt_id)
    changes = review.save_corrections(db_conn, receipt_id, header_of(data), lines_as_typed(data["lines"]))
    assert changes == 0
    assert corrections(db_conn, receipt_id) == []


def test_header_and_line_edits_are_logged(db_conn):
    receipt_id = insert_receipt(db_conn, 1, total="99.00")       # wrong total -> needs_review
    data = review.get_receipt(db_conn, receipt_id)
    header = header_of(data)
    header["total"] = "30.00"
    lines = lines_as_typed(data["lines"])
    lines[1]["quantity"] = "3"
    lines[1]["line_total"] = "30.00"

    changes = review.save_corrections(db_conn, receipt_id, header, lines)
    assert changes == 3
    assert corrections(db_conn, receipt_id) == [
        ("total", "99.00", "30.00"),
        ("line 2 quantity", "2", "3"),
        ("line 2 line_total", "20.00", "30.00"),
    ]
    total = db_conn.execute("SELECT total FROM clean.receipt WHERE receipt_id = %s",
                            (receipt_id,)).fetchone()[0]
    assert total == D("30.00")


def test_fixing_values_reruns_checks(db_conn):
    receipt_id = insert_receipt(db_conn, 1, total="99.00")
    from src import quality
    quality.run_checks(db_conn, receipt_id)
    data = review.get_receipt(db_conn, receipt_id)
    assert data["receipt"]["review_status"] == "needs_review"

    header = header_of(data)
    header["total"] = "30.00"
    review.save_corrections(db_conn, receipt_id, header, lines_as_typed(data["lines"]))
    assert review.get_receipt(db_conn, receipt_id)["receipt"]["review_status"] == "pending"


def test_add_and_delete_lines(db_conn):
    receipt_id = insert_receipt(db_conn, 1)
    data = review.get_receipt(db_conn, receipt_id)
    lines = lines_as_typed(data["lines"])[:1]                   # delete line 2
    lines.append({"line_no": None, "description": "napkins", "quantity": "1",
                  "unit_raw": "cs", "unit_price": "5.00", "line_total": "5.00"})
    lines.append({"line_no": None, "description": "", "quantity": "", "unit_raw": "",
                  "unit_price": "", "line_total": ""})             # empty row is ignored

    changes = review.save_corrections(db_conn, receipt_id, header_of(data), lines)
    assert changes == 2
    after = current_lines(db_conn, receipt_id)
    assert [l["line_no"] for l in after] == [1, 3]
    assert after[1]["description"] == "NAPKINS"
    fields = [c[0] for c in corrections(db_conn, receipt_id)]
    assert fields == ["line 3 added", "line 2 deleted"]


def test_approve_and_reject_are_logged(db_conn):
    receipt_id = insert_receipt(db_conn, 1)
    review.set_review_status(db_conn, receipt_id, "approved")
    review.set_review_status(db_conn, receipt_id, "rejected")
    assert corrections(db_conn, receipt_id) == [
        ("review_status", "pending", "approved"),
        ("review_status", "approved", "rejected"),
    ]


def test_reopen_reruns_checks(db_conn):
    receipt_id = insert_receipt(db_conn, 1, total="99.00")
    review.set_review_status(db_conn, receipt_id, "approved")
    review.set_review_status(db_conn, receipt_id, "pending")
    status = review.get_receipt(db_conn, receipt_id)["receipt"]["review_status"]
    assert status == "needs_review"


def test_review_page_shows_receipt_after_login(monkeypatch, db_conn, tmp_path):
    receipt_id = insert_receipt(db_conn, 1, total="99.00")
    from src import quality
    quality.run_checks(db_conn, receipt_id)

    monkeypatch.setattr(config, "APP_PASSWORD_HASH", auth.hash_password("letmein!", iterations=1000))
    app = AppTest.from_file(str(config.PROJECT_ROOT / "app" / "pages" / "2_Review.py"))
    app.session_state["authenticated"] = True
    app.run()
    assert not app.exception
    assert any("total is 99.00" in e.value for e in app.error)   # failed check shown
    assert len(app.text_input) == 6                               # header fields to edit
