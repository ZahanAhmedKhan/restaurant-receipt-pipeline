"""DEMO ONLY: act as a reviewer for the fake sample receipts.

For every open receipt that is one of the sample images (checked by file hash),
fix the fields to the ground-truth JSON through the normal review code (so every
change is logged in clean.correction), then:
    - reject the re-photographed duplicate
    - leave receipts with deliberate errors (wrong total, lines != subtotal)
      in the review queue for a human
    - approve the rest
Finally rebuild the mart. Real receipts are never touched.

Usage:
    python scripts/demo_review_samples.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, load_mart, review  # noqa: E402
from src.db import get_connection  # noqa: E402
from src.ocr import file_sha256, resolve_stored_path  # noqa: E402

LEAVE_FOR_HUMAN = {"wrong_total", "lines_dont_match_subtotal"}


def truth_by_hash(sample_dir=config.SAMPLE_DIR):
    """{sha256 of sample image: ground-truth dict}"""
    truths = {}
    for json_path in sorted(sample_dir.glob("receipt_*.json")):
        truth = json.loads(json_path.read_text(encoding="utf-8"))
        truths[file_sha256(sample_dir / truth["file"])] = truth
    return truths


def correct_to_truth(conn, receipt_id, truth):
    """Use the review code to set every field to the true value. Returns # changes."""
    current = review.get_receipt(conn, receipt_id)
    old_line_nos = [line["line_no"] for line in current["lines"]]
    header = {
        "vendor_name": truth["vendor"], "receipt_date": truth["date"],
        "receipt_number": truth["receipt_number"], "subtotal": truth["subtotal"],
        "tax": truth["tax"], "total": truth["total"],
    }
    lines = []
    for i, true_line in enumerate(truth["lines"]):
        lines.append({
            "line_no": old_line_nos[i] if i < len(old_line_nos) else None,
            "description": true_line["description"], "quantity": true_line["quantity"],
            "unit_raw": true_line["unit"], "unit_price": true_line["unit_price"],
            "line_total": true_line["line_total"],
        })
    return review.save_corrections(conn, receipt_id, header, lines)


def main():
    truths = truth_by_hash()
    counts = {"corrected_fields": 0, "approved": 0, "rejected": 0, "left_for_review": 0}
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT r.receipt_id, f.stored_path
            FROM clean.receipt r JOIN raw.receipt_file f ON f.file_id = r.file_id
            WHERE r.review_status IN ('pending', 'needs_review')
            ORDER BY r.receipt_id
            """
        ).fetchall()
        for receipt_id, stored_path in rows:
            path = resolve_stored_path(stored_path)
            if not path.exists():
                continue
            truth = truths.get(file_sha256(path))
            if truth is None:
                continue                      # not a sample receipt: never touched
            counts["corrected_fields"] += correct_to_truth(conn, receipt_id, truth)
            errors = set(truth["deliberate_errors"])
            if "duplicate_receipt" in errors:
                review.set_review_status(conn, receipt_id, "rejected")
                counts["rejected"] += 1
            elif errors & LEAVE_FOR_HUMAN:
                counts["left_for_review"] += 1
            else:
                review.set_review_status(conn, receipt_id, "approved")
                counts["approved"] += 1
        counts["mart"] = load_mart.build_mart(conn)
    print(counts)


if __name__ == "__main__":
    main()
