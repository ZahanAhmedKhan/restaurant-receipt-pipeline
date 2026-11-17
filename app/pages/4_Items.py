"""Item mapping: see descriptions that have no rule yet and add rules."""

import app_common

app_common.setup_page("Items", layout="wide")

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from src import load_mart, normalize  # noqa: E402

conn = app_common.db()
st.title("Item mapping")
st.write("Rules turn messy receipt descriptions into standard items, so prices can be "
         "compared over time and across suppliers.")

# --- unmapped descriptions -----------------------------------------------------------
unmapped = normalize.unmapped_descriptions(conn)
st.subheader(f"Unmapped descriptions ({len(unmapped)})")
if unmapped:
    st.dataframe(pd.DataFrame(unmapped, columns=["description", "lines", "spend"]),
                 hide_index=True, width="stretch")
else:
    st.success("Every approved line is mapped to an item.")

# --- add a rule ---------------------------------------------------------------------------
st.subheader("Add a rule")
with st.form("add_rule", clear_on_submit=True):
    pattern = st.text_input("Description pattern", placeholder="%CHKN%BRST%",
                            help="% means 'any text'. Case doesn't matter.")
    col1, col2, col3 = st.columns(3)
    item_name = col1.text_input("Item name", placeholder="chicken breast")
    category = col2.text_input("Category", placeholder="Meat")
    standard_unit = col3.selectbox("Standard unit", ["lb", "each", "L", "kg"])
    col4, col5 = st.columns(2)
    pack_size = col4.number_input("Pack size (optional)", min_value=0.0, value=0.0,
                                  help="Leave 0 to read it from the description, e.g. 10LB")
    pack_unit = col5.selectbox("Pack unit", ["", "LB", "KG", "OZ", "CT", "DZ", "EA", "GAL", "L"])
    added = st.form_submit_button("Add rule")

if added:
    if not pattern.strip() or not item_name.strip():
        st.error("Pattern and item name are required.")
    else:
        try:
            normalize.add_rule(conn, pattern, item_name, category, standard_unit,
                               str(pack_size) if pack_size else None, pack_unit or None)
            load_mart.build_mart(conn)     # apply the new rule to the analytics
            st.success("Rule added and analytics updated.")
            st.rerun()
        except Exception as error:
            st.error(f"Could not add the rule ({type(error).__name__}). Is the pattern already used?")

# --- existing rules ---------------------------------------------------------------------------
st.subheader("Current rules")
st.dataframe(pd.DataFrame(normalize.load_rules(conn)), hide_index=True, width="stretch")
