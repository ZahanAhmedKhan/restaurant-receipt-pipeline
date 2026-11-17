"""Read price history and price-increase alerts from the mart views."""

import pandas as pd


def _query(conn, sql, params=None):
    cursor = conn.execute(sql, params)
    columns = [col.name for col in cursor.description]
    return pd.DataFrame(cursor.fetchall(), columns=columns)


def price_history(conn, item_name=None):
    """All purchases with price per standard unit and % change (one item or all)."""
    if item_name:
        return _query(
            conn,
            "SELECT * FROM mart.v_price_history WHERE item_name = %s "
            "ORDER BY vendor_name, purchase_date",
            (item_name,),
        )
    return _query(conn, "SELECT * FROM mart.v_price_history ORDER BY item_name, vendor_name, purchase_date")


def price_alerts(conn):
    """Purchases where the price rose more than the threshold (newest first)."""
    return _query(conn, "SELECT * FROM mart.v_price_alerts ORDER BY purchase_date DESC, pct_change DESC")


def supplier_comparison(conn):
    """One row per item per supplier (items bought from 2+ suppliers)."""
    return _query(conn, "SELECT * FROM mart.v_supplier_comparison ORDER BY item_name, latest_price")


def supplier_savings(conn):
    """One row per item with the ESTIMATED monthly savings, biggest first."""
    return _query(conn, "SELECT * FROM mart.v_supplier_savings "
                        "ORDER BY estimated_monthly_savings DESC, item_name")


def alert_threshold(conn):
    row = conn.execute(
        "SELECT value FROM mart.setting WHERE name = 'price_alert_threshold_pct'"
    ).fetchone()
    return float(row[0]) if row else None
