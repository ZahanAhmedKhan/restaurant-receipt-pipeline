"""Download approved receipts as an Excel file."""

from datetime import date

import app_common

app_common.setup_page("Export")

import streamlit as st  # noqa: E402

from src.export_excel import build_workbook  # noqa: E402

st.title("Export to Excel")
st.write("Approved receipts only. Three sheets: Receipts, Lines and Summary "
         "(spend by vendor and month).")

content, receipt_count = build_workbook(app_common.db())
if receipt_count == 0:
    st.info("No approved receipts yet. Approve receipts on the Review page first.")
else:
    st.metric("Approved receipts", receipt_count)
    st.download_button(
        "⬇️ Download Excel file",
        data=content,
        file_name=f"receipts_{date.today().isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )
