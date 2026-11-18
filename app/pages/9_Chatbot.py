"""Ask questions about purchases in plain English (read-only, approved data only).

Staff see the answer and the table; the developer also sees the SQL and
the technical reasons when something is blocked or fails.
"""

import app_common

app_common.setup_page("Ask a question")

import streamlit as st  # noqa: E402

from src import chatbot, config, gemini_client  # noqa: E402

conn = app_common.db()
developer = app_common.is_developer()
st.title("Ask a question")
st.write("Ask about approved receipts, for example: *How much did we spend on chicken breast?* "
         "or *Which supplier is cheapest for canola oil?*")

if not config.GEMINI_API_KEY:
    if developer:
        st.info("The chatbot needs a Gemini API key. Add GEMINI_API_KEY to .env and restart the app.")
    else:
        st.info("The question box isn't switched on yet. Ask the developer to set it up.")
    st.stop()

@st.cache_data(ttl=600, show_spinner=False)
def cached_sql(question, schema):
    """Remember the SQL for a question for 10 minutes: asking again is instant.
    (Only the SQL is remembered; the query always runs on the current data.)"""
    return chatbot.generate_sql(question, schema)


with st.form("ask"):
    question = st.text_input("Your question")
    asked = st.form_submit_button("Ask")

if asked and question.strip():
    with st.spinner("Looking it up..."):
        try:
            output = chatbot.ask(question.strip(), conn, sql_generator=cached_sql)
        except gemini_client.GeminiUnavailable:
            st.warning("The AI service is busy right now. Please try again in a minute.")
            st.stop()
        except Exception as error:
            st.error("Sorry, something went wrong. Try again in a minute."
                     + (f" ({type(error).__name__})" if developer else ""))
            st.stop()

    if output["blocked"]:
        st.error("Sorry, I can only look things up, not change anything. Try asking differently."
                 + (f" (blocked: {output['blocked']})" if developer else ""))
    elif output["error"]:
        st.error("Sorry, I couldn't answer that. Try asking in a different way."
                 + (f" ({output['error']})" if developer else ""))
    else:
        if output["result"].empty:
            st.info("Nothing found for that question. Only approved receipts can be searched; "
                    "receipt numbers are shown on the Check receipts page. To see a receipt's "
                    "photo, open it on Check receipts.")
            output["answer"] = None
        elif output["answer"]:
            st.success(output["answer"])
        if not output["result"].empty:
            st.dataframe(output["result"], hide_index=True, width="stretch")
        if not output["answer"] and developer:
            st.caption("Plain-English answers are off for real data (they would send the result "
                       "table to Gemini). Set ALLOW_EXTERNAL_AI_ON_PRIVATE=true to allow them.")

    if developer:
        st.code(output["sql"] or "", language="sql")
    elif output["sql"]:
        with st.expander("How this was looked up"):
            st.code(output["sql"], language="sql")
