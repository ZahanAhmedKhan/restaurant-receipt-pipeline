"""OCR step: read the text from stored receipt images.

Tesseract is the default (free, offline). Results go to raw.ocr_run.

Run OCR on every file that hasn't been read yet:
    python -m src.ocr
"""

import logging
import time

import pytesseract
from PIL import Image

from src import config
from src.db import get_connection

logger = logging.getLogger(__name__)

# --psm 6 = "treat the image as one block of text". On our receipts it scored
# best of the page modes we tried. Grayscale/upscaling did not clearly help,
# so we pass the image as it is.
TESSERACT_OPTIONS = "--psm 6"

if config.TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD


def run_tesseract(path):
    """Read text from one image file. Returns {"text": str, "duration_ms": int}."""
    start = time.perf_counter()
    with Image.open(path) as image:
        text = pytesseract.image_to_string(image, config=TESSERACT_OPTIONS)
    duration_ms = int((time.perf_counter() - start) * 1000)
    return {"text": text, "duration_ms": duration_ms}


def resolve_stored_path(stored_path):
    """stored_path is relative to the project root unless it is absolute.

    (pathlib: root / "C:/x/y" gives "C:/x/y", so absolute paths stay as they are.)
    """
    return config.PROJECT_ROOT / stored_path


def save_ocr_run(conn, file_id, method, raw_text=None, raw_json=None,
                 duration_ms=None, error=None):
    """Insert one row into raw.ocr_run and return its ocr_run_id."""
    row = conn.execute(
        """
        INSERT INTO raw.ocr_run (file_id, method, raw_text, raw_json, duration_ms, error)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING ocr_run_id
        """,
        (file_id, method, raw_text, raw_json, duration_ms, error),
    ).fetchone()
    return row[0]


def set_file_status(conn, file_id, status):
    conn.execute(
        "UPDATE raw.receipt_file SET status = %s WHERE file_id = %s", (status, file_id)
    )


def ocr_file(conn, file_id, method=None):
    """Run OCR on one stored file and record the result.

    Returns the new ocr_run_id. On failure the error type is stored
    (never the receipt contents) and the file is marked 'failed'.
    """
    method = method or "tesseract"
    row = conn.execute(
        "SELECT stored_path FROM raw.receipt_file WHERE file_id = %s", (file_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"no file with file_id={file_id}")
    path = resolve_stored_path(row[0])

    try:
        result = run_tesseract(path)
        ocr_run_id = save_ocr_run(conn, file_id, "tesseract", raw_text=result["text"],
                                  duration_ms=result["duration_ms"])
        set_file_status(conn, file_id, "ocr_done")
        logger.info("OCR done file_id=%s ocr_run_id=%s method=%s", file_id, ocr_run_id, method)
    except Exception as error:
        conn.rollback()
        ocr_run_id = save_ocr_run(conn, file_id, method, error=type(error).__name__)
        set_file_status(conn, file_id, "failed")
        logger.warning("OCR failed file_id=%s error=%s", file_id, type(error).__name__)
    conn.commit()
    return ocr_run_id


def ocr_pending(conn=None):
    """Run OCR on every file with status 'new'. Returns the number processed."""
    own_connection = conn is None
    if own_connection:
        conn = get_connection()
    try:
        file_ids = [
            row[0]
            for row in conn.execute(
                "SELECT file_id FROM raw.receipt_file WHERE status = 'new' ORDER BY file_id"
            ).fetchall()
        ]
        for file_id in file_ids:
            ocr_file(conn, file_id)
        return len(file_ids)
    finally:
        if own_connection:
            conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(f"OCR'd {ocr_pending()} file(s)")
