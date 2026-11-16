# Progress

## Done

- **M0.1 Project skeleton:** folders, `.gitignore`, `.env.example`, `requirements.txt`, README stub,
  `.claude/settings.json`, Python 3.12 venv with requirements installed, Tesseract 5.4 installed and on PATH.
- **M0.2 Database setup:** `sql/000_roles_and_schemas.sql` (roles `receipts_app` / `receipts_readonly`,
  schemas `raw`, `clean`, `dq`, `mart`), `scripts/bootstrap_db.py` (one-time superuser step: creates
  `receipts` and `receipts_test`, runs 000, sets role passwords from `.env`), `src/config.py`, `src/db.py`,
  `scripts/setup_db.py` (applies numbered SQL files once, tracked in `public.schema_version`).
  Tests use the separate `receipts_test` database.
- **M1.1 Fake receipt generator:** `scripts/make_sample_receipts.py` draws 50 fake receipts from 4 made-up
  vendors (48 unique + 1 re-photographed duplicate + 1 exact file copy) with ground-truth JSON.
  Deliberate errors: 3 wrong totals, 1 subtotal that doesn't match its lines. One item has a planned
  15% price jump from September 2026 for the price-alert feature.

- **M1.2 Ingestion:** `sql/001_raw.sql` (`raw.receipt_file`, `raw.ocr_run`), `src/ingest.py` with
  `ingest_image_bytes()` (JPG/PNG only, real format checked with Pillow, 10 MB and 50 MP limits,
  saved as `data/raw/<sha256>.<ext>`, duplicates detected by hash) and `scan_inbox()` (skips files
  newer than 10 s, moves rejected files to `data/failed/`). Fixed `setup_db.py` so each SQL file commits.

- **M2.1 Tesseract OCR:** `src/ocr.py` with `run_tesseract(path)`, `ocr_file()` (stores a row in
  `raw.ocr_run`, sets file status `ocr_done`/`failed`, stores only the error type on failure) and
  `ocr_pending()`. Tried page modes and preprocessing on the samples; `--psm 6` on the plain image was
  best, so no preprocessing. Sample receipts were regenerated with Courier New Bold: the old font's
  dotted zero was often read as 8 or @ (ground-truth JSON unchanged, only images).

## Next

- **M2.2 Parsing:** `src/parse.py`.

## Open issues

- None yet.

## Concepts to study later

### M0.1
- Python virtual environments (`venv`)
- `requirements.txt` and pip
- `.gitignore` and keeping secrets out of Git
- Environment variables and `.env` files
- Windows PATH
- Tesseract OCR engine

### M0.2
- PostgreSQL roles, `LOGIN`, superuser vs. normal user
- Schemas as namespaces (`raw`, `clean`, `dq`, `mart`)
- `GRANT`, `ALTER DEFAULT PRIVILEGES`, principle of least privilege
- Schema migrations and a version table
- Transactions (`conn.transaction()`), commit and rollback
- Idempotent scripts (`IF NOT EXISTS`)
- Safe SQL identifiers/literals with `psycopg.sql`
- pytest fixtures and a separate test database

### M1.1
- Synthetic data and ground truth (labelled data)
- Seeded random numbers for repeatable output
- `Decimal` and rounding modes (`ROUND_HALF_UP`)
- Drawing images with Pillow (`ImageDraw`, fonts, rotate, noise, blur)
- JSON files
- SHA-256 file hashes
- pytest `parametrize`

### M1.2
- `GENERATED ALWAYS AS IDENTITY` primary keys, `UNIQUE`, `CHECK` constraints, foreign keys
- Content hashing for deduplication (SHA-256)
- Idempotency (`ON CONFLICT DO NOTHING`)
- Validating untrusted files (magic bytes vs. extension, `Image.verify()`, decompression bombs)
- Path traversal and why we never use the original filename as a path
- Parameterized queries (`%s`)
- Python `logging`
- pytest `tmp_path` and `monkeypatch`
- Implicit transactions vs. savepoints in psycopg

### M2.1
- How OCR works (Tesseract, page segmentation modes `--psm`)
- Image preprocessing (grayscale, resizing) and measuring before adding it
- Timing code with `time.perf_counter()`
- Recording failures without losing data (error column + status)
- `pathlib` path joining
