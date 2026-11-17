"""Ask questions about purchases in plain English (read-only, approved data only)."""

import app_common

app_common.setup_page("Chatbot", layout="wide")

import streamlit as st  # noqa: E402

from src import chatbot, config  # noqa: E402

conn = app_common.db()
st.title("Ask about your purchases")
st.caption("Questions are turned into SQL by Gemini. Only the table structure and your question are "
           "sent, never receipt data. The query runs read-only on approved receipts.")

if not config.GEMINI_API_KEY:
    st.info("The chatbot needs a Gemini API key. Add GEMINI_API_KEY to .env and restart the app.")
    st.stop()

with st.form("ask"):
    question = st.text_input("Question", placeholder="How much did we spend with each vendor last month?")
    asked = st.form_submit_button("Ask")

if asked and question.strip():
    with st.spinner("Thinking..."):
        try:
            output = chatbot.ask(question.strip(), conn)
        except Exception as error:
            st.error(f"Could not get an answer ({type(error).__name__}).")
            st.stop()

    if output["answer"]:
        st.success(output["answer"])
    st.code(output["sql"] or "", language="sql")
    if output["blocked"]:
        st.error(f"Blocked for safety: {output['blocked']}")
    elif output["error"]:
        st.error(f"The query failed ({output['error']}). Try rephrasing the question.")
    else:
        st.dataframe(output["result"], hide_index=True, width="stretch")
        if not output["answer"]:
            st.caption("Plain-English answers are off for real data (they would send the result "
                       "table to Gemini). Set ALLOW_EXTERNAL_AI_ON_PRIVATE=true to allow them.")
