# Evaluation on real receipts (SROIE dataset)

Measured by `python -m src.evaluate_sroie` on the public **SROIE** dataset (ICDAR 2019):
626 real, labelled receipts from Malaysian shops. Same code path as the pipeline:
Tesseract → `parse.py` → `clean.py` (dates read day-first for this dataset).

| Metric | all | dev | test |
|---|---|---|---|
| Receipts | 626 | 300 | 326 |
| Total correct (±$0.01) | 57.0% | 53.0% | 60.7% |
| Date correct | 78.2% | 79.5% | 77.1% |
| Vendor exact (normalized) | 18.2% | 19.7% | 16.9% |
| Vendor close (similarity ≥ 0.8) | 33.5% | 28.0% | 38.7% |
| A total was found | 82.4% | 76.7% | 87.7% |
| A date was found | 85.6% | 85.3% | 85.9% |
| Average OCR time | 1024 ms | 918 ms | 1121 ms |

Splits: **dev** = receipts 000–299 (used while improving the parser),
**test** = receipts 300–625 (held out: never looked at while changing code).

## Held-out test set: before and after parser improvements

| Version | Total correct | Date correct | Vendor close |
|---|---|---|---|
| Baseline (parser built for our own receipts) | 20.9% | 1.9% | 38.7% |
| Improved total/date rules (built on dev only) | 60.7% | 77.1% | 38.7% |

## Notes

- Real receipts (crumpled, faded, many layouts) are much harder than the synthetic samples.
- These receipts are Malaysian, so the country check (Canada only) is switched off here.
- The dataset is downloaded locally into `data/external/` and is not committed.
