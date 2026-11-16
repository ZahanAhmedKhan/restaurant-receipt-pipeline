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

- **M2.2 Parsing:** `src/parse.py` turns OCR text into vendor, date (raw text), receipt number,
  line items, subtotal, tax, total. Regex rules for header lines; item lines split around the unit
  token found from the right. Safe OCR fixes only inside number tokens (O/@ -> 0, l/I -> 1, trailing
  comma). Unreadable values become `None`.

- **M2.3 Cleaning + loading:** `sql/002_clean.sql` (`clean.vendor_mapping` seeded with the 4 fake
  vendors, `clean.receipt`, `clean.receipt_line`, `clean.correction`), `src/clean.py` (pandas cleaning:
  dates in 6 formats, money as `Decimal`, vendor mapping with close-match for OCR typos, whitespace/case;
  raw values kept next to clean ones), `src/run_pipeline.py` (ingest -> OCR -> clean, `--sample` copies the
  fake receipts into the inbox). DB connections now use autocommit + explicit `conn.transaction()` blocks.
  Measured on the sample set: 50 files -> 49 receipts loaded, 1 exact duplicate caught; a second run
  loaded 0 new receipts.

- **M3.1 Quality checks:** `sql/003_dq.sql` (`dq.check_result`), `src/quality.py` with 6 checks:
  required fields (incl. every line value), valid/future date, no negatives, lines add up to subtotal
  (2-cent tolerance), total = subtotal + tax, duplicate (same vendor + number + total on an earlier receipt).
  Results replace the receipt's previous results; failure -> `needs_review`, all pass -> `pending`;
  approved/rejected receipts keep their status. Added to `run_pipeline.py`.
  Measured on the 49 sample receipts: 8 pending, 41 needs_review. Failures by check: required_fields 40,
  lines_match_subtotal 20, total_is_subtotal_plus_tax 6, not_duplicate 1, valid_date 0, no_negative_values 0.
  Both planted duplicates are caught (exact file at ingestion, re-photographed copy here).

- **M3.2 Receipt capture page:** `app/Home.py` (password gate, status counts), `app/pages/1_Add_Receipt.py`
  (Take Photo / Upload Receipt tabs, preview, Submit, status messages, camera help), `app/app_common.py`
  (page setup + password check on every page), `src/auth.py` (salted PBKDF2 hash),
  `scripts/set_app_password.py`, `process_single_image()` in `run_pipeline.py`,
  `.streamlit/config.toml` (static serving off, 10 MB upload limit). README: app and phone (Tailscale) setup.
  Tests include Streamlit `AppTest` checks of the password gate.

## Next

- **M3.3 Review page:** `app/pages/2_Review.py`.

## Open issues

- Tesseract often misreads single-digit quantities (especially "1") and sometimes whole price columns on
  blurred images, so most sample receipts need review. To be compared with Gemini in M5.2.

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

### M2.2
- Regular expressions (`re`): groups, anchors `^ $`, `re.MULTILINE`, `re.IGNORECASE`
- Parsing semi-structured text, tokenizing with `split()`
- Common OCR character confusions
- "Never guess": `None` for missing data
- Unit tests with fixed input strings

### M2.3
- pandas DataFrames, `Series.map`, `dtype=object`, NaN vs. None
- Date parsing with `strptime` formats
- `Decimal` vs. float for money, `NUMERIC(12,2)`
- Fuzzy string matching (`difflib.get_close_matches`)
- Raw vs. clean columns side by side (auditability)
- Autocommit vs. explicit transactions
- `ON DELETE CASCADE`, `UNIQUE (receipt_id, line_no)`
- Idempotent pipeline steps driven by a status column
- `argparse` command-line options

### M3.1
- Data quality dimensions (completeness, validity, consistency, uniqueness)
- Tolerances when comparing money
- Rule-based validation and review queues
- Replace-on-rerun (delete + insert in one transaction)
- `count(*) FILTER (WHERE ...)` and partial indexes

### M3.2
- Streamlit basics: script reruns, widgets, `st.session_state`, `st.stop()`, tabs, forms
- Streamlit multipage apps and `st.cache_resource`
- Password hashing with salt (PBKDF2), constant-time comparison
- Why browsers need HTTPS for the camera; Tailscale private networks
- Testing Streamlit pages with `AppTest`
