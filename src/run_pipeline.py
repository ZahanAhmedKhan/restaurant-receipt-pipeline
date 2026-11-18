"""Run the whole pipeline in order. Safe to rerun: every step skips work
that is already done.

    1. ingest   data/inbox/ -> data/raw/ + raw.receipt_file
    2. OCR      files with status 'new'      -> raw.ocr_run
    3. clean    files with status 'ocr_done' -> clean.receipt / clean.receipt_line
    4. quality  checks on the new receipts   -> dq.check_result, review_status
    5. mart     rebuild the star schema from approved receipts

Usage:
    python -m src.run_pipeline              # process whatever is in data/inbox/
    python -m src.run_pipeline --sample     # first copy the fake receipts into the inbox

Scheduled runs (Windows Task Scheduler, see README): a lock file stops two runs
from overlapping, and everything is logged to logs/pipeline.log.
Exit codes: 0 = done, 1 = error, 2 = skipped because another run is going.
"""

import argparse
import logging
import os
import shutil
import sys
import time
from logging.handlers import RotatingFileHandler

from src import clean, config, ingest, load_mart, ocr, quality
from src.db import get_connection

logger = logging.getLogger(__name__)

LOCK_FILE = config.PROJECT_ROOT / "pipeline.lock"
LOG_FILE = config.LOGS_DIR / "pipeline.log"
# A lock older than this is left over from a crashed run and can be removed
STALE_LOCK_SECONDS = 2 * 60 * 60


class PipelineLock:
    """A lock file that only one run can hold at a time.

    with PipelineLock() as got_it:
        if got_it: ...   # we are the only run
    """

    def __init__(self, path=LOCK_FILE, stale_seconds=STALE_LOCK_SECONDS):
        self.path = path
        self.stale_seconds = stale_seconds
        self.acquired = False

    def acquire(self):
        if self.path.exists() and time.time() - self.path.stat().st_mtime > self.stale_seconds:
            logger.warning("Removing stale lock file (older than %s s)", self.stale_seconds)
            self.path.unlink(missing_ok=True)
        try:
            # O_EXCL: creating the file fails if it already exists. The OS checks
            # and creates in one step, so two runs can't both get the lock.
            handle = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        os.write(handle, str(os.getpid()).encode())
        os.close(handle)
        self.acquired = True
        return True

    def release(self):
        if self.acquired:
            self.path.unlink(missing_ok=True)
            self.acquired = False

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc_info):
        self.release()


def setup_logging(log_file=LOG_FILE):
    """Log to logs/pipeline.log (max 1 MB x 5 files) and to the console."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    file_handler = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(formatter)
    handlers = [file_handler]
    if sys.stdout is not None:          # pythonw.exe (scheduled runs) has no console
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        handlers.append(console)
    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True)


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
        mart_counts = load_mart.build_mart(conn)
        summary = {
            "ingested_new": ingest_counts["new"],
            "duplicates": ingest_counts["duplicate"],
            "rejected": ingest_counts["rejected"],
            "crashed": ingest_counts["crashed"],
            "skipped_still_copying": ingest_counts["skipped"],
            "ocr_runs": ocr_count,
            "receipts_loaded": len(receipt_ids),
            "needs_review": needs_review,
            "mart_fact_rows": mart_counts["fact_purchase_line"],
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

    # Clearly from another country: the checks rejected it automatically
    status = conn.execute("SELECT review_status FROM clean.receipt WHERE receipt_id = %s",
                          (receipt_id,)).fetchone()[0]
    if status == "rejected":
        result["status"] = "wrong_country"
        result["reason"] = checks["from_allowed_country"][1]
        result["needs_review"] = False
    return result


def process_multi_image(conn, parts, source, raw_dir=None):
    """One long receipt photographed in several parts (top first).

    parts: list of (bytes, original_name). The photos are joined into one
    image and then processed exactly like a single photo.
    Returns the same dict as process_single_image().
    """
    from src.stitch import StitchError, stitch_images

    try:
        joined = stitch_images(parts)
    except StitchError as reason:
        return {"status": "rejected", "file_id": None, "receipt_id": None,
                "reason": str(reason), "needs_review": False}
    name = f"long_receipt_{len(parts)}_photos.jpg"
    return process_single_image(conn, joined, name, source, raw_dir=raw_dir)


def main(argv=None, lock=None):
    """Command-line entry point. Returns the exit code."""
    parser = argparse.ArgumentParser(description="Run the receipt pipeline.")
    parser.add_argument("--sample", action="store_true",
                        help="copy the fake sample receipts into the inbox first")
    args = parser.parse_args(argv)

    setup_logging()
    lock = lock or PipelineLock()
    with lock as got_lock:
        if not got_lock:
            logger.info("Another pipeline run is in progress; skipping this run")
            return 2
        try:
            if args.sample:
                logger.info("Copied %s sample images into the inbox", copy_sample_to_inbox())
            summary = run()
            print(summary)
            return 0
        except Exception:
            # Full traceback goes to the log file; it holds no receipt contents
            logger.exception("Pipeline run failed")
            return 1


if __name__ == "__main__":
    sys.exit(main())
