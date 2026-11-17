"""Supplier comparison: items we buy from 2+ suppliers, latest prices, ESTIMATED savings."""

import app_common

app_common.setup_page("Suppliers", layout="wide")

import streamlit as st  # noqa: E402

from src import prices  # noqa: E402

conn = app_common.db()
st.title("Supplier comparison")
st.warning(
    "**Estimated savings only.** They assume every purchase had been made at the cheapest "
    "supplier's latest price. They ignore delivery fees, order minimums, quality, pack sizes "
    "on offer and availability. Use them as a starting point for a conversation, not a promise."
)

savings = prices.supplier_savings(conn)
if savings.empty:
    st.info("No item has been bought from two or more suppliers yet (approved receipts only).")
    st.stop()

total = savings["estimated_monthly_savings"].sum()
col1, col2 = st.columns(2)
col1.metric("Items compared", len(savings))
col2.metric("Estimated monthly savings", f"${total:,.2f}")

st.subheader("By item")
st.dataframe(
    savings,
    hide_index=True,
    width="stretch",
    column_config={
        "item_name": "Item",
        "standard_unit": "Unit",
        "suppliers": "Suppliers",
        "cheapest_vendor": "Cheapest supplier",
        "cheapest_price": st.column_config.NumberColumn("Cheapest price / unit", format="$%.4f"),
        "estimated_monthly_savings": st.column_config.NumberColumn("Est. monthly savings", format="$%.2f"),
    },
)

st.subheader("Latest price at each supplier")
item = st.selectbox("Item", list(savings["item_name"]))
detail = prices.supplier_comparison(conn).query("item_name == @item")
st.dataframe(
    detail[["vendor_name", "latest_date", "latest_price", "price_difference",
            "avg_monthly_quantity", "estimated_monthly_savings"]],
    hide_index=True,
    width="stretch",
    column_config={
        "vendor_name": "Supplier",
        "latest_date": "Last bought",
        "latest_price": st.column_config.NumberColumn("Latest price / unit", format="$%.4f"),
        "price_difference": st.column_config.NumberColumn("Above cheapest", format="$%.4f"),
        "avg_monthly_quantity": "Avg monthly quantity",
        "estimated_monthly_savings": st.column_config.NumberColumn("Est. monthly savings", format="$%.2f"),
    },
)
