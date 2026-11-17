"""Spending by month, vendor and item (approved receipts), with a date filter."""

import app_common

app_common.setup_page("Spending", layout="wide", developer_only=True)

import charts  # noqa: E402
import streamlit as st  # noqa: E402

from src import dashboard  # noqa: E402

conn = app_common.db()
st.title("Spending")

first, last = dashboard.date_range(conn)
if first is None:
    st.info("No approved receipts yet.")
    st.stop()

# Filters in one row above the charts
picked = st.date_input("Dates", value=(first, last), min_value=first, max_value=last)
if len(picked) != 2:
    st.stop()                      # the user has picked only the start date so far
start, end = picked
vendors = dashboard.all_vendors(conn)

by_month = dashboard.spend_by_month(conn, start, end)
by_vendor = dashboard.spend_by_vendor(conn, start, end)
by_item = dashboard.spend_by_item(conn, start, end)

st.metric("Spend in this period", f"${by_vendor['spend'].sum():,.2f}")

st.subheader("By month")
st.altair_chart(charts.stacked_month_bars(by_month, vendors), width="stretch")
with st.expander("Table"):
    st.dataframe(by_month, hide_index=True, width="stretch")

left, right = st.columns(2)
with left:
    st.subheader("By vendor")
    st.altair_chart(charts.bar_chart(by_vendor, "vendor_name", "spend"), width="stretch")
    with st.expander("Table"):
        st.dataframe(by_vendor, hide_index=True, width="stretch")
with right:
    st.subheader("Top items")
    st.altair_chart(charts.bar_chart(by_item, "item_name", "spend"), width="stretch")
    with st.expander("Table"):
        st.dataframe(by_item, hide_index=True, width="stretch")
