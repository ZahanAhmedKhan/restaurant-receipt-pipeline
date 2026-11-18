"""All receipts: a searchable list of every receipt, and a read-only view of one
(photo + items). Editing and approving happen on the Check receipts page."""

import app_common

app_common.setup_page("All receipts", layout="wide")

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from src import review  # noqa: E402
from src.ocr import resolve_stored_path  # noqa: E402

STATUS_LABELS = {
    None: "All",
    "needs_review": "⚠️ Needs checking",
    "pending": "🕒 Ready to approve",
    "approved": "✅ Approved",
    "rejected": "❌ Rejected",
}

conn = app_common.db()
st.title("All receipts")

# --- filters (one row) ---------------------------------------------------------------
col1, col2, col3 = st.columns(3)
status = col1.selectbox("Status", list(STATUS_LABELS), format_func=STATUS_LABELS.get)
vendor = col2.selectbox("Supplier", [None] + review.vendor_names(conn),
                        format_func=lambda v: "All" if v is None else v)
search = col3.text_input("Search", placeholder="supplier, receipt no. or item")

receipts = review.all_receipts(conn, status=status, vendor=vendor, search=search.strip() or None)
if not receipts:
    st.info("No receipts match.")
    st.stop()

table = pd.DataFrame(receipts)
table["review_status"] = table["review_status"].map(STATUS_LABELS)
total_shown = sum(r["total"] for r in receipts if r["total"] is not None)
st.caption(f"{len(receipts)} receipt(s) · total ${total_shown:,.2f}")
st.dataframe(
    table,
    hide_index=True,
    width="stretch",
    column_config={
        "receipt_id": st.column_config.NumberColumn("Receipt #", format="%d"),
        "vendor_name": "Supplier",
        "receipt_date": st.column_config.DateColumn("Date"),
        "receipt_number": "Receipt no.",
        "total": st.column_config.NumberColumn("Total", format="$%.2f"),
        "review_status": "Status",
        "items": "Items",
    },
)

# --- open one receipt --------------------------------------------------------------------
st.subheader("Open a receipt")


def label(row):
    total = f"${row['total']:,.2f}" if row["total"] is not None else "total ?"
    return f"Receipt #{row['receipt_id']} · {row['vendor_name'] or 'supplier ?'} · {row['receipt_date'] or 'date ?'} · {total}"


choice = st.selectbox("Receipt", receipts, format_func=label)
data = review.get_receipt(conn, choice["receipt_id"])

photo_col, items_col = st.columns([1, 1])
with photo_col:
    image_path = resolve_stored_path(data["stored_path"])
    if image_path.exists():
        st.image(image_path.read_bytes(), width="stretch")
    else:
        st.error("The photo for this receipt is missing.")
with items_col:
    receipt = data["receipt"]
    st.write(f"**Status:** {STATUS_LABELS[receipt['review_status']]}")
    st.write(f"**Supplier:** {receipt['vendor_name'] or '?'}  ·  **Date:** {receipt['receipt_date'] or '?'}  "
             f"·  **Receipt no.:** {receipt['receipt_number'] or '?'}")
    st.write(f"**Subtotal:** {review.as_text(receipt['subtotal']) or '?'}  ·  "
             f"**Tax:** {review.as_text(receipt['tax']) or '?'}  ·  **Total:** {review.as_text(receipt['total']) or '?'}")
    items = pd.DataFrame(
        [{field: review.as_text(line.get(field)) for field in review.LINE_FIELDS} for line in data["lines"]],
        columns=review.LINE_FIELDS,
    )
    st.dataframe(items, hide_index=True, width="stretch",
                 column_config={"description": "Item", "quantity": "Qty", "unit_raw": "Unit",
                                "unit_price": "Price", "line_total": "Amount"})
    st.caption("To fix or approve this receipt, open it on **Check receipts**.")
