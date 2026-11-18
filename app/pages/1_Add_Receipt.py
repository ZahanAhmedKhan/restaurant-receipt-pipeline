"""Add receipts: take a photo or upload image files.

A receipt can be ONE photo, or SEVERAL photos of one long receipt (joined
top to bottom into one image, like a document scanner app).
Every image goes through ingest_image_bytes() (validation + duplicate check),
then OCR -> parse -> clean -> quality checks for that receipt.
"""

import app_common

app_common.setup_page("Add Receipt")

import hashlib  # noqa: E402

import streamlit as st  # noqa: E402

from src.run_pipeline import process_multi_image, process_single_image  # noqa: E402

st.title("Add Receipt")

SINGLE = "One photo = one receipt"
MULTI = "Several photos = one long receipt"
LONG_RECEIPT_TIPS = (
    "Photograph the receipt **from top to bottom**. Start each photo where the previous one "
    "ended. **Try not to overlap**: a line that appears in two photos is counted twice "
    "(the Review page will flag it if the lines don't add up)."
)


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
    elif status == "wrong_country":
        st.error(f"❌ Rejected: this receipt is not from Canada ({result['reason']}). "
                 f"Saved as receipt #{result['receipt_id']} with status Rejected ({name})")
    elif status == "ocr_failed":
        st.error(f"❌ Saved, but the text could not be read. Try a sharper photo ({name})")
    else:
        st.error(f"❌ Rejected: {result['reason']} ({name})")


def submit_single(data, name, source):
    with st.spinner("Reading the receipt..."):
        result = process_single_image(app_common.db(), data, name, source)
    show_result(result, name)


def submit_multi(parts, source):
    """parts: list of (bytes, name) in order, top of the receipt first."""
    label = f"long receipt, {len(parts)} photos"
    with st.spinner("Joining the photos and reading the receipt..."):
        result = process_multi_image(app_common.db(), parts, source)
    show_result(result, label)
    return result


photo_tab, upload_tab = st.tabs(["📷 Take Photo", "📁 Upload Receipt"])

# --- Take Photo ---------------------------------------------------------------
with photo_tab:
    camera_mode = st.radio("Receipt", [SINGLE, MULTI], key="camera_mode", horizontal=True)
    photo = st.camera_input("Take a photo of the receipt")

    if camera_mode == SINGLE:
        if photo is not None:
            st.image(photo, caption="Preview", width=300)
            if st.button("Submit photo", type="primary"):
                submit_single(photo.getvalue(), "camera.jpg", "camera")
    else:
        st.caption(LONG_RECEIPT_TIPS + " After adding a photo, press **Clear photo** on the "
                   "camera to take the next one.")
        parts = st.session_state.setdefault("camera_parts", [])

        if photo is not None:
            data = photo.getvalue()
            already_added = any(hashlib.sha256(data).digest() == hashlib.sha256(p).digest()
                                for p in parts)
            if already_added:
                st.info("This photo is already part of the receipt. Press **Clear photo** "
                        "to take the next one.")
            elif st.button(f"➕ Add as photo {len(parts) + 1}"):
                parts.append(data)
                st.rerun()

        if parts:
            st.write(f"**Photos in this receipt: {len(parts)}** (top to bottom)")
            columns = st.columns(min(len(parts), 4))
            for number, data in enumerate(parts, start=1):
                columns[(number - 1) % len(columns)].image(data, caption=f"Photo {number}", width=150)
            remove_col, reset_col = st.columns(2)
            if remove_col.button("↩️ Remove last photo"):
                parts.pop()
                st.rerun()
            if reset_col.button("🗑️ Start over"):
                parts.clear()
                st.rerun()
            if len(parts) >= 2 and st.button(f"Submit receipt ({len(parts)} photos)", type="primary"):
                result = submit_multi([(data, "camera.jpg") for data in parts], "camera")
                if result["status"] in ("new", "duplicate"):
                    parts.clear()          # ready for the next receipt
            elif len(parts) == 1:
                st.caption("Add at least one more photo, or switch to 'One photo = one receipt'.")

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
    upload_mode = st.radio("The selected images are", [SINGLE, MULTI], key="upload_mode",
                           horizontal=True)
    if upload_mode == MULTI:
        st.caption(LONG_RECEIPT_TIPS + " Select the photos **in order**; they are joined in the "
                   "order shown below.")
    files = st.file_uploader(
        "Choose receipt images (JPG or PNG, up to 10 MB each)",
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=True,
    )
    if files:
        for number, uploaded in enumerate(files, start=1):
            caption = f"Photo {number}: {uploaded.name}" if upload_mode == MULTI else uploaded.name
            st.image(uploaded, caption=caption, width=300)

        if upload_mode == SINGLE:
            if st.button(f"Submit {len(files)} receipt(s)", type="primary"):
                for uploaded in files:
                    submit_single(uploaded.getvalue(), uploaded.name, "upload")
        elif len(files) < 2:
            st.caption("Choose at least 2 photos for a long receipt.")
        elif st.button(f"Submit 1 receipt ({len(files)} photos)", type="primary"):
            submit_multi([(f.getvalue(), f.name) for f in files], "upload")
