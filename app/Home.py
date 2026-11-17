"""Home / Overview page of the receipts app.

Start the app (from the project folder):
    streamlit run app/Home.py
"""

import app_common

app_common.setup_page("Receipts")

import charts  # noqa: E402
import streamlit as st  # noqa: E402

from src import dashboard  # noqa: E402

conn = app_common.db()
st.title("🧾 Restaurant Receipts")
st.caption("Add Receipt · Review · Export · Items · Spending · Prices · Suppliers · OCR Evaluation "
           "(menu on the left)")

stats = dashboard.overview_stats(conn)

# --- spend and receipts ------------------------------------------------------------
st.subheader("Overview")
col1, col2, col3 = st.columns(3)
col1.metric("Approved spend", f"${stats['approved_spend']:,.2f}")
col2.metric("Receipts", stats["receipts"])
col3.metric("Images received", stats["files"])

# --- review status -------------------------------------------------------------------
st.subheader("Review status")
col1, col2, col3, col4 = st.columns(4)
col1.metric("Needs review", stats["needs_review"])
col2.metric("Pending", stats["pending"])
col3.metric("Approved", stats["approved"])
col4.metric("Rejected", stats["rejected"])
st.caption(f"Corrections made in review: {stats['corrections']} · "
           f"Images that could not be processed: {stats['failed_files']}")

# --- data quality ------------------------------------------------------------------------
st.subheader("Data quality")
failures = dashboard.dq_failures(conn)
if failures.empty:
    st.info("No quality checks have run yet.")
else:
    failing = failures[failures["failing"] > 0].copy()
    if failing.empty:
        st.success("Every receipt passes every check.")
    else:
        failing["check"] = failing["check_name"].str.replace("_", " ")
        chart = charts.bar_chart(failing, "check", "failing", value_title="Receipts failing")
        # failing is a count, not money: plain number format
        chart = chart.encode(x=charts.alt.X("failing:Q", title="Receipts failing"),
                             tooltip=["check", "failing", "checked"])
        st.altair_chart(chart, width="stretch")
    with st.expander("Table"):
        st.dataframe(failures, hide_index=True, width="stretch")
