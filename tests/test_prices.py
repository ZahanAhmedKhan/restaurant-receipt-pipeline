"""Tests for the price history / alert views (sql/006_price_views.sql)."""

from datetime import date
from decimal import Decimal as D

from src import config, db, load_mart, prices
from tests.helpers import make_approved_receipt

HARBOR = "Harbor Fresh Foods"
SUNRISE = "Sunrise Meat Co."


def build(conn):
    # 1 case of CHKN BRST 10LB = 10 lb, so the case price / 10 = price per lb
    make_approved_receipt(conn, 1, HARBOR, date(2026, 6, 1), [("CHKN BRST 10LB", 1, "CS", "30.00")])
    make_approved_receipt(conn, 2, HARBOR, date(2026, 7, 1), [("CHKN BRST 10LB", 2, "CS", "31.50")])  # +5%
    make_approved_receipt(conn, 3, HARBOR, date(2026, 9, 1), [("CHKN BRST 10LB", 1, "CS", "36.54")])  # +16%
    make_approved_receipt(conn, 4, SUNRISE, date(2026, 9, 2), [("CHICKEN BREAST BNLS 10 LB", 1, "CS", "30.90")])
    load_mart.build_mart(conn)


def test_price_history_per_standard_unit(db_conn):
    build(db_conn)
    history = prices.price_history(db_conn, "chicken breast")
    harbor = history[history["vendor_name"] == HARBOR]
    assert list(harbor["unit_price"]) == [D("3.0000"), D("3.1500"), D("3.6540")]
    assert list(harbor["pct_change"])[1:] == [D("5.0"), D("16.0")]
    assert harbor["pct_change"].iloc[0] is None             # first purchase: nothing to compare


def test_history_is_per_vendor(db_conn):
    build(db_conn)
    sunrise = prices.price_history(db_conn, "chicken breast").query("vendor_name == @SUNRISE")
    assert len(sunrise) == 1
    assert sunrise["previous_price"].iloc[0] is None        # not compared with Harbor's price


def test_alert_only_above_threshold(db_conn, monkeypatch):
    monkeypatch.setattr(config, "PRICE_ALERT_THRESHOLD_PCT", 10.0)
    build(db_conn)
    alerts = prices.price_alerts(db_conn)
    assert list(alerts["purchase_date"]) == [date(2026, 9, 1)]
    assert prices.alert_threshold(db_conn) == 10.0


def test_threshold_from_env_setting(db_conn, monkeypatch):
    monkeypatch.setattr(config, "PRICE_ALERT_THRESHOLD_PCT", 4.0)
    build(db_conn)
    assert len(prices.price_alerts(db_conn)) == 2           # +5% and +16%


def test_chatbot_role_can_read_price_views(db_conn):
    build(db_conn)
    with db.get_connection(readonly=True) as ro:
        assert ro.execute("SELECT count(*) FROM mart.v_price_alerts").fetchone()[0] == 1
