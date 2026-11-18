"""Remove receipt data, e.g. to start fresh with real receipts.

    python scripts/reset_data.py --demo   # remove only the fake demo receipts
    python scripts/reset_data.py --all    # remove EVERY receipt (asks you to type YES)

Removed: stored images in data/raw/, raw.receipt_file, raw.ocr_run,
clean.receipt / receipt_line / correction, dq.check_result, and the mart facts
(the mart is rebuilt afterwards).
Kept: the database structure, item rules (mart.item_mapping), vendor names
(clean.vendor_mapping), settings, app passwords, data/sample/, data/private/,
and anything still waiting in data/inbox/.

This deletes data on purpose, so it only runs when you start it yourself.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import load_mart  # noqa: E402
from src.db import get_connection  # noqa: E402
from src.ocr import resolve_stored_path, sample_hashes  # noqa: E402


def delete_files(conn, file_ids):
    """Delete these files and everything built from them. Returns # of files removed."""
    if not file_ids:
        return 0
    paths = [row[0] for row in conn.execute(
        "SELECT stored_path FROM raw.receipt_file WHERE file_id = ANY(%s)", (file_ids,)).fetchall()]
    receipt_ids = [row[0] for row in conn.execute(
        "SELECT receipt_id FROM clean.receipt WHERE file_id = ANY(%s)", (file_ids,)).fetchall()]

    # One transaction: either everything below is removed, or nothing is
    with conn.transaction():
        conn.execute("DELETE FROM mart.fact_purchase_line WHERE receipt_id = ANY(%s)", (receipt_ids,))
        conn.execute("DELETE FROM dq.check_result WHERE receipt_id = ANY(%s)", (receipt_ids,))
        conn.execute("DELETE FROM clean.correction WHERE receipt_id = ANY(%s)", (receipt_ids,))
        conn.execute("DELETE FROM clean.receipt_line WHERE receipt_id = ANY(%s)", (receipt_ids,))
        conn.execute("DELETE FROM clean.receipt WHERE receipt_id = ANY(%s)", (receipt_ids,))
        conn.execute("DELETE FROM raw.ocr_run WHERE file_id = ANY(%s)", (file_ids,))
        conn.execute("DELETE FROM raw.receipt_file WHERE file_id = ANY(%s)", (file_ids,))

    # Image files last (after the database rows are gone)
    for stored_path in paths:
        resolve_stored_path(stored_path).unlink(missing_ok=True)
    return len(file_ids)


def file_ids_with_hashes(conn, hashes):
    return [row[0] for row in conn.execute(
        "SELECT file_id FROM raw.receipt_file WHERE sha256 = ANY(%s)", (list(hashes),)).fetchall()]


def all_file_ids(conn):
    return [row[0] for row in conn.execute("SELECT file_id FROM raw.receipt_file").fetchall()]


def clear_mart_dimensions(conn):
    """After --all: drop vendors and dates that no longer have any purchases."""
    with conn.transaction():
        conn.execute("DELETE FROM mart.dim_vendor v WHERE NOT EXISTS "
                     "(SELECT 1 FROM mart.fact_purchase_line f WHERE f.vendor_key = v.vendor_key)")
        conn.execute("DELETE FROM mart.dim_date d WHERE d.date_key <> 0 AND NOT EXISTS "
                     "(SELECT 1 FROM mart.fact_purchase_line f WHERE f.date_key = d.date_key)")


def main():
    parser = argparse.ArgumentParser(description="Remove receipt data.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--demo", action="store_true", help="remove only the fake demo receipts")
    group.add_argument("--all", action="store_true", help="remove every receipt")
    args = parser.parse_args()

    with get_connection() as conn:
        if args.all:
            total = len(all_file_ids(conn))
            answer = input(f"This removes ALL {total} stored receipt images and their data. "
                           "Type YES to continue: ")
            if answer.strip() != "YES":
                print("Nothing was removed.")
                return
            removed = delete_files(conn, all_file_ids(conn))
            load_mart.build_mart(conn)
            clear_mart_dimensions(conn)
        else:
            removed = delete_files(conn, file_ids_with_hashes(conn, sample_hashes()))
            load_mart.build_mart(conn)
    print(f"Removed {removed} receipt image(s) and their data.")


if __name__ == "__main__":
    main()
