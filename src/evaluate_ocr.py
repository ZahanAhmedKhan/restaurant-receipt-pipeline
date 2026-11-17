"""Evaluate extraction accuracy against the ground-truth JSON of the sample receipts.

For each sample image: run the same steps as the pipeline (OCR -> parse -> clean)
and compare with the matching receipt_XXX.json.

Header fields (exact after normalization):
    vendor, date, receipt number; total within $0.01
Line items:
    each true line is matched to the most similar extracted description
    (similarity >= 0.6, each extracted line used once), then quantity,
    unit price and line total are compared (money within $0.01).

Usage:
    python -m src.evaluate_ocr                    # Tesseract
    python -m src.evaluate_ocr --method gemini    # Gemini (sample data only)
Results: docs/ocr_evaluation.md (+ docs/ocr_evaluation.json for the dashboard)
"""

import argparse
import difflib
import json
import time
from datetime import date
from decimal import Decimal

from src import clean, config

DOCS_DIR = config.PROJECT_ROOT / "docs"
RESULTS_JSON = DOCS_DIR / "ocr_evaluation.json"
REPORT_MD = DOCS_DIR / "ocr_evaluation.md"

MONEY_TOLERANCE = Decimal("0.01")
LINE_MATCH_CUTOFF = 0.6
HEADER_FIELDS = ["vendor", "date", "receipt_number", "total"]
LINE_FIELDS = ["quantity", "unit_price", "line_total"]

# The fake vendors' standard names, used to normalize what OCR read
SAMPLE_VENDOR_MAP = {
    "HARBOR FRESH FOODS": "Harbor Fresh Foods",
    "GOLDEN VALLEY PRODUCE": "Golden Valley Produce",
    "SUNRISE MEAT CO.": "Sunrise Meat Co.",
    "METRO RESTAURANT SUPPLY": "Metro Restaurant Supply",
}


# ---------------------------------------------------------------------------
# Extraction (same code as the pipeline)
# ---------------------------------------------------------------------------
def extract_tesseract(path):
    """Returns (parsed dict, duration_ms)."""
    from src.ocr import run_tesseract
    from src.parse import parse_receipt_text
    result = run_tesseract(path)
    return parse_receipt_text(result["text"]), result["duration_ms"]


def extract_gemini(path):
    from src.ocr import run_gemini
    result = run_gemini(path)
    return result["json"], result["duration_ms"]


EXTRACTORS = {"tesseract": extract_tesseract, "gemini": extract_gemini}


# ---------------------------------------------------------------------------
# Comparing one receipt
# ---------------------------------------------------------------------------
def money_equal(a, b):
    a, b = clean.clean_money(a), clean.clean_money(b)
    return a is not None and b is not None and abs(a - b) <= MONEY_TOLERANCE


def quantity_equal(a, b):
    a, b = clean.clean_quantity(a), clean.clean_quantity(b)
    return a is not None and b is not None and a == b


def compare_header(extracted, truth):
    """Returns {field: True/False}."""
    return {
        "vendor": clean.standardize_vendor(extracted.get("vendor"), SAMPLE_VENDOR_MAP) == truth["vendor"],
        "date": clean.clean_date(extracted.get("date")) == date.fromisoformat(truth["date"]),
        "receipt_number": clean.clean_text(extracted.get("receipt_number")) == clean.clean_text(truth["receipt_number"]),
        "total": money_equal(extracted.get("total"), truth["total"]),
    }


def similarity(a, b):
    return difflib.SequenceMatcher(None, clean.clean_text(a) or "", clean.clean_text(b) or "").ratio()


def match_lines(extracted_lines, true_lines):
    """Pair each true line with the most similar unused extracted line.

    Returns a list of (true_line, extracted_line or None).
    """
    unused = list(extracted_lines)
    pairs = []
    for true_line in true_lines:
        best, best_score = None, LINE_MATCH_CUTOFF
        for candidate in unused:
            score = similarity(candidate.get("description"), true_line["description"])
            if score >= best_score:
                best, best_score = candidate, score
        if best is not None:
            unused.remove(best)
        pairs.append((true_line, best))
    return pairs


def compare_lines(extracted_lines, true_lines):
    """Count matches and correct fields for one receipt's lines."""
    counts = {"true_lines": len(true_lines), "extracted_lines": len(extracted_lines),
              "matched": 0, "fully_correct": 0}
    for field in LINE_FIELDS:
        counts[field] = 0
    for true_line, found in match_lines(extracted_lines, true_lines):
        if found is None:
            continue
        counts["matched"] += 1
        ok = {
            "quantity": quantity_equal(found.get("quantity"), true_line["quantity"]),
            "unit_price": money_equal(found.get("unit_price"), true_line["unit_price"]),
            "line_total": money_equal(found.get("line_total"), true_line["line_total"]),
        }
        for field, correct in ok.items():
            counts[field] += correct
        counts["fully_correct"] += all(ok.values())
    return counts


