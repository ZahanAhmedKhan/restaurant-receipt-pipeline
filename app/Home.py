"""Home page of the receipts app.

Start the app (from the project folder):
    streamlit run app/Home.py
"""

import app_common

app_common.setup_page("Receipts")

import streamlit as st  # noqa: E402

st.title("🧾 Restaurant Receipts")
st.write("Use the menu on the left:")
st.markdown(
    "- **Add Receipt**: take a photo or upload receipt images\n"
    "- **Review**: check what was read, fix mistakes, approve or reject\n"
    "- **Export**: download approved receipts as an Excel file"
)

# Small status overview: how many receipts are in each review state
rows = app_common.db().execute(
    "SELECT review_status, count(*) FROM clean.receipt GROUP BY review_status"
).fetchall()
counts = {status: count for status, count in rows}

col1, col2, col3, col4 = st.columns(4)
col1.metric("Needs review", counts.get("needs_review", 0))
col2.metric("Pending", counts.get("pending", 0))
col3.metric("Approved", counts.get("approved", 0))
col4.metric("Rejected", counts.get("rejected", 0))
