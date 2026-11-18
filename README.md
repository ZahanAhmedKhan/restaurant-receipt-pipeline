# Restaurant Receipt Pipeline

A local data pipeline for a family restaurant: staff photograph supplier receipts, and the
pipeline turns them into clean, reviewed data in PostgreSQL, with an Excel export, a Streamlit
dashboard, price alerts, a supplier comparison and a read-only text-to-SQL chatbot.

Built with free, open-source tools only, running on one Windows laptop.

## The problem

Today every receipt is typed into Excel by hand. That is slow, receipts get entered twice,
mistakes go unnoticed, the paper originals get lost, item names are inconsistent
(`CHKN BRST 10LB` vs. `CHICKEN BREAST BNLS 10 LB`), and nobody can easily see whether prices
are going up or which supplier is cheaper.

## What it does

- **Capture:** drop photos in `data/inbox/`, or use the app's camera / upload page (works on a phone).
  A long receipt can be taken as **several photos**; they are joined top to bottom and read as one
  receipt (like a document scanner app).
- **No duplicates:** every image is identified by its SHA-256 hash; the same photo is never stored twice.
- **Keeps originals:** images are stored unchanged under their hash, for audit.
- **Reads receipts:** Tesseract OCR (free, offline) by default; Gemini as an optional comparison.
- **Catches bad receipts:** 6 data-quality checks; anything suspicious goes to a review queue.
- **Human review:** fix fields next to the receipt image; every change is logged.
- **Analytics on trusted data only:** approved receipts feed a star schema (`mart`).
- **Standard items:** messy descriptions are mapped to standard items and units (lb, each, L).
- **Prices:** price history per item and supplier, with alerts for increases above a threshold.
- **Suppliers:** latest prices side by side, with **estimated** monthly savings.
- **Excel export** for the people who live in Excel, and a **chatbot** for quick questions.

## Architecture

```mermaid
flowchart LR
    subgraph Capture
        A[data/inbox folder]
        B[App: camera / upload]
    end
    A --> I
    B --> I
    I["ingest_image_bytes()<br/>validate JPG/PNG, SHA-256,<br/>duplicate check"] --> R[(raw.receipt_file<br/>data/raw/&lt;sha256&gt;)]
    R --> O["OCR<br/>Tesseract (default)<br/>Gemini (optional)"]
    O --> RO[(raw.ocr_run)]
    RO --> P[parse.py<br/>regex rules]
    P --> C[clean.py<br/>pandas]
    C --> CL[(clean.receipt<br/>clean.receipt_line)]
    CL --> Q[quality.py<br/>6 checks]
    Q --> DQ[(dq.check_result)]
    Q --> V{Review page<br/>fix, approve, reject}
    V -->|corrections| CL
    V -->|approved only| M[load_mart.py<br/>+ normalize.py]
    M --> MART[(mart star schema<br/>+ price / supplier views)]
    MART --> D[Streamlit dashboard]
    MART --> X[Excel export]
    MART --> CB["Chatbot<br/>(read-only role)"]
```

Layers: **raw** (what we received, never edited) → **clean** (standardized, reviewable) →
**dq** (quality results) → **mart** (star schema, approved receipts only).
More detail: [docs/architecture.md](docs/architecture.md) and
[docs/database_schema.md](docs/database_schema.md).

| Part | Tool |
|---|---|
| Language | Python 3.12 |
| Database | PostgreSQL, accessed with psycopg 3 and plain SQL (no ORM) |
| Schema changes | numbered `.sql` files in `sql/` applied by `scripts/setup_db.py` |
| Cleaning | pandas; money as `Decimal` / `NUMERIC(12,2)` |
| OCR | Tesseract (`pytesseract`); Gemini optional (`google-genai`) |
| App | Streamlit (multipage), password-protected |
| SQL safety for the chatbot | `sqlglot` + read-only PostgreSQL role |
| Tests | pytest (357 tests) |
| Scheduling | Windows Task Scheduler |

