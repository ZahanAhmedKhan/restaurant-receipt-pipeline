"""Export approved receipts to Excel.

Sheets:
    Receipts  one row per approved receipt
    Lines     one row per line item on an approved receipt
    Summary   spend by vendor (rows) and month (columns), with totals

Usage:
    python -m src.export_excel          # writes exports/receipts_<date>.xlsx
"""

import io
from datetime import date
from decimal import Decimal

import pandas as pd

from src import config
from src.db import get_connection

MONEY_FORMAT = "#,##0.00"

RECEIPTS_SQL = """
SELECT receipt_id, vendor_name, receipt_date, receipt_number, subtotal, tax, total
FROM clean.receipt
WHERE review_status = 'approved'
ORDER BY receipt_date, receipt_id
"""

LINES_SQL = """
SELECT r.receipt_id, r.vendor_name, r.receipt_date, l.line_no, l.description,
       l.quantity, l.unit_raw AS unit, l.unit_price, l.line_total
FROM clean.receipt_line l
JOIN clean.receipt r ON r.receipt_id = l.receipt_id
WHERE r.review_status = 'approved'
ORDER BY r.receipt_date, r.receipt_id, l.line_no
"""


def query_df(conn, sql):
    """Run a query and return a DataFrame with the column names."""
    cursor = conn.execute(sql)
    columns = [col.name for col in cursor.description]
    return pd.DataFrame(cursor.fetchall(), columns=columns, dtype=object)


def spend_summary(receipts):
    """Spend (receipt totals) per vendor and month, plus a Total row and column."""
    if receipts.empty:
        return pd.DataFrame({"vendor_name": []})
    data = receipts.copy()
    data["month"] = data["receipt_date"].map(lambda d: d.strftime("%Y-%m") if d else "no date")
    data["total"] = data["total"].map(lambda v: v if v is not None else Decimal("0"))

    # groupby + sum works on Decimal values (kept exact, no float)
    by_vendor_month = data.groupby(["vendor_name", "month"])["total"].sum()
    table = by_vendor_month.unstack("month", fill_value=Decimal("0"))
    table["Total"] = table.sum(axis=1)
    table.loc["Total"] = table.sum(axis=0)
    return table.reset_index().rename(columns={"vendor_name": "Vendor"})


def build_workbook(conn):
    """Build the Excel file in memory. Returns (bytes, number_of_receipts)."""
    receipts = query_df(conn, RECEIPTS_SQL)
    lines = query_df(conn, LINES_SQL)
    summary = spend_summary(receipts)

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        receipts.to_excel(writer, sheet_name="Receipts", index=False)
        lines.to_excel(writer, sheet_name="Lines", index=False)
        summary.to_excel(writer, sheet_name="Summary", index=False)
        for sheet in writer.sheets.values():
            format_sheet(sheet)
    return buffer.getvalue(), len(receipts)


def format_sheet(sheet):
    """Readable column widths, money format, frozen header row."""
    sheet.freeze_panes = "A2"
    for column in sheet.columns:
        header = str(column[0].value or "")
        width = max(len(header), *(len(str(cell.value or "")) for cell in column[1:]), 8)
        sheet.column_dimensions[column[0].column_letter].width = min(width + 2, 45)
        for cell in column[1:]:
            if isinstance(cell.value, (Decimal, float)) and header != "quantity":
                cell.number_format = MONEY_FORMAT


def export_to_file(conn=None, exports_dir=None, today=None):
    """Write exports/receipts_<date>.xlsx. Returns (path, number_of_receipts)."""
    exports_dir = exports_dir or config.EXPORTS_DIR
    exports_dir.mkdir(parents=True, exist_ok=True)
    today = today or date.today()
    own_connection = conn is None
    if own_connection:
        conn = get_connection()
    try:
        content, count = build_workbook(conn)
    finally:
        if own_connection:
            conn.close()
    path = exports_dir / f"receipts_{today.isoformat()}.xlsx"
    path.write_bytes(content)
    return path, count


if __name__ == "__main__":
    out_path, receipt_count = export_to_file()
    print(f"Exported {receipt_count} approved receipt(s) to {out_path}")
