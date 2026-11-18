"""Evaluate the pipeline on REAL receipts from the public SROIE dataset.

SROIE (ICDAR 2019 "Scanned Receipts OCR and Information Extraction") has
626 labelled receipts from Malaysian shops. Each label file gives the
company, date, address and total. We download them into data/external/sroie/
(not committed: the dataset is for research use).

Same code path as the pipeline: Tesseract -> parse.py -> clean.py.
Fields scored: total (within $0.01), date (same calendar day), vendor
(exact after normalization, and "close" = similarity >= 0.8).

Split, so that parser changes can be judged fairly:
    dev  = receipts 000-299 (allowed to look at while improving the parser)
    test = receipts 300-625 (held out: never looked at while changing code)

Usage:
    python -m src.evaluate_sroie --ocr            # run Tesseract once, cache the text
    python -m src.evaluate_sroie                  # score all splits, write the report
"""

import argparse
import difflib
import json
import re
import time
from datetime import datetime

from src import clean, config
from src.parse import parse_receipt_text

DATA_DIR = config.DATA_DIR / "external" / "sroie"
CACHE_DIR = config.DATA_DIR / "external" / "sroie_ocr"
REPORT_MD = config.PROJECT_ROOT / "docs" / "sroie_evaluation.md"
RESULTS_JSON = config.PROJECT_ROOT / "docs" / "sroie_evaluation.json"

DEV_IDS = range(0, 300)
TEST_IDS = range(300, 626)
VENDOR_CLOSE = 0.8

# Malaysian receipts write dates day first
LABEL_DATE_FORMATS = ["%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d-%m-%y", "%d.%m.%Y", "%d.%m.%y",
                      "%Y-%m-%d", "%Y/%m/%d", "%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d %b %y",
                      "%b %d, %Y", "%d%b%Y"]


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def receipt_ids(split):
    if split == "dev":
        ids = DEV_IDS
    elif split == "test":
        ids = TEST_IDS
    else:
        ids = range(0, 626)
    return [f"{i:03d}" for i in ids if (DATA_DIR / f"{i:03d}.json").exists()]


def load_label(receipt_id):
    return json.loads((DATA_DIR / f"{receipt_id}.json").read_text(encoding="utf-8"))


def parse_label_date(text):
    text = (text or "").strip()
    for fmt in LABEL_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()   # month names: any case
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# OCR (cached, because it is the slow part)
# ---------------------------------------------------------------------------
def run_ocr_cache(ids):
    """Run Tesseract on every receipt not cached yet. Returns timing info."""
    from src.ocr import run_tesseract
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    durations, failures = [], []
    for receipt_id in ids:
        cache = CACHE_DIR / f"{receipt_id}.json"
        if cache.exists():
            continue
        try:
            result = run_tesseract(DATA_DIR / f"{receipt_id}.jpg")
            cache.write_text(json.dumps(result), encoding="utf-8")
            durations.append(result["duration_ms"])
        except Exception as error:
            failures.append((receipt_id, type(error).__name__))
    return durations, failures


def cached_ocr(receipt_id):
    path = CACHE_DIR / f"{receipt_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def normalize_name(text):
    """Uppercase, letters and digits only, single spaces."""
    text = re.sub(r"[^A-Z0-9 ]", " ", (text or "").upper())
    return re.sub(r"\s+", " ", text).strip()


def score_receipt(text, label):
    """Compare what the pipeline extracts from the OCR text with the label."""
    parsed = parse_receipt_text(text)
    found_total = clean.clean_money(parsed["total"])
    true_total = clean.clean_money(label.get("total"))
    found_date = clean.clean_date(parsed["date"])
    true_date = parse_label_date(label.get("date"))
    vendor = normalize_name(parsed["vendor"])
    company = normalize_name(label.get("company"))
    return {
        "total": found_total is not None and true_total is not None
        and abs(found_total - true_total) <= clean.CENT,
        "date": true_date is not None and found_date == true_date,
        "date_labelled": true_date is not None,
        "vendor_exact": bool(vendor) and vendor == company,
        "vendor_close": bool(vendor) and difflib.SequenceMatcher(None, vendor, company).ratio() >= VENDOR_CLOSE,
        "total_found": found_total is not None,
        "date_found": found_date is not None,
    }


