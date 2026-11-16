"""Review logic: load a receipt for review, save corrections, approve/reject.

Every change a reviewer makes is logged in clean.correction
(field, old value, new value), so nothing is silently overwritten.
"""

from datetime import date
from decimal import Decimal

from src import quality
from src.clean import clean_date, clean_money, clean_quantity, clean_text

HEADER_FIELDS = ["vendor_name", "receipt_date", "receipt_number", "subtotal", "tax", "total"]
LINE_FIELDS = ["description", "quantity", "unit_raw", "unit_price", "line_total"]

# How to turn what the reviewer typed into a clean value, per field
CONVERTERS = {
    "vendor_name": lambda v: (str(v).strip() or None) if v is not None else None,
    "receipt_date": clean_date,
    "receipt_number": clean_text,
    "subtotal": clean_money,
    "tax": clean_money,
    "total": clean_money,
    "description": clean_text,
    "quantity": clean_quantity,
    "unit_raw": clean_text,
    "unit_price": clean_money,
    "line_total": clean_money,
}


def as_text(value):
    """How a value is shown on the page and written in the correction log."""
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        if value.as_tuple().exponent == -2:
            return str(value)                         # money: 32.50
        return format(value.normalize(), "f")         # quantity 2.000 -> 2
    return str(value)


def values_equal(a, b):
    """Compare by value, so 2 == 2.000 and '' == None."""
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, Decimal) and isinstance(b, Decimal):
        return a == b
    return as_text(a) == as_text(b)


def convert(field, value):
    """Clean one typed value. Empty input -> None."""
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, float):
        value = repr(value)        # 2.5 -> "2.5", never Decimal(2.5) from a float
    return CONVERTERS[field](value)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def list_receipts(conn, status):
    """Receipts with one review status, oldest first."""
    return conn.execute(
        """
        SELECT receipt_id, vendor_name, receipt_date, total
        FROM clean.receipt
        WHERE review_status = %s
        ORDER BY receipt_id
        """,
        (status,),
    ).fetchall()


def get_receipt(conn, receipt_id):
    """Everything the review page shows for one receipt."""
    receipt, lines = quality.load_receipt(conn, receipt_id)
    # unit_raw is not part of quality's line columns, so add it
    units = dict(conn.execute(
        "SELECT line_no, unit_raw FROM clean.receipt_line WHERE receipt_id = %s", (receipt_id,)
    ).fetchall())
    for line in lines:
        line["unit_raw"] = units.get(line["line_no"])

    stored_path = conn.execute(
        """
        SELECT f.stored_path FROM clean.receipt r
        JOIN raw.receipt_file f ON f.file_id = r.file_id
        WHERE r.receipt_id = %s
        """,
        (receipt_id,),
    ).fetchone()[0]
    checks = conn.execute(
        "SELECT check_name, passed, details FROM dq.check_result "
        "WHERE receipt_id = %s ORDER BY check_id",
        (receipt_id,),
    ).fetchall()
    corrections = conn.execute(
        "SELECT corrected_at, field_name, old_value, new_value FROM clean.correction "
        "WHERE receipt_id = %s ORDER BY correction_id",
        (receipt_id,),
    ).fetchall()
    return {"receipt": receipt, "lines": lines, "stored_path": stored_path,
            "checks": checks, "corrections": corrections}


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------
def log_correction(conn, receipt_id, field_name, old_value, new_value):
    conn.execute(
        "INSERT INTO clean.correction (receipt_id, field_name, old_value, new_value) "
        "VALUES (%s, %s, %s, %s)",
        (receipt_id, field_name, as_text(old_value), as_text(new_value)),
    )


def save_corrections(conn, receipt_id, new_header, new_lines):
    """Save the reviewer's edits and log every change. Returns the number of changes.

    new_header: {field: typed value} for HEADER_FIELDS
    new_lines:  list of {line_no (None for a new line), description, quantity, ...}
                Lines missing from the list are deleted.
    Afterwards the quality checks run again on the corrected values.
    """
    current = get_receipt(conn, receipt_id)
    old_header = current["receipt"]
    old_lines = {line["line_no"]: line for line in current["lines"]}
    changes = 0

    with conn.transaction():
        # 1. Header fields
        for field in HEADER_FIELDS:
            new_value = convert(field, new_header.get(field))
            if not values_equal(new_value, old_header.get(field)):
                # field is from the fixed HEADER_FIELDS list, never user input
                conn.execute(
                    f"UPDATE clean.receipt SET {field} = %s WHERE receipt_id = %s",
                    (new_value, receipt_id),
                )
                log_correction(conn, receipt_id, field, old_header.get(field), new_value)
                changes += 1

        # 2. Changed and new lines
        kept_line_nos = set()
        next_line_no = max(old_lines, default=0) + 1
        for line in new_lines:
            values = {field: convert(field, line.get(field)) for field in LINE_FIELDS}
            line_no = line.get("line_no")
            if line_no is None or line_no not in old_lines:
                if all(value is None for value in values.values()):
                    continue                     # an empty row added by mistake
                conn.execute(
                    """
                    INSERT INTO clean.receipt_line
                        (receipt_id, line_no, description, quantity, unit_raw, unit_price, line_total)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (receipt_id, next_line_no, values["description"], values["quantity"],
                     values["unit_raw"], values["unit_price"], values["line_total"]),
                )
                log_correction(conn, receipt_id, f"line {next_line_no} added", None,
                               values["description"])
                kept_line_nos.add(next_line_no)
                next_line_no += 1
                changes += 1
                continue

            kept_line_nos.add(line_no)
            for field in LINE_FIELDS:
                old_value = old_lines[line_no].get(field)
                if not values_equal(values[field], old_value):
                    conn.execute(
                        f"UPDATE clean.receipt_line SET {field} = %s "
                        "WHERE receipt_id = %s AND line_no = %s",
                        (values[field], receipt_id, line_no),
                    )
                    log_correction(conn, receipt_id, f"line {line_no} {field}", old_value,
                                   values[field])
                    changes += 1

        # 3. Deleted lines
        for line_no, old_line in old_lines.items():
            if line_no not in kept_line_nos:
                conn.execute(
                    "DELETE FROM clean.receipt_line WHERE receipt_id = %s AND line_no = %s",
                    (receipt_id, line_no),
                )
                log_correction(conn, receipt_id, f"line {line_no} deleted",
                               old_line.get("description"), None)
                changes += 1

        if changes:
            conn.execute("UPDATE clean.receipt SET updated_at = now() WHERE receipt_id = %s",
                         (receipt_id,))

    # Re-check the corrected receipt (updates pending / needs_review)
    quality.run_checks(conn, receipt_id)
    return changes


def set_review_status(conn, receipt_id, new_status):
    """Approve or reject a receipt (or reopen it). The change is logged."""
    if new_status not in ("approved", "rejected", "pending"):
        raise ValueError(f"not allowed: {new_status}")
    old_status = conn.execute(
        "SELECT review_status FROM clean.receipt WHERE receipt_id = %s", (receipt_id,)
    ).fetchone()[0]
    with conn.transaction():
        conn.execute(
            "UPDATE clean.receipt SET review_status = %s, updated_at = now() WHERE receipt_id = %s",
            (new_status, receipt_id),
        )
        log_correction(conn, receipt_id, "review_status", old_status, new_status)
    if new_status == "pending":
        quality.run_checks(conn, receipt_id)   # reopened: work out pending/needs_review again
