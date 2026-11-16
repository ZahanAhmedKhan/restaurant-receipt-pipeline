# CLAUDE.md — Restaurant Receipt Pipeline

This file is the single source of truth for this project. Read it fully before doing anything.
You have no access to any earlier conversation; everything you need is here.

---

## 1. Who you are working with

- I'm a 3rd-year Data Engineering student. Python and SQL: beginner–intermediate. pandas, PostgreSQL, Git: basic.
- I'm on **Windows 11, VS Code, PowerShell**. PostgreSQL is installed locally and I use **pgAdmin**.
- **Right now the goal is to finish the project.** Don't stop to teach or explain concepts during milestones.
  I'll study the whole project at the end (see M8.3). Still keep code **simple, readable and well commented** so it's easy to learn from later.
- Keep each milestone small.
- Budget: **$0**. Free and open-source tools only.

---

## 2. What we're building

A data pipeline for my family's restaurant. Today, staff type every receipt into Excel by hand.

**Flow:**

```
Receipt photo (inbox folder)
  → raw storage (original image + file hash)
  → OCR (Tesseract by default, Gemini optional)
  → parse OCR text into structured fields
  → clean & standardize with pandas
  → data quality checks → manual review if flagged
  → PostgreSQL (clean tables → star schema)
  → Excel export + Streamlit dashboard + text-to-SQL chatbot
```

**Business goals:** less manual entry, no duplicate receipts, catch bad receipts, keep originals for audit,
standardize messy item names, track prices over time, compare prices across our existing suppliers,
estimate savings.

---

## 3. Tech stack (do not add anything else without asking me)

| Component | Choice | Why |
|---|---|---|
| Language | Python 3.12 | What I know |
| DB access | **psycopg 3 + plain SQL** (no ORM) | I need SQL practice; easier to explain |
| Database | PostgreSQL (local) | Real relational DB, free |
| Schema changes | Numbered `.sql` files in `sql/` run by a small Python script | Simple and visible; no Alembic |
| Cleaning | pandas | Standard for tabular cleaning |
| Money | `Decimal` in Python, `NUMERIC(12,2)` in SQL | Never use float for money |
| OCR | Tesseract (`pytesseract`) default; Gemini Vision optional | Tesseract is free and offline |
| Images | Pillow | Open/validate images, generate fake receipts |
| Excel | openpyxl (via pandas) | Staff use Excel |
| UI | Streamlit (multipage) | One Python app; no separate frontend |
| Config | `python-dotenv` + `.env` | Keep secrets out of code |
| Tests | pytest | Simple, standard |
| Scheduling | Windows Task Scheduler | Already on my machine |
| LLM (chatbot, OCR option) | Gemini free tier | Free; optional |

**Do NOT add:** FastAPI, SQLAlchemy, Alembic, Docker, Airflow, Kafka, Redis, cloud services, user-role systems,
React or any second frontend. If you think one is truly needed, stop and ask me first.

---

## 4. Rules for Claude Code (follow every time)

1. Work on **one milestone at a time**. Start building right away; no teaching or concept explanations during milestones.
2. Look at existing files before changing them. Don't rewrite working code without a reason.
3. Keep code beginner-friendly: short functions, clear names, a comment on anything non-obvious. No clever one-liners.
4. Write pytest tests for new logic and run them. Report results honestly; explain any failures.
5. Give me **exact PowerShell commands** to run things (activate venv, run scripts, run tests).
6. **Finish every milestone by committing and pushing, then stop.** Once the milestone's tests pass:
   - Run `git status` and check that nothing private is staged: no `.env`, nothing from `data/inbox|raw|failed|private`, no exports or logs. If anything is, fix `.gitignore` first.
   - `git add` only this milestone's files, `git commit -m "<the milestone's commit message>"`, then `git push`.
   - If tests fail, **don't commit**. Report the failure and stop.
   - Then give a short summary: what was built (2–3 lines), the commands to run and test it, and the commit hash. Wait for my approval before the next milestone.
