"""Shared setup for every Streamlit page.

Each page starts with:
    import app_common
    app_common.setup_page("Page title")
which sets the layout and asks for the app password.
"""

import sys
from pathlib import Path

# Let pages import from src/ (the project root is the folder above app/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402

from src import config  # noqa: E402
from src.auth import verify_password  # noqa: E402
from src.db import get_connection  # noqa: E402


def setup_page(title):
    """Page settings + password gate. Stops the page if not logged in."""
    st.set_page_config(page_title=title, page_icon="🧾", layout="centered")
    require_password()


def require_password():
    if st.session_state.get("authenticated"):
        return

    if not config.APP_PASSWORD_HASH:
        st.error("No app password is set. In a terminal run: "
                 "`python scripts\\set_app_password.py`, then restart the app.")
        st.stop()

    st.title("🧾 Receipts")
    with st.form("login"):
        password = st.text_input("App password", type="password")
        submitted = st.form_submit_button("Log in")
    if submitted:
        if verify_password(password, config.APP_PASSWORD_HASH):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Wrong password.")
    st.stop()


@st.cache_resource
def get_db():
    """One database connection shared by the app (opened once)."""
    return get_connection()


def db():
    """Return a working connection, reconnecting if the old one was closed."""
    conn = get_db()
    if conn.closed:
        get_db.clear()
        conn = get_db()
    return conn
