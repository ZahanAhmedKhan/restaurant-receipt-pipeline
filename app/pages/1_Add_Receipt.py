"""Add receipts: take a photo or upload image files.

Every image goes through ingest_image_bytes() (validation + duplicate check),
then OCR -> parse -> clean -> quality checks for that receipt.
"""

import app_common

app_common.setup_page("Add Receipt")

import streamlit as st  # noqa: E402

from src.run_pipeline import process_single_image  # noqa: E402

st.title("Add Receipt")


def show_result(result, name):
    """Show one friendly status message."""
    status = result["status"]
    if status == "new":
        st.success(f"✅ Saved, receipt #{result['receipt_id']}, sent to review ({name})")
    elif status == "duplicate":
        if result["receipt_id"]:
            st.warning(f"⚠️ Duplicate, already saved as receipt #{result['receipt_id']} ({name})")
        else:
            st.warning(f"⚠️ Duplicate, this image was already saved ({name})")
    elif status == "ocr_failed":
        st.error(f"❌ Saved, but the text could not be read. Try a sharper photo ({name})")
    else:
        st.error(f"❌ Rejected: {result['reason']} ({name})")


def submit(data, name, source):
    with st.spinner("Reading the receipt..."):
        result = process_single_image(app_common.db(), data, name, source)
    show_result(result, name)


photo_tab, upload_tab = st.tabs(["📷 Take Photo", "📁 Upload Receipt"])

# --- Take Photo ---------------------------------------------------------------
with photo_tab:
    photo = st.camera_input("Take a photo of the receipt")
    if photo is not None:
        st.image(photo, caption="Preview", width=300)
        if st.button("Submit photo", type="primary"):
            submit(photo.getvalue(), "camera.jpg", "camera")
    with st.expander("Camera not showing?"):
        st.markdown(
            "- Allow camera access when the browser asks (or in the browser's site settings).\n"
            "- On a phone, the page must be opened over **HTTPS** "
            "(see *Using on a phone* in the README).\n"
            "- You can always use the **Upload Receipt** tab instead."
        )

# --- Upload Receipt -------------------------------------------------------------
with upload_tab:
    st.info("📱 On a phone, this button also lets you take a photo with the main camera. "
            "That photo is usually sharper, which gives better results.")
    files = st.file_uploader(
        "Choose receipt images (JPG or PNG, up to 10 MB each)",
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=True,
    )
    if files:
        for uploaded in files:
            st.image(uploaded, caption=uploaded.name, width=300)
        if st.button(f"Submit {len(files)} receipt(s)", type="primary"):
            for uploaded in files:
                submit(uploaded.getvalue(), uploaded.name, "upload")
