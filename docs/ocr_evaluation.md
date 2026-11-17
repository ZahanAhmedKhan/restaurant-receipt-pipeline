# OCR evaluation

Measured by `python -m src.evaluate_ocr` on the 50 synthetic sample receipts in `data/sample/`
(fake vendors, ground truth in the matching JSON files). Numbers below are what the script measured.

| Metric | tesseract |
|---|---|
| Receipts evaluated | 50 |
| Extraction errors | 0 |
| Vendor correct | 100.0% |
| Date correct | 100.0% |
| Receipt number correct | 100.0% |
| Total correct (±$0.01) | 96.0% |
| True line items | 260 |
| Line items found (matched) | 100.0% |
| Line items fully correct | 69.2% |
| Quantity correct (matched lines) | 78.8% |
| Unit price correct (matched lines) | 90.4% |
| Line total correct (matched lines) | 90.0% |
| Average time per receipt | 527 ms |
| Run date | 2026-11-16 |

## Method

- Each sample image goes through the same code as the pipeline: OCR (or Gemini), then `parse.py`,
  then the cleaning functions in `clean.py`.
- **Header fields:** vendor (after mapping to the standard vendor name), date (after date
  standardization), receipt number (uppercase, single spaces) must match exactly; total must be
  within $0.01.
- **Line items:** every true line is paired with the extracted line whose description is most
  similar (`difflib` ratio >= 0.6; each extracted line is used once). "Found" = share of true
  lines that got a pair. For paired lines, quantity must be equal and unit price / line total
  within $0.01. "Fully correct" = all three right, as a share of all true lines.
- **Time:** OCR/extraction time only (no database), averaged over the receipts.
- **Limits:** synthetic receipts are cleaner than real photos (flat, evenly lit, one font), so
  real-world accuracy will be lower. Gemini runs only on these fake receipts.
