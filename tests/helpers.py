"""Small helpers shared by several test files."""

import io

from PIL import Image


def make_approved_receipt(conn, number, vendor, day, lines):
    """Insert an approved receipt straight into the clean tables (no OCR).

    lines: list of (description, quantity, unit, unit_price) tuples.
    Returns receipt_id.
    """
    from decimal import Decimal

    import pandas as pd

    from src import clean

    file_id = conn.execute(
        "INSERT INTO raw.receipt_file (sha256, stored_path, source) VALUES (%s, 'x', 'upload') "
        "RETURNING file_id",
        (f"{number:064d}",),
    ).fetchone()[0]
    rows = []
    for i, (description, quantity, unit, unit_price) in enumerate(lines, start=1):
        qty, price = Decimal(str(quantity)), Decimal(str(unit_price))
        rows.append({"line_no": i, "description_raw": description, "description": description,
                     "quantity": qty, "unit_raw": unit, "unit_price": price,
                     "line_total": (qty * price).quantize(Decimal("0.01"))})
    subtotal = sum(row["line_total"] for row in rows)
    header = {"vendor_raw": vendor, "vendor_name": vendor, "receipt_date_raw": str(day),
              "receipt_date": day, "receipt_number": f"R-{number}",
              "subtotal": subtotal, "tax": Decimal("0.00"), "total": subtotal}
    receipt_id = clean.insert_receipt(conn, file_id, None, header, pd.DataFrame(rows, dtype=object))
    conn.execute("UPDATE clean.receipt SET review_status = 'approved' WHERE receipt_id = %s",
                 (receipt_id,))
    return receipt_id


def image_bytes(fmt="JPEG", size=(200, 300), color=(240, 240, 240)):
    """Make a small in-memory image and return its bytes."""
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, fmt)
    return buffer.getvalue()
