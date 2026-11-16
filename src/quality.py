"""Data quality checks for clean receipts.

Every check returns (passed, details). Results go to dq.check_result.
Any failure -> review_status 'needs_review'; all pass -> 'pending' (waits for approval).
Approved or rejected receipts keep their status. Data is never deleted.

Run checks on every open receipt:
    python -m src.quality
"""

import logging
from datetime import date
from decimal import Decimal

from src.db import get_connection

logger = logging.getLogger(__name__)

# Money comparisons allow a small rounding difference
TOLERANCE = Decimal("0.02")
OPEN_STATUSES = ("pending", "needs_review")


# ---------------------------------------------------------------------------
# The checks. Each gets the receipt header (dict) and its lines (list of dicts).
# ---------------------------------------------------------------------------
def check_required_fields(receipt, lines):
    missing = []
    for field in ("vendor_name", "receipt_date", "receipt_number", "total"):
        if receipt.get(field) is None:
            missing.append(field)
    if not lines:
        missing.append("line items")

    # Each line needs a description, quantity, price and amount
    incomplete = []
    for line in lines:
        needed = ("description", "quantity", "unit_price", "line_total")
        if any(line.get(field) is None for field in needed):
            incomplete.append(str(line["line_no"]))
    if incomplete:
        missing.append("values on line(s) " + ", ".join(incomplete))

    if missing:
        return False, "missing: " + "; ".join(missing)
    return True, None


def check_valid_date(receipt, lines, today=None):
    today = today or date.today()
    receipt_date = receipt.get("receipt_date")
    if receipt_date is None:
        if receipt.get("receipt_date_raw"):
            return False, "date could not be read"
        return False, "no date"
    if receipt_date > today:
        return False, f"date {receipt_date} is in the future"
    if receipt_date.year < 2000:
        return False, f"date {receipt_date} is too old"
    return True, None


def check_no_negative_values(receipt, lines):
    negatives = []
    for field in ("subtotal", "tax", "total"):
        value = receipt.get(field)
        if value is not None and value < 0:
            negatives.append(field)
    for line in lines:
        for field in ("quantity", "unit_price", "line_total"):
            value = line.get(field)
            if value is not None and value < 0:
                negatives.append(f"line {line['line_no']} {field}")
    if negatives:
        return False, "negative: " + ", ".join(negatives)
    return True, None


def check_lines_match_subtotal(receipt, lines):
    subtotal = receipt.get("subtotal")
    if subtotal is None:
        return False, "no subtotal to compare with"
    if not lines:
        return False, "no line items"
    if any(line.get("line_total") is None for line in lines):
        return False, "some line amounts could not be read"
    lines_sum = sum(line["line_total"] for line in lines)
    if abs(lines_sum - subtotal) > TOLERANCE:
        return False, f"lines add up to {lines_sum}, subtotal is {subtotal}"
    return True, None


def check_total_is_subtotal_plus_tax(receipt, lines):
    subtotal, tax, total = receipt.get("subtotal"), receipt.get("tax"), receipt.get("total")
    if subtotal is None or total is None:
        return False, "subtotal or total missing"
    tax = tax or Decimal("0")
    expected = subtotal + tax
    if abs(expected - total) > TOLERANCE:
        return False, f"subtotal + tax = {expected}, total is {total}"
    return True, None


# Checks that only need this receipt's own data, in the order they are shown
SIMPLE_CHECKS = {
    "required_fields": check_required_fields,
    "valid_date": check_valid_date,
    "no_negative_values": check_no_negative_values,
    "lines_match_subtotal": check_lines_match_subtotal,
    "total_is_subtotal_plus_tax": check_total_is_subtotal_plus_tax,
}


def check_not_duplicate(conn, receipt):
    """Same vendor + receipt number + total on an EARLIER, non-rejected receipt."""
    if not receipt.get("vendor_name") or not receipt.get("receipt_number") or receipt.get("total") is None:
        return True, "not enough data to compare"
    row = conn.execute(
        """
        SELECT receipt_id FROM clean.receipt
        WHERE vendor_name = %s AND receipt_number = %s AND total = %s
          AND receipt_id < %s AND review_status <> 'rejected'
        ORDER BY receipt_id
        LIMIT 1
        """,
        (receipt["vendor_name"], receipt["receipt_number"], receipt["total"], receipt["receipt_id"]),
    ).fetchone()
    if row:
        return False, f"same as receipt #{row[0]}"
    return True, None


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
RECEIPT_COLUMNS = ["receipt_id", "vendor_name", "receipt_date_raw", "receipt_date",
                   "receipt_number", "subtotal", "tax", "total", "review_status"]
LINE_COLUMNS = ["line_no", "description", "quantity", "unit_price", "line_total"]


def load_receipt(conn, receipt_id):
    """Read one receipt and its lines as plain dicts."""
    # The column lists are constants in this file (not user input),
    # so building the column part of the SQL with an f-string is safe.
    row = conn.execute(
        f"SELECT {', '.join(RECEIPT_COLUMNS)} FROM clean.receipt WHERE receipt_id = %s",
        (receipt_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"no receipt with receipt_id={receipt_id}")
    receipt = dict(zip(RECEIPT_COLUMNS, row))
    line_rows = conn.execute(
        f"SELECT {', '.join(LINE_COLUMNS)} FROM clean.receipt_line "
        "WHERE receipt_id = %s ORDER BY line_no",
        (receipt_id,),
    ).fetchall()
    lines = [dict(zip(LINE_COLUMNS, line)) for line in line_rows]
    return receipt, lines


def run_checks(conn, receipt_id):
    """Run all checks on one receipt, save results, update its status.

    Returns a dict {check_name: (passed, details)}.
    """
    receipt, lines = load_receipt(conn, receipt_id)
    results = {}
    for name, check in SIMPLE_CHECKS.items():
        results[name] = check(receipt, lines)
    results["not_duplicate"] = check_not_duplicate(conn, receipt)

    all_passed = all(passed for passed, _ in results.values())

    with conn.transaction():
        # Replace old results for this receipt with the new ones
        conn.execute("DELETE FROM dq.check_result WHERE receipt_id = %s", (receipt_id,))
        for name, (passed, details) in results.items():
            conn.execute(
                "INSERT INTO dq.check_result (receipt_id, check_name, passed, details) "
                "VALUES (%s, %s, %s, %s)",
                (receipt_id, name, passed, details),
            )
        # Only open receipts change status; approved/rejected stay as they are
        if receipt["review_status"] in OPEN_STATUSES:
            new_status = "pending" if all_passed else "needs_review"
            conn.execute(
                "UPDATE clean.receipt SET review_status = %s, updated_at = now() "
                "WHERE receipt_id = %s",
                (new_status, receipt_id),
            )

    failed = [name for name, (passed, _) in results.items() if not passed]
    logger.info("DQ receipt_id=%s failed=%s", receipt_id, failed)
    return results


def check_open_receipts(conn=None):
    """Run checks on every pending / needs_review receipt. Returns how many."""
    own_connection = conn is None
    if own_connection:
        conn = get_connection()
    try:
        ids = [
            row[0]
            for row in conn.execute(
                "SELECT receipt_id FROM clean.receipt WHERE review_status = ANY(%s) "
                "ORDER BY receipt_id",
                (list(OPEN_STATUSES),),
            ).fetchall()
        ]
        for receipt_id in ids:
            run_checks(conn, receipt_id)
        return len(ids)
    finally:
        if own_connection:
            conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(f"Checked {check_open_receipts()} receipt(s)")
