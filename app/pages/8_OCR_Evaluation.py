"""OCR evaluation results (measured by src/evaluate_ocr.py on the sample receipts)."""

import app_common

app_common.setup_page("OCR Evaluation", developer_only=True)

import streamlit as st  # noqa: E402

from src import dashboard  # noqa: E402

st.title("OCR evaluation")
st.write("How well each method read the 51 fake sample receipts, compared with their "
         "ground truth. These numbers were measured by `python -m src.evaluate_ocr`.")

results = dashboard.ocr_results()
if results.empty:
    st.info("No evaluation yet. Run `python -m src.evaluate_ocr` in a terminal.")
    st.stop()

st.dataframe(results.astype(str), width="stretch")
if "gemini" not in results.columns:
    st.caption("Gemini not evaluated yet: add GEMINI_API_KEY to .env and run "
               "`python -m src.evaluate_ocr --method gemini`.")

with st.expander("How it is measured"):
    st.markdown(
        "- Same code as the pipeline: OCR (or Gemini), then parsing and cleaning.\n"
        "- Header fields must match exactly after standardization; the total within $0.01.\n"
        "- Lines are paired by description similarity, then quantity, unit price and line total "
        "are compared.\n"
        "- The fake receipts are cleaner than real photos, so real accuracy will be lower.\n"
        "- Full details: `docs/ocr_evaluation.md`."
    )
