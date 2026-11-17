"""Tests for src/dashboard.py and the dashboard pages."""

import json
from datetime import date
from decimal import Decimal as D

import pytest
from streamlit.testing.v1 import AppTest

from src import config, dashboard, load_mart, quality
from tests.helpers import make_approved_receipt

PAGES = config.PROJECT_ROOT / "app" / "pages"


@pytest.fixture
def data(db_conn):
    make_approved_receipt(db_conn, 1, "Harbor Fresh Foods", date(2026, 6, 5), [("CHKN BRST 10LB", 2, "CS", "30.00")])
    make_approved_receipt(db_conn, 2, "Harbor Fresh Foods", date(2026, 9, 5), [("CHKN BRST 10LB", 1, "CS", "36.00")])
    make_approved_receipt(db_conn, 3, "Sunrise Meat Co.", date(2026, 7, 6), [("GOAT CUBES", 10, "LB", "6.25")])
    quality.run_checks(db_conn, 1)
    load_mart.build_mart(db_conn)
    return db_conn


def test_overview_stats(data):
    stats = dashboard.overview_stats(data)
    assert stats["receipts"] == 3
    assert stats["approved"] == 3
    assert stats["approved_spend"] == D("158.50")


def test_dq_failures_counts(data):
    failures = dashboard.dq_failures(data)
    assert set(failures["checked"]) == {1}


def test_spending_queries_respect_date_filter(data):
    first, last = dashboard.date_range(data)
    assert (first, last) == (date(2026, 6, 5), date(2026, 9, 5))
    all_time = dashboard.spend_by_vendor(data, first, last)
    summer = dashboard.spend_by_vendor(data, date(2026, 6, 1), date(2026, 7, 31))
    assert all_time["spend"].sum() == D("158.50")
    assert summer["spend"].sum() == D("122.50")
    months = dashboard.spend_by_month(data, first, last)
    assert list(months["month"]) == ["2026-06", "2026-07", "2026-09"]
    items = dashboard.spend_by_item(data, first, last)
    assert items["item_name"].iloc[0] == "chicken breast"


def test_ocr_results_table(tmp_path):
    path = tmp_path / "ocr.json"
    path.write_text(json.dumps({"tesseract": {
        "receipts": 50, "run_date": "2026-11-16", "avg_duration_ms": 527,
        "header_accuracy_pct": {"vendor": 100.0, "date": 100.0, "receipt_number": 100.0, "total": 96.0},
        "lines": {"matched_pct": 100.0, "fully_correct_pct": 69.2,
                  "field_accuracy_pct": {"quantity": 78.8, "unit_price": 90.4, "line_total": 90.0}},
    }}))
    table = dashboard.ocr_results(path)
    assert table.loc["Total correct (%)", "tesseract"] == 96.0
    assert dashboard.ocr_results(tmp_path / "missing.json").empty


def run_page(path):
    app = AppTest.from_file(str(path), default_timeout=30)
    app.session_state["authenticated"] = True
    return app.run()


@pytest.mark.parametrize("page", ["5_Spending.py", "6_Prices.py", "7_Suppliers.py", "8_OCR_Evaluation.py"])
def test_dashboard_pages_render(data, page):
    app = run_page(PAGES / page)
    assert not app.exception


def test_home_overview_renders(data):
    app = run_page(config.PROJECT_ROOT / "app" / "Home.py")
    assert not app.exception
    assert app.metric[0].value == "$158.50"


def test_prices_page_shows_alert(data):
    app = run_page(PAGES / "6_Prices.py")
    assert "above 10%" in app.subheader[0].value
    assert len(app.dataframe) >= 1
