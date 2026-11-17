"""Queries behind the dashboard pages. All analytics read the mart
(approved receipts only); the overview also reads review / quality status."""

import json

import pandas as pd

from src import config

OCR_RESULTS_JSON = config.PROJECT_ROOT / "docs" / "ocr_evaluation.json"


def _query(conn, sql, params=None):
    cursor = conn.execute(sql, params)
    columns = [col.name for col in cursor.description]
    return pd.DataFrame(cursor.fetchall(), columns=columns)


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------
def overview_stats(conn):
    """Headline numbers (all measured from the database)."""
    row = conn.execute(
        """
        SELECT
            (SELECT count(*) FROM raw.receipt_file)                                AS files,
            (SELECT count(*) FROM raw.receipt_file WHERE status = 'failed')        AS failed_files,
            (SELECT count(*) FROM clean.receipt)                                   AS receipts,
            (SELECT count(*) FROM clean.receipt WHERE review_status = 'approved')  AS approved,
            (SELECT count(*) FROM clean.receipt WHERE review_status = 'needs_review') AS needs_review,
            (SELECT count(*) FROM clean.receipt WHERE review_status = 'pending')   AS pending,
            (SELECT count(*) FROM clean.receipt WHERE review_status = 'rejected')  AS rejected,
            (SELECT COALESCE(sum(line_total), 0) FROM mart.fact_purchase_line)     AS approved_spend,
            (SELECT count(*) FROM clean.correction WHERE field_name <> 'review_status') AS corrections
        """
    ).fetchone()
    names = ["files", "failed_files", "receipts", "approved", "needs_review", "pending",
             "rejected", "approved_spend", "corrections"]
    return dict(zip(names, row))


def dq_failures(conn):
    """How many open-or-closed receipts currently fail each quality check."""
    return _query(
        conn,
        """
        SELECT check_name, count(*) FILTER (WHERE NOT passed) AS failing,
               count(*) AS checked
        FROM dq.check_result
        GROUP BY check_name
        ORDER BY failing DESC, check_name
        """,
    )


# ---------------------------------------------------------------------------
# Spending (filters: start / end date, inclusive)
# ---------------------------------------------------------------------------
def date_range(conn):
    """First and last purchase date in the mart, or (None, None)."""
    return conn.execute(
        """
        SELECT min(d.full_date), max(d.full_date)
        FROM mart.fact_purchase_line f JOIN mart.dim_date d USING (date_key)
        """
    ).fetchone()


SPEND_BASE = """
FROM mart.fact_purchase_line f
JOIN mart.dim_date d   ON d.date_key = f.date_key
JOIN mart.dim_vendor v ON v.vendor_key = f.vendor_key
JOIN mart.dim_item i   ON i.item_key = f.item_key
WHERE d.full_date BETWEEN %s AND %s
"""


def spend_by_month(conn, start, end):
    return _query(
        conn,
        "SELECT to_char(d.full_date, 'YYYY-MM') AS month, v.vendor_name, sum(f.line_total) AS spend "
        + SPEND_BASE + " GROUP BY 1, 2 ORDER BY 1, 2",
        (start, end),
    )


def spend_by_vendor(conn, start, end):
    return _query(
        conn,
        "SELECT v.vendor_name, sum(f.line_total) AS spend, count(DISTINCT f.receipt_id) AS receipts "
        + SPEND_BASE + " GROUP BY 1 ORDER BY spend DESC",
        (start, end),
    )


def spend_by_item(conn, start, end, limit=15):
    return _query(
        conn,
        "SELECT i.item_name, i.category, sum(f.line_total) AS spend "
        + SPEND_BASE + " GROUP BY 1, 2 ORDER BY spend DESC LIMIT %s",
        (start, end, limit),
    )


def all_vendors(conn):
    """Every vendor name, sorted. Used to give each vendor a fixed chart color."""
    return [row[0] for row in conn.execute(
        "SELECT vendor_name FROM mart.dim_vendor ORDER BY vendor_name").fetchall()]


# ---------------------------------------------------------------------------
# OCR evaluation
# ---------------------------------------------------------------------------
def ocr_results(path=OCR_RESULTS_JSON):
    """Results written by src/evaluate_ocr.py, as a table: one column per method."""
    if not path.exists():
        return pd.DataFrame()
    results = json.loads(path.read_text(encoding="utf-8"))
    rows = {
        "Receipts evaluated": lambda r: r["receipts"],
        "Vendor correct (%)": lambda r: r["header_accuracy_pct"]["vendor"],
        "Date correct (%)": lambda r: r["header_accuracy_pct"]["date"],
        "Receipt number correct (%)": lambda r: r["header_accuracy_pct"]["receipt_number"],
        "Total correct (%)": lambda r: r["header_accuracy_pct"]["total"],
        "Line items found (%)": lambda r: r["lines"]["matched_pct"],
        "Line items fully correct (%)": lambda r: r["lines"]["fully_correct_pct"],
        "Quantity correct (%)": lambda r: r["lines"]["field_accuracy_pct"]["quantity"],
        "Unit price correct (%)": lambda r: r["lines"]["field_accuracy_pct"]["unit_price"],
        "Line total correct (%)": lambda r: r["lines"]["field_accuracy_pct"]["line_total"],
        "Avg time per receipt (ms)": lambda r: r["avg_duration_ms"],
        "Run date": lambda r: r["run_date"],
    }
    table = {method: [getter(result) for getter in rows.values()] for method, result in results.items()}
    return pd.DataFrame(table, index=list(rows))
