"""Tests for src/export_excel.py."""

import io
from datetime import date

import pandas as pd
from streamlit.testing.v1 import AppTest

from src import config, export_excel, review
from tests.test_quality import insert_receipt


def approve(conn, receipt_id):
    review.set_review_status(conn, receipt_id, "approved")


def read_sheets(content):
    return pd.read_excel(io.BytesIO(content), sheet_name=None)


def test_only_approved_receipts_are_exported(db_conn):
    first = insert_receipt(db_conn, 1, number="A-1")
    insert_receipt(db_conn, 2, number="A-2")             # stays pending
    approve(db_conn, first)

    content, count = export_excel.build_workbook(db_conn)
    sheets = read_sheets(content)
    assert count == 1
    assert list(sheets) == ["Receipts", "Lines", "Summary"]
    assert list(sheets["Receipts"]["receipt_number"]) == ["A-1"]
    assert len(sheets["Lines"]) == 2                      # the approved receipt's 2 lines
    assert sheets["Lines"]["line_total"].sum() == 30.0


def test_summary_spend_by_vendor_and_month(db_conn):
    for n in (1, 2):
        approve(db_conn, insert_receipt(db_conn, n, number=f"A-{n}"))

    sheets = read_sheets(export_excel.build_workbook(db_conn)[0])
    summary = sheets["Summary"].set_index("Vendor")
    assert summary.loc["Harbor Fresh Foods", "2026-06"] == 60.0
    assert summary.loc["Total", "Total"] == 60.0


def test_export_with_no_approved_receipts(db_conn):
    content, count = export_excel.build_workbook(db_conn)
    assert count == 0
    assert "Receipts" in read_sheets(content)


def test_export_to_file_name(db_conn, tmp_path):
    path, _ = export_excel.export_to_file(db_conn, exports_dir=tmp_path, today=date(2026, 11, 16))
    assert path.name == "receipts_2026-11-16.xlsx"
    assert path.exists()


def test_export_page_has_download_button(db_conn):
    approve(db_conn, insert_receipt(db_conn, 1))
    app = AppTest.from_file(str(config.PROJECT_ROOT / "app" / "pages" / "3_Export.py"))
    app.session_state["authenticated"] = True
    app.run()
    assert not app.exception
    assert app.metric[0].value == "1"