## Setup (Windows, PowerShell)

### 1. Python environment

```powershell
cd "<project folder>"
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If activation is blocked, run this once:
`Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

### 2. Tesseract OCR

1. Install it with winget:
   `winget install --id UB-Mannheim.TesseractOCR -e`
   (or download the installer from https://github.com/UB-Mannheim/tesseract/wiki)
2. Add `C:\Program Files\Tesseract-OCR` to your user PATH:
   ```powershell
   [Environment]::SetEnvironmentVariable("Path", [Environment]::GetEnvironmentVariable("Path", "User") + ";C:\Program Files\Tesseract-OCR", "User")
   ```
   Then close and reopen the terminal (and VS Code).
3. Or skip the PATH step and set `TESSERACT_CMD` in `.env` to the full path of `tesseract.exe`.

### 3. Config

```powershell
Copy-Item .env.example .env
```
Then edit `.env`. Set `DB_APP_PASSWORD` and `DB_READONLY_PASSWORD` to long random strings.

### 4. Database (one time)

```powershell
python scripts\bootstrap_db.py      # asks for the postgres superuser password (not saved)
python scripts\setup_db.py          # creates the tables; safe to run again
```

`bootstrap_db.py` creates the `receipts` and `receipts_test` databases, runs
`sql/000_roles_and_schemas.sql` in both (two roles, four schemas), and sets the role passwords
from `.env`. You can also run `000_roles_and_schemas.sql` by hand in pgAdmin; see the comments at
the top of the file.

### 5. Check everything works

```powershell
python -c "import pandas, psycopg, pytesseract, PIL; print('imports ok')"
tesseract --version
python -m pytest -q                 # uses the receipts_test database, never the real one
```

## Try it with the fake sample receipts

`data/sample/` has 51 synthetic receipts (made by `scripts/make_sample_receipts.py`), each with a
ground-truth JSON file: 50 from 4 made-up Ontario suppliers (postal codes, GST/HST numbers, 13% HST
on supplies) and 1 from a made-up Australian supplier. They include deliberate problems: 3 wrong
totals, 1 subtotal that doesn't match its lines, 1 re-photographed duplicate, 1 byte-for-byte
duplicate file and the non-Canadian receipt.

```powershell
python -m src.run_pipeline --sample        # ingest -> OCR -> parse -> clean -> checks -> mart
python scripts\demo_review_samples.py      # DEMO ONLY: plays the reviewer for the sample receipts
python scripts\set_app_password.py         # staff password (stored only as a hash)
python scripts\set_app_password.py --developer   # developer password (must be different)
streamlit run app\Home.py                  # http://localhost:8501
```

`demo_review_samples.py` corrects the sample receipts to their ground truth through the normal
review code (every change logged), approves the clean ones, rejects the duplicate and leaves the
deliberately wrong ones for a human. It never touches real receipts (checked by file hash).

## Receipts from any country (optional country rule)

By default receipts from **every country, store and restaurant** are accepted. Dates like
`06/07/2026` are read month-first; set `DATE_ORDER=DMY` in `.env` for day-first countries.

Optionally, accept only one country by setting `ALLOWED_COUNTRY=CA` (or `US`, `AU`) in `.env`.
"$" and store names don't tell the country (Costco is in Canada, the US and Australia), so
`src/country.py` looks for signs only one country prints:

- **Canada:** postal code (`L5R 3T7`), province + postal code, `HST`, `GST/HST`, `PST`, `QST`/`TVQ`/`TPS`,
  GST/HST business number (`121476329 RT0001`), "Canada"/"CAD".
- **Australia:** `ABN`, state + 4-digit postcode (`NSW 2144`), "Australia"/"AUD".
- **USA:** state + 5-digit ZIP (`WA 98027`), "sales tax", "USA".

With the rule on, a receipt that is clearly from another country is **rejected automatically**
(kept with status Rejected; the reason is logged). A receipt with no clear signs (e.g. OCR missed the address) goes
to **Check receipts** so a person decides. Plain "GST" alone is not a Canadian sign (Australia
uses it too). Tax lines `HST`, `GST/HST`, `GST` + `PST`, `TPS` + `TVQ` are read and added up.

## Start fresh with real receipts

```powershell
python scripts\reset_data.py --all     # removes EVERY receipt and its data (asks you to type YES)
python scripts\reset_data.py --demo    # or: remove only the fake demo receipts
```

This keeps the database structure, item rules, vendor names, settings, passwords, `data\sample\`
and `data\private\`. Real receipt images are stored in `data\raw\`, which is never committed to Git,
and they are never sent to Gemini.

## Daily use

```powershell
python -m src.run_pipeline       # process new photos in data\inbox\ (or let Task Scheduler do it)
streamlit run app\Home.py        # review, export, dashboards
python -m src.export_excel       # Excel file of approved receipts in exports\
```

**Long receipts:** on **Add Receipt**, choose "Several photos = one long receipt". With the camera,
take the photos top to bottom and press **Add as photo N** after each; with upload, select the photos
in order. Avoid overlapping photos: a line that appears twice is counted twice (the quality checks
will flag the receipt if the lines no longer add up).

**Two passwords, two menus** (not user accounts; whichever password is typed decides the menu):

| Login | Menu |
|---|---|
| Staff password | Start · Add receipt · Check receipts · Excel · Ask a question (plain wording, no technical details) |
| Developer password | the same, plus **Analytics** (Overview, Spending, Prices, Suppliers) and **Setup and quality** (Item rules, OCR evaluation), check names, change history and the chatbot's SQL |

Developer-only pages refuse a staff login even if the address is typed in directly.

## Run automatically every 30 minutes (Windows Task Scheduler)

The pipeline is safe to run on a schedule: a lock file (`pipeline.lock`) stops two runs from
overlapping, files that crash go to `data\failed\`, and everything is logged to `logs\pipeline.log`
(IDs, counts and error types only, never receipt contents).

**Option A: one PowerShell command.** Run it from the project folder:

```powershell
$project = (Get-Location).Path
$action  = New-ScheduledTaskAction -Execute "$project\.venv\Scripts\pythonw.exe" -Argument "-m src.run_pipeline" -WorkingDirectory $project
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 30)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable
Register-ScheduledTask -TaskName "Receipt Pipeline" -Action $action -Trigger $trigger -Settings $settings -Description "Process receipt photos in data\inbox"
```

**Option B: by hand.**

1. Open **Task Scheduler** (Start menu, type "Task Scheduler").
2. **Action → Create Task…**
3. **General** tab: Name `Receipt Pipeline`. Choose "Run only when user is logged on".
4. **Triggers** tab → **New…**: "On a schedule", **One time**, start now; tick **Repeat task every: 30 minutes**,
   for a duration of: **Indefinitely** → OK.
5. **Actions** tab → **New…**: "Start a program".
   - Program/script: `<project folder>\.venv\Scripts\pythonw.exe`
   - Add arguments: `-m src.run_pipeline`
   - Start in: `<project folder>`
6. **Settings** tab: "If the task is already running": **Do not start a new instance** → OK.

(`pythonw.exe` runs without opening a console window.)

**Check it works:** right-click the task → **Run**, then look at the end of the log:
```powershell
Get-Content logs\pipeline.log -Tail 5
```
Exit codes: `0` done, `1` error (details in the log), `2` skipped because another run was still going.

To remove it: `Unregister-ScheduledTask -TaskName "Receipt Pipeline"`

## OCR evaluation and the optional Gemini method

```powershell
python -m src.evaluate_ocr                   # Tesseract vs. ground truth -> docs\ocr_evaluation.md
```

To compare with Gemini (free tier): get an API key at https://aistudio.google.com/apikey, put it in
`.env` as `GEMINI_API_KEY=...`, then run:

```powershell
python -m src.evaluate_ocr --method gemini   # adds a Gemini column to docs\ocr_evaluation.md
```

To use Gemini in the pipeline, also set `OCR_METHOD=gemini`. Gemini only ever receives the fake
sample receipts (checked by file hash). Real receipts stay on Tesseract unless you set
`ALLOW_EXTERNAL_AI_ON_PRIVATE=true`.

## Chatbot (text-to-SQL, read-only)

Needs `GEMINI_API_KEY` in `.env`. Use the **Chatbot** page, or the terminal:

```powershell
python -m src.chatbot "How much did we spend with each vendor?"
python -m src.chatbot --evaluate     # score on the 25 questions in tests\chatbot_questions.json
```

Safety: Gemini only gets the mart table structure and the question, never receipt data. The SQL
it returns must parse (with `sqlglot`) as a single SELECT on `mart.` objects, gets `LIMIT 200`, and
runs as the `receipts_readonly` role in a read-only transaction with a 5-second timeout. The
one-line plain-English answer sends the small result table to Gemini, so it is only produced when
all stored images are sample receipts (or you allow it).

## Using on a phone

Browsers only allow the camera on **HTTPS** pages or on `localhost`. A phone opening
`http://<laptop-ip>:8501` can still use **Upload Receipt** (which can take a photo with the phone's
camera app), but not **Take Photo**.