7. **Git rules:**
   - Commits must look like mine. Use my existing git `user.name` / `user.email`. Never change git config.
   - **Never add `Co-Authored-By`, "Generated with Claude Code", or any Claude/AI/Anthropic mention** to commit messages, PR descriptions, code comments, README or any file.
   - Never force-push, rewrite history, or delete branches. Push to `main` only.
   - If the repo has no remote yet, stop and ask me for the GitHub repo URL.
8. Keep commit messages short, plain English, imperative ("Add OCR step", not "Added OCR step").
9. **Never invent metrics** (accuracy, time saved, savings). Only report numbers the code actually measured.
10. Never put secrets in code, logs or error messages.
11. Never read, modify, move or delete anything in `data/private/` unless I explicitly ask.
12. Never send any file from `data/private/` to Gemini or any external API unless I explicitly approve it for that run.
13. Don't build features that aren't in the current milestone.
14. At the end of each milestone, update `PROGRESS.md` (what's done, what's next, any open issues), and add the
    main concepts used in that milestone as short bullet points under a "Concepts to study later" heading. Just a list; don't explain them now.

---

## 5. Privacy and security (simple, but real)

This runs **locally** on my computer for my family. It is not deployed publicly.

- **Real receipts never go in Git.** Real images, OCR output and DB exports live in `data/private/`, which is in `.gitignore`.
- **Public demo uses fake receipts only** (`data/sample/`, generated in Milestone 1).
- `.env` holds the DB password and Gemini API key. Commit only `.env.example` with placeholders.
- **Two PostgreSQL roles:**
  - `receipts_app`: owns the project schemas; used by the pipeline and Streamlit. Not a superuser.
  - `receipts_readonly`: SELECT only on the `mart` schema; used **only** by the chatbot.
- Use **parameterized queries** everywhere (`%s` placeholders). Never build SQL by string formatting with user input.
- **All images (camera, upload, inbox):** accept only JPG/PNG, check the file actually opens as an image with Pillow
  (`Image.verify()`), check the real format matches JPG/PNG (not just the extension), limit size (10 MB) and pixel count
  (`Image.MAX_IMAGE_PIXELS`), and save with a server-generated name (`<sha256>.jpg`). Never trust the original filename as a path.
- Receipt images are never served from a public URL or static folder. They're only displayed inside the password-protected app.
- **Streamlit password:** one app password stored as a hash in `.env`, checked at the top of every page.
  (Proper user accounts only if this ever goes online. Not in scope now.)
- Don't log receipt contents. Log IDs, status and error types only.

---

## 6. Folder structure

```
restaurant-receipt-pipeline/
├── CLAUDE.md
├── README.md
├── PROGRESS.md
├── requirements.txt
├── .env.example
├── .gitignore
├── data/
│   ├── inbox/          # drop new receipt photos here (gitignored)
│   ├── raw/            # stored originals, renamed by hash (gitignored)
│   ├── failed/         # receipts that errored (gitignored)
│   ├── sample/         # fake receipts + ground-truth JSON (committed)
│   └── private/        # real family data (gitignored, never touched without permission)
├── sql/                # numbered schema files: 001_raw.sql, 002_clean.sql, ...
├── src/
│   ├── config.py       # loads .env
│   ├── db.py           # get_connection(), run_sql_file()
│   ├── ingest.py       # inbox → raw storage
│   ├── ocr.py          # Tesseract / Gemini
│   ├── parse.py        # OCR text → structured fields
│   ├── clean.py        # pandas cleaning
│   ├── quality.py      # data quality checks
│   ├── load_mart.py    # build star schema
│   ├── normalize.py    # item-name normalization + unit conversion
│   ├── export_excel.py
│   ├── evaluate_ocr.py
│   ├── chatbot.py
│   └── run_pipeline.py # runs all steps in order
├── app/                # Streamlit pages
│   ├── Home.py
│   └── pages/
├── scripts/
│   ├── make_sample_receipts.py
│   └── setup_db.py
├── tests/
└── docs/
    ├── architecture.md
    └── database_schema.md
```

Create files only when a milestone needs them.

---

## 7. Database design

Four schemas, matching the data layers:

