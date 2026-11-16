"""Review receipts: see the image next to what was read, fix mistakes,
then approve or reject. Every edit is logged in clean.correction.
"""

import app_common

app_common.setup_page("Review", layout="wide")

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from src import review  # noqa: E402
from src.ocr import resolve_stored_path  # noqa: E402

STATUS_LABELS = {
    "needs_review": "⚠️ Needs review",
    "pending": "🕒 Pending approval",
    "approved": "✅ Approved",
    "rejected": "❌ Rejected",
}

conn = app_common.db()
st.title("Review receipts")

# --- pick a receipt ------------------------------------------------------------
status = st.radio("Show", list(STATUS_LABELS), format_func=STATUS_LABELS.get, horizontal=True)
receipts = review.list_receipts(conn, status)
if not receipts:
    st.info("No receipts here.")
    st.stop()


def receipt_label(row):
    receipt_id, vendor, receipt_date, total = row
    return f"#{receipt_id} · {vendor or '?'} · {receipt_date or '?'} · {total if total is not None else '?'}"


choice = st.selectbox("Receipt", receipts, format_func=receipt_label)
receipt_id = choice[0]
data = review.get_receipt(conn, receipt_id)
receipt = data["receipt"]

image_col, fields_col = st.columns([1, 1])

# --- left: the original image (bytes read from data/raw, never a public URL) ----
with image_col:
    image_path = resolve_stored_path(data["stored_path"])
    if image_path.exists():
        st.image(image_path.read_bytes(), width="stretch")
    else:
        st.error("The stored image file is missing.")

# --- right: checks, fields, lines --------------------------------------------------
with fields_col:
    failed = [(name, details) for name, passed, details in data["checks"] if not passed]
    if failed:
        for name, details in failed:
            st.error(f"**{name.replace('_', ' ')}**: {details}")
    elif data["checks"]:
        st.success("All quality checks passed.")

    with st.form(f"edit_{receipt_id}"):
        st.caption(f"Status: {STATUS_LABELS[receipt['review_status']]}")
        vendor = st.text_input("Vendor", receipt["vendor_name"] or "")
        receipt_date = st.text_input(
            "Date (YYYY-MM-DD)",
            receipt["receipt_date"].isoformat() if receipt["receipt_date"] else "",
            help=f"Read from receipt: {receipt['receipt_date_raw'] or 'nothing'}",
        )
        number = st.text_input("Receipt number", receipt["receipt_number"] or "")
        col1, col2, col3 = st.columns(3)
        subtotal = col1.text_input("Subtotal", review.as_text(receipt["subtotal"]))
        tax = col2.text_input("Tax", review.as_text(receipt["tax"]))
        total = col3.text_input("Total", review.as_text(receipt["total"]))

        st.write("Line items (add or delete rows if OCR missed or invented a line)")
        lines_df = pd.DataFrame(
            [{field: review.as_text(line.get(field)) for field in review.LINE_FIELDS}
             | {"line_no": line["line_no"]} for line in data["lines"]],
            columns=["line_no"] + review.LINE_FIELDS,
        )
        edited = st.data_editor(
            lines_df,
            num_rows="dynamic",
            hide_index=True,
            width="stretch",
            disabled=["line_no"],
            column_config={
                "line_no": st.column_config.NumberColumn("#", width="small"),
                "description": "Description",
                "quantity": "Qty",
                "unit_raw": "Unit",
                "unit_price": "Unit price",
                "line_total": "Amount",
            },
        )
        saved = st.form_submit_button("💾 Save changes")

    if saved:
        new_lines = []
        for row in edited.to_dict("records"):
            line_no = row.get("line_no")
            row["line_no"] = None if pd.isna(line_no) else int(line_no)
            new_lines.append({k: (None if (v is not None and pd.isna(v)) else v) for k, v in row.items()})
        new_header = {"vendor_name": vendor, "receipt_date": receipt_date, "receipt_number": number,
                      "subtotal": subtotal, "tax": tax, "total": total}
        changes = review.save_corrections(conn, receipt_id, new_header, new_lines)
        st.toast(f"Saved {changes} change(s)")
        st.rerun()

    # --- approve / reject -------------------------------------------------------------
    approve_col, reject_col, reopen_col = st.columns(3)
    if receipt["review_status"] in ("pending", "needs_review"):
        if approve_col.button("✅ Approve", type="primary", width="stretch"):
            review.set_review_status(conn, receipt_id, "approved")
            st.rerun()
        if reject_col.button("❌ Reject", width="stretch"):
            review.set_review_status(conn, receipt_id, "rejected")
            st.rerun()
        if failed:
            st.caption("Some checks failed. Fix the values above, or approve anyway if the receipt itself is wrong.")
    else:
        if reopen_col.button("↩️ Reopen for review", width="stretch"):
            review.set_review_status(conn, receipt_id, "pending")
            st.rerun()

    with st.expander(f"Change history ({len(data['corrections'])})"):
        if data["corrections"]:
            st.dataframe(
                pd.DataFrame(data["corrections"], columns=["when", "field", "old", "new"]),
                hide_index=True, width="stretch",
            )
        else:
            st.write("No changes yet.")
