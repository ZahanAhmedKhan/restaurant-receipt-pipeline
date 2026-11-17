"""OCR step: read receipts from stored images.

Two methods, results stored in raw.ocr_run:
    tesseract (default): free, offline, returns plain text -> parse.py
    gemini (optional):   Google Gemini returns structured JSON directly.
                         Used only when OCR_METHOD=gemini AND GEMINI_API_KEY is set.

Privacy: Gemini is an external service. It only receives the fake sample
receipts, unless ALLOW_EXTERNAL_AI_ON_PRIVATE=true is set in .env.

Run OCR on every file that hasn't been read yet:
    python -m src.ocr
"""

import hashlib
import json
import logging
import time
from functools import lru_cache

import pytesseract
from PIL import Image
from psycopg.types.json import Jsonb

from src import config
from src.db import get_connection

logger = logging.getLogger(__name__)

# --psm 6 = "treat the image as one block of text". On our receipts it scored
# best of the page modes we tried. Grayscale/upscaling did not clearly help,
# so we pass the image as it is.
TESSERACT_OPTIONS = "--psm 6"

if config.TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD


class PrivateDataError(Exception):
    """Raised when a real (non-sample) receipt would be sent to an external API."""


# ---------------------------------------------------------------------------
# Tesseract
# ---------------------------------------------------------------------------
def run_tesseract(path):
    """Read text from one image file. Returns {"text": str, "duration_ms": int}."""
    start = time.perf_counter()
    with Image.open(path) as image:
        text = pytesseract.image_to_string(image, config=TESSERACT_OPTIONS)
    duration_ms = int((time.perf_counter() - start) * 1000)
    return {"text": text, "duration_ms": duration_ms}


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------
GEMINI_PROMPT = """You read supplier receipts for a restaurant.
Return the receipt as JSON with exactly these keys:
vendor, date, receipt_number, lines, subtotal, tax, total.
Each item in "lines" has: description, quantity, unit, unit_price, line_total.
Copy every value exactly as printed (text, not numbers; money with 2 decimals, no $ sign).
The vendor is the business name at the top. Do not include the address or phone number.
If a value is missing or unreadable, use null. Never guess or calculate values."""

# JSON schema the answer must follow (same structure as parse.py output)
TEXT_OR_NULL = {"type": "STRING", "nullable": True}
GEMINI_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "vendor": TEXT_OR_NULL,
        "date": TEXT_OR_NULL,
        "receipt_number": TEXT_OR_NULL,
        "lines": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "description": TEXT_OR_NULL,
                    "quantity": TEXT_OR_NULL,
                    "unit": TEXT_OR_NULL,
                    "unit_price": TEXT_OR_NULL,
                    "line_total": TEXT_OR_NULL,
                },
            },
        },
        "subtotal": TEXT_OR_NULL,
        "tax": TEXT_OR_NULL,
        "total": TEXT_OR_NULL,
    },
    "required": ["vendor", "date", "receipt_number", "lines", "subtotal", "tax", "total"],
}

HEADER_KEYS = ["vendor", "date", "receipt_number", "subtotal", "tax", "total"]
LINE_KEYS = ["description", "quantity", "unit", "unit_price", "line_total"]


def file_sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def sample_hashes():
    """Hashes of the fake sample images (the only images Gemini may see by default)."""
    hashes = set()
    for path in config.SAMPLE_DIR.iterdir():
        if path.suffix.lower() in (".jpg", ".jpeg", ".png"):
            hashes.add(file_sha256(path))
    return frozenset(hashes)


def check_allowed_for_external_ai(path):
    """Raise PrivateDataError unless this image is a fake sample receipt
    (by hash, wherever it is stored) or the owner allowed real data."""
    if config.ALLOW_EXTERNAL_AI_ON_PRIVATE:
        return
    if file_sha256(path) not in sample_hashes():
        raise PrivateDataError("external AI is only allowed on sample receipts")


def _call_gemini(image_bytes, mime_type):
    """The only function that talks to the Gemini API. Returns the JSON text.
    Tests replace this function, so they never call the real API."""
    from google import genai               # imported here: only needed for Gemini
    from google.genai import types

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=[types.Part.from_bytes(data=image_bytes, mime_type=mime_type), GEMINI_PROMPT],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=GEMINI_SCHEMA,
            temperature=0,
        ),
    )
    return response.text


def _as_text(value):
    """Make every value a trimmed string (or None), like parse.py output."""
    if value is None:
        return None
    text = str(value).strip().replace("$", "")
    return text or None


def normalize_gemini_json(data):
    """Keep only the expected keys, with string-or-None values."""
    result = {key: _as_text(data.get(key)) for key in HEADER_KEYS}
    result["lines"] = []
    for line in data.get("lines") or []:
        result["lines"].append({key: _as_text(line.get(key)) for key in LINE_KEYS})
    return result


def run_gemini(path):
    """Ask Gemini for the receipt as JSON. Returns {"json": dict, "duration_ms": int}."""
    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set")
    check_allowed_for_external_ai(path)

    mime_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    start = time.perf_counter()
    answer = _call_gemini(path.read_bytes(), mime_type)
    duration_ms = int((time.perf_counter() - start) * 1000)
    return {"json": normalize_gemini_json(json.loads(answer)), "duration_ms": duration_ms}


def gemini_enabled():
    return config.OCR_METHOD == "gemini" and bool(config.GEMINI_API_KEY)


# ---------------------------------------------------------------------------
# Storing results
# ---------------------------------------------------------------------------
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
        # Jsonb() tells psycopg to send the dict as a JSONB value
        (file_id, method, raw_text, Jsonb(raw_json) if raw_json is not None else None,
         duration_ms, error),
    ).fetchone()
    return row[0]


def set_file_status(conn, file_id, status):
    conn.execute(
        "UPDATE raw.receipt_file SET status = %s WHERE file_id = %s", (status, file_id)
    )


def _extract(path, method):
    """Run one method. Returns (method actually used, raw_text, raw_json, duration_ms)."""
    if method == "gemini":
        try:
            result = run_gemini(path)
            return "gemini", None, result["json"], result["duration_ms"]
        except PrivateDataError:
            # Real receipt and no permission to send it out: stay local
            logger.info("Gemini not allowed for this file; using Tesseract")
    result = run_tesseract(path)
    return "tesseract", result["text"], None, result["duration_ms"]


def ocr_file(conn, file_id, method=None):
    """Run OCR on one stored file and record the result.

    method: "tesseract" or "gemini"; by default Gemini only if enabled in .env.
    Returns the new ocr_run_id. On failure the error type is stored
    (never the receipt contents) and the file is marked 'failed'.
    """
    if method is None:
        method = "gemini" if gemini_enabled() else "tesseract"
    row = conn.execute(
        "SELECT stored_path FROM raw.receipt_file WHERE file_id = %s", (file_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"no file with file_id={file_id}")
    path = resolve_stored_path(row[0])

    try:
        used, raw_text, raw_json, duration_ms = _extract(path, method)
        with conn.transaction():   # OCR row and status change saved together
            ocr_run_id = save_ocr_run(conn, file_id, used, raw_text=raw_text,
                                      raw_json=raw_json, duration_ms=duration_ms)
            set_file_status(conn, file_id, "ocr_done")
        logger.info("OCR done file_id=%s ocr_run_id=%s method=%s", file_id, ocr_run_id, used)
    except Exception as error:
        ocr_run_id = save_ocr_run(conn, file_id, method, error=type(error).__name__)
        set_file_status(conn, file_id, "failed")
        logger.warning("OCR failed file_id=%s error=%s", file_id, type(error).__name__)
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