def score_split(split):
    config.DATE_ORDER = "DMY"          # Malaysian receipts: day first
    ids = receipt_ids(split)
    rows, missing = [], 0
    for receipt_id in ids:
        ocr = cached_ocr(receipt_id)
        if ocr is None:
            missing += 1
            continue
        rows.append(score_receipt(ocr["text"], load_label(receipt_id)))

    def pct(key, base=None):
        pool = [r for r in rows if base is None or r[base]]
        return round(100.0 * sum(r[key] for r in pool) / len(pool), 1) if pool else 0.0

    durations = [cached_ocr(i)["duration_ms"] for i in ids if cached_ocr(i)]
    return {
        "split": split,
        "receipts": len(rows),
        "not_ocred": missing,
        "total_correct_pct": pct("total"),
        "date_correct_pct": pct("date", base="date_labelled"),
        "dates_labelled": sum(r["date_labelled"] for r in rows),
        "vendor_exact_pct": pct("vendor_exact"),
        "vendor_close_pct": pct("vendor_close"),
        "total_found_pct": pct("total_found"),
        "date_found_pct": pct("date_found"),
        "avg_ocr_ms": round(sum(durations) / len(durations)) if durations else None,
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def render_report(results, history):
    def row(label, key, suffix="%"):
        return f"| {label} | " + " | ".join(f"{r[key]}{suffix}" for r in results) + " |"

    lines = [
        "# Evaluation on real receipts (SROIE dataset)",
        "",
        "Measured by `python -m src.evaluate_sroie` on the public **SROIE** dataset (ICDAR 2019):",
        "626 real, labelled receipts from Malaysian shops. Same code path as the pipeline:",
        "Tesseract → `parse.py` → `clean.py` (dates read day-first for this dataset).",
        "",
        "| Metric | " + " | ".join(r["split"] for r in results) + " |",
        "|---|" + "---|" * len(results),
        row("Receipts", "receipts", ""),
        row("Total correct (±$0.01)", "total_correct_pct"),
        row("Date correct", "date_correct_pct"),
        row("Vendor exact (normalized)", "vendor_exact_pct"),
        row("Vendor close (similarity ≥ 0.8)", "vendor_close_pct"),
        row("A total was found", "total_found_pct"),
        row("A date was found", "date_found_pct"),
        row("Average OCR time", "avg_ocr_ms", " ms"),
        "",
        "Splits: **dev** = receipts 000–299 (used while improving the parser),",
        "**test** = receipts 300–625 (held out: never looked at while changing code).",
        "",
    ]
    if history:
        lines += ["## Held-out test set: before and after parser improvements", "",
                  "| Version | Total correct | Date correct | Vendor close |", "|---|---|---|---|"]
        for entry in history:
            lines.append(f"| {entry['label']} | {entry['total_correct_pct']}% | "
                         f"{entry['date_correct_pct']}% | {entry['vendor_close_pct']}% |")
        lines.append("")
    lines += [
        "## Notes",
        "",
        "- Real receipts (crumpled, faded, many layouts) are much harder than the synthetic samples.",
        "- These receipts are Malaysian, so the country check (Canada only) is switched off here.",
        "- The dataset is downloaded locally into `data/external/` and is not committed.",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Evaluate on the SROIE real-receipt dataset.")
    parser.add_argument("--ocr", action="store_true", help="run Tesseract on receipts not cached yet")
    parser.add_argument("--record", metavar="LABEL", help="save the test-split result under this label")
    args = parser.parse_args()

    if args.ocr:
        start = time.perf_counter()
        durations, failures = run_ocr_cache(receipt_ids("all"))
        print(f"OCR'd {len(durations)} receipts in {time.perf_counter() - start:.0f} s; "
              f"failures: {failures or 'none'}")

    results = [score_split(split) for split in ("all", "dev", "test")]
    saved = json.loads(RESULTS_JSON.read_text(encoding="utf-8")) if RESULTS_JSON.exists() else {}
    history = saved.get("test_history", [])
    if args.record:
        history = [h for h in history if h["label"] != args.record]
        history.append({"label": args.record, **results[2]})
    RESULTS_JSON.write_text(json.dumps({"results": results, "test_history": history}, indent=2),
                            encoding="utf-8")
    REPORT_MD.write_text(render_report(results, history), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
