"""Tests for the supplier comparison views (sql/007_supplier_comparison.sql)."""

from datetime import date
from decimal import Decimal as D

from streamlit.testing.v1 import AppTest

from src import config, load_mart, prices
from tests.helpers import make_approved_receipt

HARBOR = "Harbor Fresh Foods"
SUNRISE = "Sunrise Meat Co."


def build(conn):
    # Two months of data (June and July).
    # Harbor: 2 cases (20 lb) in June at $3.00/lb, latest (July) 1 case at $3.50/lb.
    make_approved_receipt(conn, 1, HARBOR, date(2026, 6, 5), [("CHKN BRST 10LB", 2, "CS", "30.00")])
    make_approved_receipt(conn, 2, HARBOR, date(2026, 7, 5), [("CHKN BRST 10LB", 1, "CS", "35.00")])
    # Sunrise: 1 case (10 lb) at $3.10/lb.
    make_approved_receipt(conn, 3, SUNRISE, date(2026, 7, 6), [("CHICKEN BREAST BNLS 10 LB", 1, "CS", "31.00")])
    # Only bought from one supplier: not compared
    make_approved_receipt(conn, 4, SUNRISE, date(2026, 7, 7), [("GOAT CUBES", 10, "LB", "6.25")])
    load_mart.build_mart(conn)


def test_only_items_from_two_suppliers(db_conn):
    build(db_conn)
    assert list(prices.supplier_savings(db_conn)["item_name"]) == ["chicken breast"]


def test_latest_and_cheapest_prices(db_conn):
    build(db_conn)
    rows = prices.supplier_comparison(db_conn).set_index("vendor_name")
    assert rows.loc[HARBOR, "latest_price"] == D("3.5000")         # July, not June
    assert rows.loc[SUNRISE, "latest_price"] == D("3.1000")
    assert set(rows["cheapest_vendor"]) == {SUNRISE}
    assert rows.loc[HARBOR, "price_difference"] == D("0.4000")


def test_estimated_savings_hand_calculation(db_conn):
    build(db_conn)
    rows = prices.supplier_comparison(db_conn).set_index("vendor_name")
    # Harbor: 30 lb over 2 months = 15 lb/month x $0.40 = $6.00 per month
    assert rows.loc[HARBOR, "avg_monthly_quantity"] == D("15.000")
    assert rows.loc[HARBOR, "estimated_monthly_savings"] == D("6.00")
    assert rows.loc[SUNRISE, "estimated_monthly_savings"] == D("0.00")
    assert prices.supplier_savings(db_conn)["estimated_monthly_savings"].iloc[0] == D("6.00")


def test_suppliers_page_says_estimated(db_conn):
    build(db_conn)
    app = AppTest.from_file(str(config.PROJECT_ROOT / "app" / "pages" / "7_Suppliers.py"))
    app.session_state["authenticated"] = True
    app.run()
    assert not app.exception
    assert "Estimated savings only" in app.warning[0].value
    assert "delivery fees" in app.warning[0].value
    assert app.metric[1].value == "$6.00"
