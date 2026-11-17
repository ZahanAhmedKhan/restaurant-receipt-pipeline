"""Tests for src/evaluate_ocr.py (no real OCR: a fake extractor returns fixed data)."""

import json

from src import evaluate_ocr

TRUTH = {
    "file": "receipt_001.png",
    "vendor": "Harbor Fresh Foods",
    "date": "2026-06-07",
    "receipt_number": "HF-10210",
    "lines": [
        {"description": "CHKN BRST 10LB", "quantity": "2", "unit": "CS", "unit_price": "32.50", "line_total": "65.00"},
        {"description": "FLOUR AP 50LB", "quantity": "1", "unit": "BAG", "unit_price": "22.40", "line_total": "22.40"},
    ],
    "subtotal": "87.40", "tax": "0.00", "total": "87.40", "deliberate_errors": [],
}


def perfect_extraction():
    return {
        "vendor": "HARBOR FRESH FOODS", "date": "06/07/2026", "receipt_number": "HF-10210",
        "lines": [dict(line) for line in TRUTH["lines"]],
        "subtotal": "87.40", "tax": "0.00", "total": "87.40",
    }


def test_perfect_header():
    assert evaluate_ocr.compare_header(perfect_extraction(), TRUTH) == {
        "vendor": True, "date": True, "receipt_number": True, "total": True}


def test_wrong_header_fields():
    extracted = perfect_extraction()
    extracted["date"] = None
    extracted["total"] = "87.42"                 # 2 cents off: wrong
    result = evaluate_ocr.compare_header(extracted, TRUTH)
    assert result["date"] is False
    assert result["total"] is False


def test_money_tolerance_one_cent():
    assert evaluate_ocr.money_equal("87.41", "87.40")
    assert not evaluate_ocr.money_equal(None, "87.40")


def test_lines_matched_by_similar_description():
    extracted = [
        {"description": "FL0UR AP 50LB", "quantity": None, "unit_price": "22.40", "line_total": "22.40"},
        {"description": "CHKN BRST 10LB", "quantity": "2", "unit_price": "32.50", "line_total": "65.00"},
    ]
    counts = evaluate_ocr.compare_lines(extracted, TRUTH["lines"])
    assert counts["matched"] == 2
    assert counts["fully_correct"] == 1
    assert counts["quantity"] == 1
    assert counts["line_total"] == 2


def test_unrelated_line_is_not_matched():
    extracted = [{"description": "THANK YOU", "quantity": "1", "unit_price": "1.00", "line_total": "1.00"}]
    assert evaluate_ocr.compare_lines(extracted, TRUTH["lines"])["matched"] == 0


def test_each_extracted_line_used_once():
    extracted = [{"description": "CHKN BRST 10LB", "quantity": "2", "unit_price": "32.50", "line_total": "65.00"}]
    two_same = [TRUTH["lines"][0], TRUTH["lines"][0]]
    assert evaluate_ocr.compare_lines(extracted, two_same)["matched"] == 1


def test_evaluate_and_report_with_fake_extractor(tmp_path):
    (tmp_path / "receipt_001.json").write_text(json.dumps(TRUTH))
    second = dict(TRUTH, file="receipt_002.png")
    (tmp_path / "receipt_002.json").write_text(json.dumps(second))

    def fake_extractor(path):
        if path.name == "receipt_002.png":
            raise RuntimeError("OCR crashed")
        return perfect_extraction(), 120

    results = evaluate_ocr.evaluate("tesseract", sample_dir=tmp_path, extractor=fake_extractor)
    assert results["receipts"] == 2
    assert results["errors"] == 1
    assert results["header_accuracy_pct"]["total"] == 50.0
    assert results["lines"]["true_lines"] == 4
    assert results["lines"]["fully_correct_pct"] == 50.0
    assert results["avg_duration_ms"] == 120

    all_results = evaluate_ocr.save_results(results, path=tmp_path / "results.json")
    report = evaluate_ocr.render_report(all_results)
    assert "| Total correct (±$0.01) | 50.0% |" in report
    assert "## Method" in report
