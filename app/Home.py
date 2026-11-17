"""Entry point of the receipts app: log in, then show the menu for that password.

Start the app (from the project folder):
    streamlit run app/Home.py

Staff password     -> Start, Add receipt, Check receipts, Excel, Ask a question
Developer password -> everything (daily pages + analytics + setup)
"""

import app_common

app_common.setup_page("Receipts")

import streamlit as st  # noqa: E402

# Pages everyone uses, with plain names
start = st.Page("pages/Start.py", title="Start", icon="🏠", default=True)
add = st.Page("pages/1_Add_Receipt.py", title="Add receipt", icon="📷")
check = st.Page("pages/2_Review.py", title="Check receipts", icon="✅")
excel = st.Page("pages/3_Export.py", title="Excel", icon="📊")
ask = st.Page("pages/9_Chatbot.py", title="Ask a question", icon="💬")
daily = [start, add, check, excel, ask]

if app_common.is_developer():
    menu = {
        "Daily use": daily,
        "Analytics": [
            st.Page("pages/0_Overview.py", title="Overview", icon="📋"),
            st.Page("pages/5_Spending.py", title="Spending", icon="💵"),
            st.Page("pages/6_Prices.py", title="Prices", icon="📈"),
            st.Page("pages/7_Suppliers.py", title="Suppliers", icon="🚚"),
        ],
        "Setup and quality": [
            st.Page("pages/4_Items.py", title="Item rules", icon="🏷️"),
            st.Page("pages/8_OCR_Evaluation.py", title="OCR evaluation", icon="🔍"),
        ],
    }
else:
    menu = daily

app_common.logout_button()
st.navigation(menu).run()