**`raw`: what we received, never edited**
- `raw.receipt_file`: `file_id` PK, `sha256` UNIQUE, `stored_path`, `original_name`, `source` (`inbox`, `upload`, `camera`), `received_at`, `status` (`new`, `ocr_done`, `parsed`, `failed`)
- `raw.ocr_run`: `ocr_run_id` PK, `file_id` FK, `method` (`tesseract`/`gemini`), `raw_text`, `raw_json`, `started_at`, `duration_ms`, `error`

**`clean`: standardized, reviewable**
- `clean.receipt`: `receipt_id` PK, `file_id` FK, `ocr_run_id` FK, `vendor_raw`, `vendor_name`, `receipt_date`, `receipt_number`, `subtotal`, `tax`, `total`, `review_status` (`pending`, `needs_review`, `approved`, `rejected`), `updated_at`
- `clean.receipt_line`: `line_id` PK, `receipt_id` FK, `line_no`, `description_raw`, `quantity`, `unit_raw`, `unit_price`, `line_total`
- `clean.correction`: `correction_id` PK, `receipt_id` FK, `field_name`, `old_value`, `new_value`, `corrected_at`

**`dq`: data quality**
- `dq.check_result`: `check_id` PK, `receipt_id` FK, `check_name`, `passed` BOOL, `details`, `checked_at`

**`mart`: star schema (approved receipts only)**
- `mart.dim_vendor`: `vendor_key` PK, `vendor_name` UNIQUE
- `mart.dim_item`: `item_key` PK, `item_name` (normalized), `category`, `standard_unit` (`lb`, `kg`, `each`, `L`)
- `mart.dim_date`: `date_key` PK (YYYYMMDD int), `full_date`, `year`, `month`, `month_name`, `week`, `day_of_week`
- `mart.fact_purchase_line`: **grain = one line item on one approved receipt.**
  `purchase_key` PK, `line_id` UNIQUE (lineage back to `clean.receipt_line`), `receipt_id`, `vendor_key`, `item_key`, `date_key`,
  `quantity`, `standard_quantity`, `line_total`, `unit_price_standard`
- `mart.item_mapping`: `description_pattern`, `item_name`, `pack_size`, `pack_unit` (rules for normalization; editable by me)

**Rebuild rule:** the mart is rebuilt from approved clean data by an **idempotent** script (delete + insert inside one transaction,
or upsert on `line_id`). If a receipt is corrected after approval, rerunning the mart build fixes the facts. No duplicates, ever.

**Lineage:** any fact row → `line_id` → `receipt_id` → `ocr_run_id` → `file_id` → original image.

---

## 8. Milestones

Every milestone ends with: tests pass → `PROGRESS.md` updated → commit (using the message listed) → push → short summary → **STOP**.

M0.1 must also create `.claude/settings.json` to switch off Claude Code's automatic attribution:

```json
{
  "includeCoAuthoredBy": false,
  "attribution": { "commit": "", "pr": "" }
}
```

### Phase 0: Setup

**M0.1: Project skeleton**
- Create folders, `.gitignore` (venv, `.env`, `data/inbox|raw|failed|private`, `__pycache__`, `*.xlsx` outputs), `.env.example`, `requirements.txt`, `README.md` stub, `PROGRESS.md`.
- Give PowerShell commands to create and activate a venv and install requirements.
- Explain how to install Tesseract on Windows and add it to PATH (or set its path in `.env`).
- Done when: `python -c "import pandas, psycopg, pytesseract, PIL"` works and `tesseract --version` works.
- Commit: `Set up project structure and environment`

**M0.2: Database setup**
- `sql/000_roles_and_schemas.sql` (creates the two roles and four schemas; I run it once in pgAdmin as postgres),
  `src/config.py`, `src/db.py`, `scripts/setup_db.py` (runs numbered SQL files in order and records them in a `public.schema_version` table so each runs once).
- Done when: setup script runs twice without errors (second run does nothing).
- Commit: `Add database roles, schemas and setup script`

### Phase 1: Fake data and raw ingestion

**M1.1: Fake receipt generator**
- `scripts/make_sample_receipts.py`: uses Pillow to draw ~50 realistic fake supplier receipts (3–4 fake vendors, messy item names like `CHKN BRST 10LB`, some tax, a few deliberate errors such as a wrong total, one duplicate).
- For each image, save a ground-truth JSON with the correct vendor, date, receipt number, line items and totals. (This becomes our labelled data for OCR evaluation.)
- Done when: `data/sample/` has images + matching JSON files. Tests check that each JSON's lines add up to its total, except the intentionally wrong ones.
- Commit: `Add synthetic receipt generator with ground truth`

