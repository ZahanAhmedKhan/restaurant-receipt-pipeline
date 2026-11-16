"""Cleaning step: standardize parsed fields with pandas and load them into
clean.receipt and clean.receipt_line (status 'pending').

Raw values are kept next to clean ones (vendor_raw, receipt_date_raw,
description_raw, unit_raw) so a reviewer can always see what OCR read.
"""

import difflib
import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

import pandas as pd

from src.db import get_connection
from src.parse import parse_receipt_text

logger = logging.getLogger(__name__)

# Date formats our suppliers print, tried in this order
DATE_FORMATS = [
    "%m/%d/%Y",    # 06/14/2026
    "%Y-%m-%d",    # 2026-06-14
    "%b %d, %Y",   # Jun 14, 2026
    "%b %d %Y",    # Jun 14 2026 (OCR dropped the comma)
    "%m/%d/%y",    # 06/14/26
    "%d-%b-%Y",    # 14-Jun-2026
]

# How similar an OCR'd vendor name must be to a known one (0..1) to map it
VENDOR_MATCH_CUTOFF = 0.85

CENT = Decimal("0.01")


# ---------------------------------------------------------------------------
# Value cleaners (each takes one raw value and returns a clean value or None)
# ---------------------------------------------------------------------------
def clean_text(value):
    """Trim, collapse inner spaces, uppercase. Empty -> None."""
    if value is None or pd.isna(value):
        return None
    text = re.sub(r"\s+", " ", str(value)).strip().upper()
    return text or None


def clean_date(value):
    """Turn a printed date into a datetime.date, or None if no format fits."""
    text = clean_text(value)
    if text is None:
        return None
    for fmt in DATE_FORMATS:
        try:
            # strptime is case-insensitive for month names (JUL == Jul)
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def clean_money(value):
    """'32.50' -> Decimal('32.50'). Never float. None if not a number."""
    if value is None or pd.isna(value):
        return None
    try:
        return Decimal(str(value)).quantize(CENT)
    except InvalidOperation:
        return None


def clean_quantity(value):
    if value is None or pd.isna(value):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def standardize_vendor(vendor_raw, vendor_map):
    """Map an OCR'd vendor name to our standard name.

    vendor_map: {"HARBOR FRESH FOODS": "Harbor Fresh Foods", ...}
    Exact match first, then a close match (handles small OCR typos).
    Unknown vendors keep their cleaned raw text so nothing is lost.
    """
    key = clean_text(vendor_raw)
    if key is None:
        return None
    if key in vendor_map:
        return vendor_map[key]
    close = difflib.get_close_matches(key, list(vendor_map), n=1, cutoff=VENDOR_MATCH_CUTOFF)
    if close:
        return vendor_map[close[0]]
    return key.title()


# ---------------------------------------------------------------------------
# Cleaning one parsed receipt with pandas
# ---------------------------------------------------------------------------
def clean_receipt(parsed, vendor_map):
    """Clean one parsed receipt.

    Returns (header, lines):
        header: dict of clean header fields
        lines:  pandas DataFrame, one row per line item
    """
    header = {
        "vendor_raw": parsed.get("vendor"),
        "vendor_name": standardize_vendor(parsed.get("vendor"), vendor_map),
        "receipt_date_raw": parsed.get("date"),
        "receipt_date": clean_date(parsed.get("date")),
        "receipt_number": clean_text(parsed.get("receipt_number")),
        "subtotal": clean_money(parsed.get("subtotal")),
        "tax": clean_money(parsed.get("tax")),
        "total": clean_money(parsed.get("total")),
    }

    raw_lines = pd.DataFrame(
        parsed.get("lines") or [],
        columns=["description", "quantity", "unit", "unit_price", "line_total"],
        dtype=object,   # keep None as None (not NaN) and strings as strings
    )
    lines = pd.DataFrame({
        "line_no": range(1, len(raw_lines) + 1),
        "description_raw": raw_lines["description"],
        "description": raw_lines["description"].map(clean_text),
        "quantity": raw_lines["quantity"].map(clean_quantity),
        "unit_raw": raw_lines["unit"].map(clean_text),
        "unit_price": raw_lines["unit_price"].map(clean_money),
        "line_total": raw_lines["line_total"].map(clean_money),
    })
    return header, lines


