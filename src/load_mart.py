"""Build the star schema (mart) from APPROVED clean receipts.

Idempotent: the fact table is emptied and refilled inside one transaction,
so rerunning gives the same result, and corrections made after approval
show up on the next rebuild. No duplicates, ever (line_id is UNIQUE).

Usage:
    python -m src.load_mart
"""

import logging

from src import config, normalize
from src.db import get_connection

logger = logging.getLogger(__name__)

UNKNOWN_VENDOR = "Unknown vendor"
UNKNOWN_DATE_KEY = 0

# 0. The "unknown" rows the facts fall back to (re-created if someone emptied the tables)
ENSURE_UNKNOWN_ROWS = """
INSERT INTO mart.dim_item (item_name) VALUES ('UNMAPPED') ON CONFLICT (item_name) DO NOTHING;
INSERT INTO mart.dim_date (date_key, full_date, month_name, day_of_week)
VALUES (0, NULL, 'Unknown', 'Unknown') ON CONFLICT (date_key) DO NOTHING;
"""

# 1. Every vendor on an approved receipt gets a row (existing rows are kept)
UPSERT_VENDORS = """
INSERT INTO mart.dim_vendor (vendor_name)
SELECT DISTINCT COALESCE(vendor_name, %s)
FROM clean.receipt
WHERE review_status = 'approved'
ON CONFLICT (vendor_name) DO NOTHING
"""

# 2. A calendar row for every day from the first to the last approved receipt
UPSERT_DATES = """
INSERT INTO mart.dim_date (date_key, full_date, year, month, month_name, week, day_of_week)
SELECT
    to_char(d, 'YYYYMMDD')::int,
    d::date,
    extract(year FROM d)::int,
    extract(month FROM d)::int,
    trim(to_char(d, 'Month')),
    extract(week FROM d)::int,
    trim(to_char(d, 'Day'))
FROM generate_series(
    (SELECT min(receipt_date) FROM clean.receipt WHERE review_status = 'approved'),
    (SELECT max(receipt_date) FROM clean.receipt WHERE review_status = 'approved'),
    interval '1 day'
) AS d
ON CONFLICT (date_key) DO NOTHING
"""

# 3. Rebuild the facts: one row per line on an approved receipt.
#    Items start as UNMAPPED; step 4 (normalize.py) fills in the real item.
DELETE_FACTS = "DELETE FROM mart.fact_purchase_line"

INSERT_FACTS = """
INSERT INTO mart.fact_purchase_line
    (line_id, receipt_id, vendor_key, item_key, date_key, quantity, line_total)
SELECT
    l.line_id,
    r.receipt_id,
    v.vendor_key,
    (SELECT item_key FROM mart.dim_item WHERE item_name = 'UNMAPPED'),
    COALESCE(to_char(r.receipt_date, 'YYYYMMDD')::int, %s),
    l.quantity,
    l.line_total
FROM clean.receipt_line l
JOIN clean.receipt r ON r.receipt_id = l.receipt_id
JOIN mart.dim_vendor v ON v.vendor_name = COALESCE(r.vendor_name, %s)
WHERE r.review_status = 'approved'
"""


UPSERT_SETTING = """
INSERT INTO mart.setting (name, value) VALUES (%s, %s)
ON CONFLICT (name) DO UPDATE SET value = EXCLUDED.value
"""


def build_mart(conn=None):
    """Rebuild the mart. Returns a dict of row counts."""
    own_connection = conn is None
    if own_connection:
        conn = get_connection()
    try:
        # All or nothing: if anything fails, the old mart stays as it was
        with conn.transaction():
            conn.execute(ENSURE_UNKNOWN_ROWS)
            conn.execute(UPSERT_VENDORS, (UNKNOWN_VENDOR,))
            conn.execute(UPSERT_DATES)
            conn.execute(DELETE_FACTS)
            conn.execute(INSERT_FACTS, (UNKNOWN_DATE_KEY, UNKNOWN_VENDOR))
            # 4. Map descriptions to items and convert to standard units
            normalize.normalize_facts(conn)
            # 5. Settings the price views read (threshold comes from .env)
            conn.execute(UPSERT_SETTING, ("price_alert_threshold_pct",
                                          str(config.PRICE_ALERT_THRESHOLD_PCT)))
        counts = {}
        for table in ("dim_vendor", "dim_item", "dim_date", "fact_purchase_line"):
            # table names come from the fixed tuple above, not from input
            counts[table] = conn.execute(f"SELECT count(*) FROM mart.{table}").fetchone()[0]
        logger.info("Mart rebuilt: %s", counts)
        return counts
    finally:
        if own_connection:
            conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(build_mart())
