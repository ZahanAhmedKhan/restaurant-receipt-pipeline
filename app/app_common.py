"""Shared setup for every Streamlit page.

Each page starts with:
    import app_common
    app_common.setup_page("Page title")                        # staff + developer
    app_common.setup_page("Page title", developer_only=True)   # developer only
which sets the layout and asks for a password if nobody is logged in.

Two passwords, two views (see src/auth.py): the role is kept in
st.session_state["role"] ("staff" or "developer").
"""

import sys
from pathlib import Path

# Let pages import from src/ (the project root is the folder above app/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402

from src import config  # noqa: E402
from src.auth import DEVELOPER, STAFF, role_for_password  # noqa: E402
from src.db import get_connection  # noqa: E402


def setup_page(title, layout="centered", developer_only=False):
    """Page settings + password gate. Stops the page if not allowed.

    "centered" works best on phones; wide pages are for the developer views.
    """
    st.set_page_config(page_title=title, page_icon="🧾", layout=layout)
    require_login()
    if developer_only and not is_developer():
        st.error("This page is only for the developer account.")
        st.stop()


def current_role():
    return st.session_state.get("role")


def is_developer():
    return current_role() == DEVELOPER


def require_login():
    if current_role() in (STAFF, DEVELOPER):
        return

    if not config.APP_PASSWORD_HASH and not config.DEVELOPER_PASSWORD_HASH:
        st.error("No app password is set. In a terminal run: "
                 "`python scripts\\set_app_password.py`, then restart the app.")
        st.stop()

    st.title("🧾 Receipts")
    with st.form("login"):
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")
    if submitted:
        role = role_for_password(password, config.APP_PASSWORD_HASH,
                                 config.DEVELOPER_PASSWORD_HASH)
        if role:
            st.session_state["role"] = role
            st.rerun()
        else:
            st.error("Wrong password.")
    st.stop()


def logout_button():
    """A small 'Log out' button in the sidebar."""
    label = "Developer" if is_developer() else "Staff"
    st.sidebar.caption(f"Logged in: {label}")
    if st.sidebar.button("Log out"):
        st.session_state.clear()
        st.rerun()


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
