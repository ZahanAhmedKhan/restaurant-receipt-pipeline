"""Start page for staff: what to do next, in plain words."""

import app_common

app_common.setup_page("Start")

import streamlit as st  # noqa: E402

from src import dashboard  # noqa: E402

stats = dashboard.overview_stats(app_common.db())
waiting = stats["needs_review"] + stats["pending"]

st.title("🧾 Receipts")

if waiting:
    st.warning(f"**{waiting} receipt(s) are waiting for you to check.**")
else:
    st.success("All receipts are checked. 👍")

st.write("What do you want to do?")
st.page_link("pages/1_Add_Receipt.py", label="Add a receipt (photo or file)", icon="📷")
st.page_link("pages/2_Review.py", label="Check and approve receipts", icon="✅")
st.page_link("pages/All_Receipts.py", label="See all receipts", icon="🗂️")
st.page_link("pages/3_Export.py", label="Download the Excel file", icon="📊")
st.page_link("pages/9_Chatbot.py", label="Ask a question about purchases", icon="💬")

with st.expander("How it works"):
    st.markdown(
        "1. **Add a receipt**: take a photo or choose a picture. A long receipt can be several photos.\n"
        "2. **Check it**: the computer reads the receipt. Compare what it read with the photo, "
        "fix anything wrong, then press **Approve**.\n"
        "3. **Excel**: approved receipts go into the Excel file.\n"
        "4. **Ask**: type a question like *How much did we spend on chicken this month?*"
    )
