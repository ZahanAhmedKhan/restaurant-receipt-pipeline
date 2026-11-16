"""Run the whole pipeline in order. Safe to rerun: every step skips work
that is already done.

    1. ingest   data/inbox/ -> data/raw/ + raw.receipt_file
    2. OCR      files with status 'new'      -> raw.ocr_run
    3. clean    files with status 'ocr_done' -> clean.receipt / clean.receipt_line
    4. quality  checks on the new receipts   -> dq.check_result, review_status

Usage:
    python -m src.run_pipeline              # process whatever is in data/inbox/
    python -m src.run_pipeline --sample     # first copy the fake receipts into the inbox
"""

import argparse
import logging
import shutil

from src import clean, config, ingest, ocr, quality
from src.db import get_connection

logger = logging.getLogger(__name__)


def copy_sample_to_inbox(sample_dir=None, inbox_dir=None):
    """Copy the fake sample images into the inbox (for demos and testing)."""
    sample_dir = sample_dir or config.SAMPLE_DIR
    inbox_dir = inbox_dir or config.INBOX_DIR
    inbox_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for path in sorted(sample_dir.iterdir()):
        if path.suffix.lower() in (".jpg", ".jpeg", ".png"):
            # copy2 keeps the old modified time, so the inbox scan
            # doesn't think the file is still being copied
            shutil.copy2(path, inbox_dir / path.name)
            count += 1
    return count


def run(conn=None, inbox_dir=None, raw_dir=None, failed_dir=None):
    """Run every step once. Returns a summary dict (counts only, no contents)."""
    own_connection = conn is None
    if own_connection:
        conn = get_connection()
    try:
        ingest_counts = ingest.scan_inbox(conn=conn, inbox_dir=inbox_dir,
                                          raw_dir=raw_dir, failed_dir=failed_dir)
        ocr_count = ocr.ocr_pending(conn)
        receipt_ids = clean.process_pending(conn)
        needs_review = 0
        for receipt_id in receipt_ids:
            results = quality.run_checks(conn, receipt_id)
            if not all(passed for passed, _ in results.values()):
                needs_review += 1
        summary = {
            "ingested_new": ingest_counts["new"],
            "duplicates": ingest_counts["duplicate"],
            "rejected": ingest_counts["rejected"],
            "skipped_still_copying": ingest_counts["skipped"],
            "ocr_runs": ocr_count,
            "receipts_loaded": len(receipt_ids),
            "needs_review": needs_review,
        }
        logger.info("Pipeline summary: %s", summary)
        return summary
    finally:
        if own_connection:
            conn.close()


def process_single_image(conn, data, original_name, source, raw_dir=None):
    """Run one image through every step right away (used by the capture page).

    Returns a dict:
        {"status": "new" | "duplicate" | "rejected" | "ocr_failed",
         "file_id": ..., "receipt_id": ..., "reason": ..., "needs_review": bool}
    """
    status, value = ingest.ingest_image_bytes(data, original_name, source, conn=conn,
                                              raw_dir=raw_dir)
    result = {"status": status, "file_id": None, "receipt_id": None,
              "reason": None, "needs_review": False}

    if status == "rejected":
        result["reason"] = value
        return result

    file_id = value
    result["file_id"] = file_id
    if status == "duplicate":
        row = conn.execute("SELECT receipt_id FROM clean.receipt WHERE file_id = %s",
                           (file_id,)).fetchone()
        result["receipt_id"] = row[0] if row else None
        return result

    ocr.ocr_file(conn, file_id)
    file_status = conn.execute("SELECT status FROM raw.receipt_file WHERE file_id = %s",
                               (file_id,)).fetchone()[0]
    if file_status != "ocr_done":
        result["status"] = "ocr_failed"
        return result

    receipt_id = clean.process_file(conn, file_id)
    checks = quality.run_checks(conn, receipt_id)
    result["receipt_id"] = receipt_id
    result["needs_review"] = not all(passed for passed, _ in checks.values())
    return result


def main():
    parser = argparse.ArgumentParser(description="Run the receipt pipeline.")
    parser.add_argument("--sample", action="store_true",
                        help="copy the fake sample receipts into the inbox first")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.sample:
        print(f"Copied {copy_sample_to_inbox()} sample images into the inbox")
    print(run())


if __name__ == "__main__":
    main()
