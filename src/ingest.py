"""Ingestion: the ONLY way an image enters the system.

The inbox folder scan, the Streamlit upload tab and the camera tab all call
ingest_image_bytes(). That way validation and duplicate detection can't be skipped.

Run the inbox scan:
    python -m src.ingest
"""

import hashlib
import io
import logging
import shutil
import time
from datetime import datetime
from pathlib import Path

from PIL import Image

from src import config
from src.db import get_connection

logger = logging.getLogger(__name__)

MAX_BYTES = 10 * 1024 * 1024          # 10 MB
MAX_PIXELS = 50_000_000               # 50 megapixels is more than any phone photo needs
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
# Real file format (from the file's bytes) -> extension we save with
FORMAT_TO_EXT = {"JPEG": "jpg", "PNG": "png"}
SOURCES = {"inbox", "upload", "camera"}
INBOX_MIN_AGE_SECONDS = 10            # newer files may still be copying

# Pillow's own safety limit against "decompression bomb" images
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_image(data, original_name):
    """Check that the bytes are a real, reasonable JPG or PNG.

    Returns (extension, None) if OK, or (None, reason) if not.
    """
    if not data:
        return None, "empty file"
    if len(data) > MAX_BYTES:
        return None, "over 10 MB"

    # The name must claim to be JPG/PNG ...
    extension = Path(original_name or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        return None, "not a JPG or PNG file"

    # ... and the bytes must really be JPG/PNG (the name alone can lie)
    try:
        with Image.open(io.BytesIO(data)) as image:
            real_format = image.format
            width, height = image.size
            if real_format not in FORMAT_TO_EXT:
                return None, "not a JPG or PNG file"
            if width * height > MAX_PIXELS:
                return None, "image has too many pixels"
            image.verify()  # checks the file structure without decoding everything
    except Image.DecompressionBombError:
        return None, "image has too many pixels"
    except Exception:
        return None, "not a valid image"

    return FORMAT_TO_EXT[real_format], None


def safe_label(original_name):
    """Keep only the base file name, as a label. Never used to build a path."""
    name = Path(str(original_name or "")).name
    return name[:255] or None


def stored_path_text(path):
    """Store paths relative to the project root when possible (portable)."""
    try:
        return Path(path).resolve().relative_to(config.PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# The core intake function
# ---------------------------------------------------------------------------
def ingest_image_bytes(data, original_name, source, conn=None, raw_dir=None):
    """Validate, deduplicate and store one image.

    Returns one of:
        ("new", file_id)        stored and recorded
        ("duplicate", file_id)  same bytes already stored before
        ("rejected", reason)    not a valid JPG/PNG, too big, etc.
    """
    if source not in SOURCES:
        raise ValueError(f"unknown source: {source}")
    raw_dir = Path(raw_dir or config.RAW_DIR)

    extension, reason = validate_image(data, original_name)
    if reason:
        return "rejected", reason

    sha256 = hashlib.sha256(data).hexdigest()
    # Server-generated name: the hash. The original name is never a path.
    target = raw_dir / f"{sha256}.{extension}"

    own_connection = conn is None
    if own_connection:
        conn = get_connection()
    try:
        row = conn.execute(
            "SELECT file_id FROM raw.receipt_file WHERE sha256 = %s", (sha256,)
        ).fetchone()
        if row:
            _write_file_if_missing(target, data)   # repair if the copy was lost
            return "duplicate", row[0]

        _write_file_if_missing(target, data)
        row = conn.execute(
            """
            INSERT INTO raw.receipt_file (sha256, stored_path, original_name, source)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (sha256) DO NOTHING
            RETURNING file_id
            """,
            (sha256, stored_path_text(target), safe_label(original_name), source),
        ).fetchone()
        conn.commit()

        if row is None:
            # Another process inserted the same file a moment ago
            row = conn.execute(
                "SELECT file_id FROM raw.receipt_file WHERE sha256 = %s", (sha256,)
            ).fetchone()
            return "duplicate", row[0]

        logger.info("Ingested file_id=%s source=%s", row[0], source)
        return "new", row[0]
    finally:
        if own_connection:
            conn.close()


def _write_file_if_missing(target, data):
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(data)


# ---------------------------------------------------------------------------
# Inbox folder scan
# ---------------------------------------------------------------------------
def scan_inbox(conn=None, inbox_dir=None, raw_dir=None, failed_dir=None,
               min_age_seconds=INBOX_MIN_AGE_SECONDS):
    """Ingest every settled file in the inbox.

    - new / duplicate: the file is removed from the inbox (a copy is in data/raw/)
    - rejected:        the file is moved to data/failed/ and the reason is logged
    Returns a dict of counts.
    """
    inbox_dir = Path(inbox_dir or config.INBOX_DIR)
    failed_dir = Path(failed_dir or config.FAILED_DIR)
    counts = {"new": 0, "duplicate": 0, "rejected": 0, "skipped": 0}
    now = time.time()

    for path in sorted(inbox_dir.iterdir()):
        if not path.is_file() or path.name == ".gitkeep":
            continue
        if now - path.stat().st_mtime < min_age_seconds:
            counts["skipped"] += 1        # may still be copying; next run gets it
            continue

        status, value = ingest_image_bytes(
            path.read_bytes(), path.name, "inbox", conn=conn, raw_dir=raw_dir
        )
        counts[status] += 1
        if status == "rejected":
            move_to_failed(path, failed_dir)
            logger.warning("Rejected inbox file %s: %s", path.name, value)
        else:
            path.unlink()
    return counts


def move_to_failed(path, failed_dir):
    """Move a file to data/failed/ with a timestamp so names never clash."""
    failed_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    shutil.move(str(path), str(failed_dir / f"{stamp}_{path.name}"))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(scan_inbox())