**M1.2: Ingestion**
- `sql/001_raw.sql`, `src/ingest.py`.
- Core function: `ingest_image_bytes(data, original_name, source)` → validates the image, computes SHA-256, returns
  `("duplicate", file_id)` if the hash already exists, otherwise saves to `data/raw/<sha256>.<ext>`, inserts into
  `raw.receipt_file`, and returns `("new", file_id)`. Invalid images return `("rejected", reason)`.
  **This is the only way any image enters the system.** The inbox folder scan and the Streamlit upload/camera page (M3.2) all call it.
- Inbox scan: loop over `data/inbox/`, skip files modified in the last 10 seconds (may still be copying), call
  `ingest_image_bytes(..., source="inbox")`. Rejected files go to `data/failed/` with a logged reason.
- Done when: running it twice on the same inbox inserts each file once. Tests cover duplicate, bad file, non-image file, oversized file.
- Commit: `Add idempotent receipt ingestion with duplicate detection`

### Phase 2: OCR, parsing, cleaning

**M2.1: Tesseract OCR**
- `src/ocr.py`: `run_tesseract(path)` returns text + duration. Store in `raw.ocr_run`. Light image preprocessing (grayscale, resize) only if it clearly helps.
- Commit: `Add Tesseract OCR step`

**M2.2: Parsing**
- `src/parse.py`: turn raw OCR text into a dict: vendor, date, receipt number, line items (description, qty, unit price, line total), subtotal, tax, total. Use clear regex rules with comments. Missing fields become `None`, never guesses.
- Tests use fixed OCR text strings (no OCR needed in tests).
- Commit: `Parse OCR text into structured receipt fields`

**M2.3: Cleaning + loading**
- `sql/002_clean.sql`, `src/clean.py`: pandas standardizes dates, money (Decimal), vendor names (simple mapping table), whitespace and case. Keep raw values next to clean ones. Load into `clean.receipt` and `clean.receipt_line` with status `pending`.
- `src/run_pipeline.py`: runs ingest → OCR → parse → clean in order; safe to rerun.
- Done when: the full sample set loads; rerunning creates no duplicates.
- Commit: `Add pandas cleaning and load to PostgreSQL`

### Phase 3: Data quality, capture and review (first usable MVP after M3.4)

**M3.1: Quality checks**
- `sql/003_dq.sql`, `src/quality.py`: checks for missing required fields, invalid/future dates, negative values, line items not adding up to the subtotal (with a small tolerance), total ≠ subtotal + tax, same vendor + receipt number + total already exists. Write every result to `dq.check_result`. Any failure → `needs_review`; all pass → stays `pending` for approval.
- Never delete failing data.
- Commit: `Add data quality checks`

**M3.2: Receipt capture page (camera + file upload)**
- `app/Home.py` (password gate, `layout="centered"` for phones), `app/pages/1_Add_Receipt.py` with two tabs:
  - **Take Photo:** `st.camera_input("Take a photo of the receipt")`
  - **Upload Receipt:** `st.file_uploader(type=["jpg", "jpeg", "png"], accept_multiple_files=True)`.
    Tell staff in the UI: *on a phone, this button also lets you take a photo with the main camera*. That photo is usually sharper than `camera_input`, so it's better for OCR.