Chosen setup: **Tailscale** (free personal plan). It gives a private HTTPS address that only your
own devices can open. Nothing is put on the public internet.

1. Install Tailscale on the laptop (https://tailscale.com/download) and sign in.
2. Install the Tailscale app on each phone and sign in with the same account.
3. In the Tailscale admin console, under **DNS**, turn on **MagicDNS** and **HTTPS certificates**.
4. Start the app on the laptop: `streamlit run app\Home.py`
5. In a second terminal on the laptop: `tailscale serve --bg 8501`
6. It prints an address like `https://<laptop-name>.<tailnet>.ts.net`. Open it on the phone.
7. To stop sharing: `tailscale serve reset`

Do **not** use public tunnels (ngrok, Cloudflare quick tunnels, etc.) with real receipts.

## Privacy and security

- Runs locally. Real receipts, OCR output and exports never go in Git (`.gitignore`); the public
  demo uses fake receipts only.
- Secrets live in `.env` (not committed). The app password is stored only as a salted PBKDF2 hash.
- Two database roles: `receipts_app` (pipeline and app, not a superuser) and `receipts_readonly`
  (SELECT on `mart` only, used only by the chatbot).
- Parameterized queries everywhere.
- Every image is checked: JPG/PNG only (real format, not just the extension), opens and verifies in
  Pillow, max 10 MB and 50 megapixels, saved under a server-generated name (`<sha256>.<ext>`).
- Receipt images are never served from a static folder (`enableStaticServing = false`).
- Logs contain IDs, counts and error types, never receipt contents.

## Results on real receipts (public SROIE dataset)

Measured by `python -m src.evaluate_sroie` on **626 real, labelled receipts** from the public SROIE
dataset (ICDAR 2019, Malaysian shops), using the same code path as the pipeline
(Tesseract → `parse.py` → `clean.py`). The parser's total/date rules were improved using only the
**dev split** (receipts 000–299); the **test split** (300–625, 326 receipts) was held out and never
looked at while changing code.

| Metric (held-out test split, 326 real receipts) | Before | After |
|---|---|---|
| Total amount correct (±$0.01) | 20.9% | **60.7%** |
| Date correct | 1.9% | **77.1%** |
| Vendor name close (similarity ≥ 0.8) | 38.7% | 38.7% (unchanged) |

All 626 receipts: OCR'd with 0 failures in 643 s (about 1.0 s per receipt); after the change,
57.0% totals and 78.2% dates correct across all 626. Full report: [docs/sroie_evaluation.md](docs/sroie_evaluation.md).
The dataset is downloaded into `data/external/` and is not committed.

## Results on the synthetic sample receipts

All numbers below were measured by the code in this repo on the fake sample data.

| Metric | Result | How it was measured |
|---|---|---|
| Images processed | 51 → 50 receipts, 0 failures | `run_pipeline --sample` |
| Duplicates caught | 2 of 2 planted: 1 exact file (hash, at ingestion), 1 re-photographed receipt (quality check) | pipeline + `dq.check_result` |
| Optional country check (`ALLOWED_COUNTRY=CA`) | 1 of 1 planted Australian receipt rejected automatically; 0 of 49 Canadian receipts wrongly flagged | `src/country.py` + `src/quality.py` |
| OCR (Tesseract): vendor / date / receipt no. / total | 100% / 98.0% / 100% / 96.1% (the date miss is the Australian day-first date) | `src/evaluate_ocr.py` |
| OCR (Tesseract): line items | 98.5% found, 73.0% fully correct (quantity 84.2%, unit price 88.8%, line total 89.2% of matched lines) | `src/evaluate_ocr.py` |
| OCR (Tesseract): average time | 540 ms per receipt | `src/evaluate_ocr.py` |
| OCR (Gemini) | not measured yet | `evaluate_ocr --method gemini` |
| Data-quality failures right after OCR (50 receipts) | required fields 39, lines ≠ subtotal 21, total ≠ subtotal + tax 7, duplicate 1, invalid date 1, not Canadian 1, negative 0 → 42 sent to review, 1 rejected automatically, 7 pending | `src/quality.py` (fresh run in the test database) |
| Review (demo reviewer on sample data) | 114 field corrections logged; 44 approved, 1 rejected (duplicate), 4 left for a human | `scripts/demo_review_samples.py` |
| Items tracked | 24 standard items, 0 unmapped descriptions | `mart.dim_item` |
| Price alerts | 1 (the planted +14.8% chicken breast increase) | `mart.v_price_alerts` |
| Suppliers compared | 5 items across 4 suppliers | `mart.v_supplier_savings` |
| Estimated monthly savings | $57.33 (**estimate**: ignores delivery fees, minimums, quality, availability) | `mart.v_supplier_savings` |
| Chatbot accuracy (Gemini text-to-SQL) | **22 of 25** questions answered correctly (88%); 2 wrong, 1 not answered because every Gemini model was busy at that moment | `python -m src.chatbot --evaluate` |
| Chatbot safety | 5 unsafe requests: Gemini wrote harmful SQL for 3 (DELETE, DROP, CREATE TABLE), all 3 blocked; the other 2 came back as harmless read-only queries; 0 data changed or exposed. Unit tests: 21 of 21 attack queries blocked | `src/chatbot.py`, `tests/test_chatbot.py` |
| Chatbot response time | 1.0–2.1 s per question (3 questions timed) | `chatbot.ask` |
| Automated tests | 392 passing | `python -m pytest` |

Full OCR report: [docs/ocr_evaluation.md](docs/ocr_evaluation.md).

### Manual-entry time saved

To be measured (with the family, on real receipts).

## Screenshots

Not added yet. To add them: load the sample data (see above), open each page, and save
screenshots in `docs/screenshots/`.

## Project layout

```
sql/        numbered schema files (000 run by the superuser, 001+ by setup_db.py) and queries/
src/        pipeline code (ingest, ocr, parse, clean, quality, review, load_mart, normalize,
            prices, export_excel, evaluate_ocr, chatbot, run_pipeline, ...)
app/        Streamlit app (Home.py + pages/)
scripts/    setup, sample generator, demo reviewer, app password
tests/      pytest tests (+ chatbot_questions.json)
docs/       architecture, database schema, OCR evaluation
data/       inbox/ raw/ failed/ private/ (all gitignored) and sample/ (fake receipts)
```