# ---------------------------------------------------------------------------
# Whole sample set
# ---------------------------------------------------------------------------
def evaluate(method="tesseract", sample_dir=None, extractor=None):
    """Run one method over every sample receipt. Returns a results dict."""
    sample_dir = sample_dir or config.SAMPLE_DIR
    extractor = extractor or EXTRACTORS[method]

    header_correct = {field: 0 for field in HEADER_FIELDS}
    line_totals = {"true_lines": 0, "extracted_lines": 0, "matched": 0, "fully_correct": 0,
                   **{field: 0 for field in LINE_FIELDS}}
    durations = []
    errors = 0
    receipts = 0

    for truth_path in sorted(sample_dir.glob("receipt_*.json")):
        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        receipts += 1
        try:
            extracted, duration_ms = extractor(sample_dir / truth["file"])
        except Exception:
            # Count it as all wrong, keep going
            errors += 1
            line_totals["true_lines"] += len(truth["lines"])
            continue
        durations.append(duration_ms)
        for field, correct in compare_header(extracted, truth).items():
            header_correct[field] += correct
        for key, value in compare_lines(extracted.get("lines") or [], truth["lines"]).items():
            line_totals[key] += value

    def pct(part, whole):
        return round(100.0 * part / whole, 1) if whole else 0.0

    matched = line_totals["matched"]
    return {
        "method": method,
        "run_date": date.today().isoformat(),
        "receipts": receipts,
        "errors": errors,
        "header_accuracy_pct": {field: pct(header_correct[field], receipts) for field in HEADER_FIELDS},
        "lines": {
            "true_lines": line_totals["true_lines"],
            "extracted_lines": line_totals["extracted_lines"],
            "matched_pct": pct(matched, line_totals["true_lines"]),
            "fully_correct_pct": pct(line_totals["fully_correct"], line_totals["true_lines"]),
            # Field accuracy among lines that were matched
            "field_accuracy_pct": {field: pct(line_totals[field], matched) for field in LINE_FIELDS},
        },
        "avg_duration_ms": round(sum(durations) / len(durations)) if durations else None,
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def load_all_results(path=RESULTS_JSON):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_results(results, path=RESULTS_JSON):
    """Store this method's results next to the other methods' results."""
    all_results = load_all_results(path)
    all_results[results["method"]] = results
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(all_results, indent=2), encoding="utf-8")
    return all_results


def render_report(all_results):
    """Markdown report with one column per evaluated method."""
    methods = sorted(all_results)
    header = "| Metric | " + " | ".join(methods) + " |"
    divider = "|---|" + "---|" * len(methods)

    def row(label, getter, suffix="%"):
        cells = []
        for method in methods:
            value = getter(all_results[method])
            cells.append("n/a" if value is None else f"{value}{suffix}")
        return f"| {label} | " + " | ".join(cells) + " |"

    rows = [
        row("Receipts evaluated", lambda r: r["receipts"], ""),
        row("Extraction errors", lambda r: r["errors"], ""),
        row("Vendor correct", lambda r: r["header_accuracy_pct"]["vendor"]),
        row("Date correct", lambda r: r["header_accuracy_pct"]["date"]),
        row("Receipt number correct", lambda r: r["header_accuracy_pct"]["receipt_number"]),
        row("Total correct (±$0.01)", lambda r: r["header_accuracy_pct"]["total"]),
        row("True line items", lambda r: r["lines"]["true_lines"], ""),
        row("Line items found (matched)", lambda r: r["lines"]["matched_pct"]),
        row("Line items fully correct", lambda r: r["lines"]["fully_correct_pct"]),
        row("Quantity correct (matched lines)", lambda r: r["lines"]["field_accuracy_pct"]["quantity"]),
        row("Unit price correct (matched lines)", lambda r: r["lines"]["field_accuracy_pct"]["unit_price"]),
        row("Line total correct (matched lines)", lambda r: r["lines"]["field_accuracy_pct"]["line_total"]),
        row("Average time per receipt", lambda r: r["avg_duration_ms"], " ms"),
        row("Run date", lambda r: r["run_date"], ""),
    ]
    return "\n".join([
        "# OCR evaluation",
        "",
        "Measured by `python -m src.evaluate_ocr` on the 50 synthetic sample receipts in `data/sample/`",
        "(fake vendors, ground truth in the matching JSON files). Numbers below are what the script measured.",
        "",
        header,
        divider,
        *rows,
        "",
        "## Method",
        "",
        "- Each sample image goes through the same code as the pipeline: OCR (or Gemini), then `parse.py`,",
        "  then the cleaning functions in `clean.py`.",
        "- **Header fields:** vendor (after mapping to the standard vendor name), date (after date",
        "  standardization), receipt number (uppercase, single spaces) must match exactly; total must be",
        "  within $0.01.",
        "- **Line items:** every true line is paired with the extracted line whose description is most",
        "  similar (`difflib` ratio >= 0.6; each extracted line is used once). \"Found\" = share of true",
        "  lines that got a pair. For paired lines, quantity must be equal and unit price / line total",
        "  within $0.01. \"Fully correct\" = all three right, as a share of all true lines.",
        "- **Time:** OCR/extraction time only (no database), averaged over the receipts.",
        "- **Limits:** synthetic receipts are cleaner than real photos (flat, evenly lit, one font), so",
        "  real-world accuracy will be lower. Gemini runs only on these fake receipts.",
        "",
    ])


def main():
    parser = argparse.ArgumentParser(description="Evaluate OCR against ground truth.")
    parser.add_argument("--method", choices=sorted(EXTRACTORS), default="tesseract")
    args = parser.parse_args()

    results = evaluate(args.method)
    if results["errors"] == results["receipts"]:
        # Every receipt failed: that's a setup problem (API key, model name,
        # network), not an accuracy result. Don't overwrite the report with 0%.
        print(f"All {results['receipts']} receipts failed with {args.method}; nothing saved. "
              "Check the API key, GEMINI_MODEL and your internet connection.")
        return
    all_results = save_results(results)
    REPORT_MD.write_text(render_report(all_results), encoding="utf-8")
    print(json.dumps(results, indent=2))
    print(f"Report written to {REPORT_MD}")


if __name__ == "__main__":
    main()