- Flow for both tabs: show a **preview** with `st.image`, then show a **Submit** button. Retaking (camera's built-in "Clear photo") or picking a different file replaces the preview before submitting.
  On Submit, call `ingest_image_bytes(bytes, name, source="camera" | "upload")`, then run OCR → parse → clean → quality checks for that receipt.
- Status messages: ✅ "Saved, receipt #123, sent to review" · ⚠️ "Duplicate, already saved as receipt #98" · ❌ "Rejected: not a valid image / over 10 MB". Show a spinner while processing.
- If the camera doesn't appear, show a short help note: allow camera permission in the browser, and on a phone the page must be opened over HTTPS (see section 11).
- Privacy: images are shown only by reading bytes from `data/raw/` and passing them to `st.image`. **Never** put receipt images in a static/public folder, and keep `server.enableStaticServing = false` in `.streamlit/config.toml`.
- Tests: the ingestion function is already tested; add a test that a camera-sized JPEG and an uploaded PNG both produce a `raw.receipt_file` row with the right `source`.
- Commit: `Add receipt capture page with camera and file upload`

**M3.3: Review page**
- `app/pages/2_Review.py`: show the receipt image next to extracted fields and failed checks; let me edit fields (log each change in `clean.correction`), then approve or reject.
- Commit: `Add receipt review page`

**M3.4: Excel export**
- `src/export_excel.py`: export approved receipts and lines to `exports/receipts_<date>.xlsx` (two sheets) plus a summary sheet (spend by vendor and month). Add a download button in Streamlit.
- **MVP done here:** photo in (camera, upload or folder) → reviewed data out to Excel.
- Commit: `Add Excel export`

### Phase 4: Star schema

**M4.1: Build the mart**
- `sql/004_mart.sql`, `src/load_mart.py`: populate `dim_date`, `dim_vendor`, `fact_purchase_line` from approved receipts (items unmapped for now go to an `UNMAPPED` item). Idempotent.
- Tests: running it twice gives the same row counts, and the fact table total equals the sum of approved receipt lines (reconciliation test).
- Add `sql/queries/` with 5 example analytics queries (spend per month, per vendor, top items, etc.).
- Commit: `Build star schema and analytics queries`

### Phase 5: OCR evaluation

**M5.1: Evaluation script**
- `src/evaluate_ocr.py`: compare pipeline output to ground-truth JSON. Field accuracy for vendor, date, receipt number, total (exact after normalization; money within $0.01). Line-item accuracy: match lines by description similarity, then compare qty, unit price and line total. Also record average processing time.
- Writes `docs/ocr_evaluation.md` with a results table and method explanation.
- Commit: `Add OCR evaluation against ground truth`

**M5.2: Gemini option**
- Add `run_gemini(path)` in `ocr.py` that asks Gemini for JSON in the same structure as `parse.py` output. Use it only when `OCR_METHOD=gemini` and an API key is set. Refuse to run it on `data/private/` unless `ALLOW_EXTERNAL_AI_ON_PRIVATE=true`.
- Rerun the evaluation on sample receipts for both methods and compare.
- Tests must not call the real API (mock it).
- Commit: `Add optional Gemini extraction and comparison`

### Phase 6: Prices and suppliers

**M6.1: Item normalization**
- `src/normalize.py` + `mart.item_mapping`: map messy descriptions to standard items (`CHKN BRST 10LB` → chicken breast, 10 lb). Parse pack sizes, convert to a standard unit (lb↔kg = 2.20462). Fill `dim_item` and the `standard_quantity` / `unit_price_standard` columns. Show an "unmapped items" list so I can add rules.
- Commit: `Normalize item names and units`

**M6.2: Price tracking**
- SQL views in `mart`: price history per item per vendor, % change vs. previous purchase, and flags when a price rises more than 10% (threshold in `.env`).
- Commit: `Add price history and increase alerts`

**M6.3: Supplier comparison**
- View: for each item bought from 2+ of our suppliers, the latest unit price at each, the cheapest, and **estimated** monthly savings = (our average monthly quantity) × (price difference). Label it "estimated". It ignores delivery fees, minimums and availability, and the page must say so.
- Commit: `Add supplier price comparison`

### Phase 7: Automation and dashboard

**M7.1: Scheduled runs**
- `run_pipeline.py` gets a lock file so two runs can't overlap, logs to `logs/pipeline.log`, and moves files that crash into `data/failed/`. Write exact steps in the README to set up Windows Task Scheduler to run it every 30 minutes.
- Commit: `Automate pipeline with Task Scheduler`

**M7.2: Dashboard pages**
- Streamlit pages: Overview (spend totals, receipt counts, data quality status), Spending (by month/vendor/item with date filters), Prices (history + alerts), Suppliers (comparison), OCR Evaluation (results table).
- Commit: `Add analytics dashboard`

### Phase 8: Chatbot and polish

**M8.1: Text-to-SQL chatbot**
- `src/chatbot.py` + `app/pages/Chatbot.py`. Send Gemini **only the mart schema description and the question** (no receipt data). Gemini returns one SQL query.
- Safety: parse the SQL with `sqlglot` and allow only a single `SELECT` on `mart` objects; run it as `receipts_readonly` with `statement_timeout = 5s`; add `LIMIT 200` if missing. Show the SQL, the results table, and a one-line plain-English answer (the answer may send the small result table to Gemini, so only allow this on sample data unless I approve).
- `tests/chatbot_questions.json`: 25 questions with expected answers computed by hand-written SQL. Script scores how many it gets right and how many unsafe queries were blocked. Tests mock the API.
- Commit: `Add read-only text-to-SQL chatbot with evaluation`

**M8.2: Polish**
- README: problem, architecture diagram (Mermaid), setup steps, screenshots using sample data, results section with **only measured numbers** (receipts processed, OCR accuracy per method, chatbot accuracy, duplicates caught, items tracked). `docs/architecture.md` and `docs/database_schema.md`.
- Commit: `Write README and documentation`

**M8.3: Study guide (only after everything else is done)**
- Create `docs/STUDY_GUIDE.md` to help me learn the finished project for interviews. Use the "Concepts to study later" list in `PROGRESS.md`.
- For each part of the pipeline, in the order data flows: what it does, which files do it, the key code to read, and why it was built that way (link to section 10).
- Use simple language and real-life analogies.
- End each section with 3–5 likely interview questions about it. Put the answers in a separate "Answers" section at the bottom of the file.
- Commit: `Add study guide`

---

## 9. Metrics to track (measured, never invented)

Receipts processed · processing success rate · OCR field accuracy (Tesseract vs. Gemini) · avg processing time ·
duplicates caught · DQ failures by type · items tracked · suppliers compared · estimated monthly savings ·
chatbot accuracy (x/25) · manual-entry time saved (**I'll measure this myself** with my family; leave a placeholder section in the README that says "to be measured").

---

## 10. Key design decisions (so I can explain them)

- **Plain SQL over an ORM:** the SQL is visible and testable, and it's what interviewers ask about.
- **Raw → clean → mart layers:** raw is never edited, so anything can be reprocessed; clean is reviewable; mart is for analytics only.
- **Hash-based file names:** prevent duplicates and path tricks, and give every file a stable ID.
- **Only approved receipts reach the mart:** analytics are trusted, and mistakes get caught in review first.
- **Idempotent steps:** rerunning anything is always safe, which makes scheduling and recovery simple.
- **Tesseract default, Gemini optional:** free and private by default; Gemini is compared fairly on fake data.
- **Read-only role for the chatbot:** AI-written SQL is treated as untrusted, so it physically can't change data.
- **Local only:** no user roles needed now. If it goes online later, add real user accounts and roles first.
- **One intake function for every source:** camera, upload and folder all go through `ingest_image_bytes`, so validation and duplicate detection can't be skipped.

---

## 11. Using the camera from a phone (HTTPS)

Browsers only allow camera access on **HTTPS pages or `localhost`**.

- **On the laptop running the app:** `http://localhost:8501` works with the camera, no setup needed.
- **On a phone on the same Wi-Fi:** `http://<laptop-ip>:8501` will **not** allow the camera. Options, in order of preference:
  1. **Tailscale (free personal plan):** install it on the laptop and the phones, then run `tailscale serve 8501`.
     This gives a private HTTPS address that only devices on my Tailscale network can open. Nothing is exposed to the internet.
  2. **mkcert + Streamlit SSL:** make a local certificate with `mkcert`, set `server.sslCertFile` and `server.sslKeyFile` in `.streamlit/config.toml`,
     and install mkcert's root certificate on each phone. Works offline but takes more setup per phone.
  3. **Fallback without HTTPS:** the **Upload Receipt** tab still works over plain local Wi-Fi, and on phones it lets staff take a photo with the camera app.
- **Do NOT** use public tunnels (ngrok, Cloudflare quick tunnels, etc.) with real receipts. They put the app on the public internet.
- Document the chosen setup step by step in the README under "Using on a phone".
