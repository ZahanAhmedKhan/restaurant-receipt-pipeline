"""Price history per item and alerts for big price increases."""

import app_common

app_common.setup_page("Prices", layout="wide", developer_only=True)

import charts  # noqa: E402
import streamlit as st  # noqa: E402

from src import dashboard, prices  # noqa: E402

conn = app_common.db()
st.title("Prices")

# --- alerts -----------------------------------------------------------------------------
threshold = prices.alert_threshold(conn)
alerts = prices.price_alerts(conn)
st.subheader(f"⚠️ Price increases above {threshold:g}%")
if alerts.empty:
    st.success("No price increases above the threshold.")
else:
    st.dataframe(
        alerts[["purchase_date", "item_name", "vendor_name", "previous_price", "unit_price",
                "pct_change", "standard_unit"]],
        hide_index=True,
        width="stretch",
        column_config={
            "purchase_date": "Date", "item_name": "Item", "vendor_name": "Vendor",
            "previous_price": st.column_config.NumberColumn("Previous price", format="$%.4f"),
            "unit_price": st.column_config.NumberColumn("New price", format="$%.4f"),
            "pct_change": st.column_config.NumberColumn("Change", format="%.1f%%"),
            "standard_unit": "Per",
        },
    )
st.caption("The threshold is PRICE_ALERT_THRESHOLD_PCT in .env (applied on the next mart rebuild).")

# --- history ------------------------------------------------------------------------------
st.subheader("Price history")
history = prices.price_history(conn)
if history.empty:
    st.info("No price history yet (needs approved receipts with mapped items).")
    st.stop()

items = sorted(history["item_name"].unique())
default = items.index(alerts["item_name"].iloc[0]) if not alerts.empty else 0
item = st.selectbox("Item", items, index=default)
item_history = history[history["item_name"] == item]
unit = item_history["standard_unit"].iloc[0]

st.altair_chart(charts.price_lines(item_history, dashboard.all_vendors(conn), unit),
                width="stretch")
with st.expander("Table"):
    st.dataframe(item_history, hide_index=True, width="stretch")