def none_if_missing(value):
    """pandas may hold NaN for missing values; the database needs None."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def load_vendor_map(conn):
    rows = conn.execute("SELECT vendor_raw, vendor_name FROM clean.vendor_mapping").fetchall()
    return {raw: name for raw, name in rows}


def insert_receipt(conn, file_id, ocr_run_id, header, lines):
    """Insert the receipt and its lines in ONE transaction. Returns receipt_id."""
    with conn.transaction():
        receipt_id = conn.execute(
            """
            INSERT INTO clean.receipt
                (file_id, ocr_run_id, vendor_raw, vendor_name, receipt_date_raw,
                 receipt_date, receipt_number, subtotal, tax, total)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING receipt_id
            """,
            (file_id, ocr_run_id, header["vendor_raw"], header["vendor_name"],
             header["receipt_date_raw"], header["receipt_date"], header["receipt_number"],
             header["subtotal"], header["tax"], header["total"]),
        ).fetchone()[0]

        for row in lines.itertuples(index=False):
            conn.execute(
                """
                INSERT INTO clean.receipt_line
                    (receipt_id, line_no, description_raw, description, quantity,
                     unit_raw, unit_price, line_total)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (receipt_id, int(row.line_no), none_if_missing(row.description_raw),
                 none_if_missing(row.description), none_if_missing(row.quantity),
                 none_if_missing(row.unit_raw), none_if_missing(row.unit_price),
                 none_if_missing(row.line_total)),
            )
        conn.execute(
            "UPDATE raw.receipt_file SET status = 'parsed' WHERE file_id = %s", (file_id,)
        )
    return receipt_id


def latest_ocr_run(conn, file_id):
    """The newest successful OCR run for a file: (ocr_run_id, raw_text, raw_json)."""
    return conn.execute(
        """
        SELECT ocr_run_id, raw_text, raw_json
        FROM raw.ocr_run
        WHERE file_id = %s AND error IS NULL
        ORDER BY ocr_run_id DESC
        LIMIT 1
        """,
        (file_id,),
    ).fetchone()


def process_file(conn, file_id, vendor_map=None):
    """Parse + clean + load one OCR'd file. Returns receipt_id.

    Safe to rerun: if the file already has a receipt, that receipt is
    returned and nothing is changed (it may already be reviewed).
    """
    existing = conn.execute(
        "SELECT receipt_id FROM clean.receipt WHERE file_id = %s", (file_id,)
    ).fetchone()
    if existing:
        return existing[0]

    run = latest_ocr_run(conn, file_id)
    if run is None:
        raise ValueError(f"file_id={file_id} has no successful OCR run")
    ocr_run_id, raw_text, raw_json = run

    # Gemini returns structured JSON directly; Tesseract returns text to parse
    parsed = raw_json if raw_json else parse_receipt_text(raw_text)

    if vendor_map is None:
        vendor_map = load_vendor_map(conn)
    header, lines = clean_receipt(parsed, vendor_map)
    receipt_id = insert_receipt(conn, file_id, ocr_run_id, header, lines)
    logger.info("Loaded receipt_id=%s file_id=%s lines=%s", receipt_id, file_id, len(lines))
    return receipt_id


def process_pending(conn=None):
    """Parse/clean/load every file with status 'ocr_done'. Returns new receipt_ids."""
    own_connection = conn is None
    if own_connection:
        conn = get_connection()
    try:
        file_ids = [
            row[0]
            for row in conn.execute(
                "SELECT file_id FROM raw.receipt_file WHERE status = 'ocr_done' ORDER BY file_id"
            ).fetchall()
        ]
        vendor_map = load_vendor_map(conn)
        receipt_ids = []
        for file_id in file_ids:
            receipt_ids.append(process_file(conn, file_id, vendor_map))
        return receipt_ids
    finally:
        if own_connection:
            conn.close()
