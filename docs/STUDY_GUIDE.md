# Study guide

How to use this guide: read the sections in order. They follow one receipt photo through the
system, from the moment it arrives to the moment it shows up on a dashboard. For each part you get:
what it does, which files do it, the key code to read, and why it was built that way. Each section
ends with interview questions. Try to answer them out loud first, then check the
[Answers](#answers) at the bottom.

The "Concepts to study later" list in `PROGRESS.md` is the full checklist of topics; this guide
puts them in context. "Design decisions" refers to section 10 of `CLAUDE.md` and to
[architecture.md](architecture.md).

**The one-sentence version (learn this first):**
> Photos of supplier receipts go through validation and hashing, OCR, parsing and cleaning into
> PostgreSQL; quality checks send doubtful receipts to a human review page; only approved receipts
> are loaded into a star schema that powers price alerts, supplier comparison, Excel exports and a
> read-only chatbot.

**Analogy for the whole project: a restaurant kitchen.**
Deliveries arrive at the back door (inbox), get checked and labelled (ingestion), unpacked and
sorted (OCR, parsing, cleaning), inspected (quality checks), approved by the head chef (review),
and only then put on the shelves the cooks use (the mart). Nobody cooks from an unchecked box.

---

## 1. Setup: config, database connection, schema files, roles

**What it does.** Loads settings from `.env`, opens database connections, creates the database
structure in numbered steps, and sets up two database users with different powers.

**Files.** `src/config.py`, `src/db.py`, `sql/000_roles_and_schemas.sql`, `scripts/bootstrap_db.py`,
`scripts/setup_db.py`, `.env.example`, `.gitignore`.

**Key code to read.**
- `config.py`: every setting in one place; `load_dotenv(..., override=False)` so tests can point
  `DB_NAME` at the test database.
- `db.get_connection()`: note `autocommit=True` and the docstring about `with conn.transaction():`.
- `setup_db.apply_migrations()`: lists `001_*.sql`, skips files already in `public.schema_version`,
  runs each new file plus its version row in one transaction.
- `000_roles_and_schemas.sql`: `CREATE ROLE ... LOGIN NOSUPERUSER`, `CREATE SCHEMA ... AUTHORIZATION`,
  `GRANT`, `ALTER DEFAULT PRIVILEGES`.
- `bootstrap_db.set_role_password()`: `psycopg.sql.Literal` because `ALTER ROLE` can't take `%s`.

**Why.** Plain SQL files instead of an ORM or Alembic keep the SQL visible (design decisions).
Two roles apply the *principle of least privilege*: the chatbot's role can only read the mart.
Secrets stay in `.env`, which Git ignores.

**Analogy.** The roles are like keys: the manager's key opens every room; the visitor's badge only
opens the dining room, and only to look.

**Interview questions**
1. What is a schema migration, and how does `setup_db.py` make sure each file runs only once?
2. Why does the project use two PostgreSQL roles? What can `receipts_readonly` do?
3. What does `ALTER DEFAULT PRIVILEGES` solve that a plain `GRANT SELECT ON ALL TABLES` doesn't?
4. Why are connections in autocommit mode, and when do we still use a transaction?
5. How do you keep passwords out of a Git repository?

---

## 2. Fake data with ground truth

**What it does.** Draws 50 realistic receipt images from 4 made-up vendors and saves, for each,
a JSON file with the correct values. Some receipts are broken on purpose.

**Files.** `scripts/make_sample_receipts.py`, `data/sample/`, `tests/test_sample_receipts.py`.

**Key code to read.** `build_receipts()` (random but seeded), `add_deliberate_errors()`,
`draw_receipt()` (Pillow: text, rotation, noise, blur), `to_json()` (money as strings), the
duplicate section at the end of `generate()`, and `PRICE_JUMP` (a planted 15% price rise).

**Why.** Real receipts are private and unlabelled. Synthetic data gives a public demo and
*labelled* data for measuring OCR accuracy. A fixed seed makes it repeatable. The font was switched
to Courier New Bold after measuring that the old font's dotted zero was read as 8 or @.

**Analogy.** A driving-test course with known obstacles: you know exactly where the cones are,
so you can score the driver.

**Interview questions**
1. What is ground truth and why do you need it?
2. Why use a random seed in a data generator?
3. Why store money as strings in the JSON instead of numbers?
4. What deliberate errors did you plant, and which part of the system should catch each one?
5. What are the limits of evaluating on synthetic data?

---

## 3. Ingestion: the only way in

**What it does.** Checks that a file is a real, reasonable JPG/PNG, computes its SHA-256 hash,
stores it as `data/raw/<sha256>.<ext>`, and records it in `raw.receipt_file`. The same bytes twice
→ "duplicate". The inbox scan feeds folder files into the same function.

**Files.** `src/ingest.py`, `sql/001_raw.sql`, `tests/test_ingest.py`.

**Key code to read.** `validate_image()` (size → extension → real format → pixel count →
`verify()`), `ingest_image_bytes()` (look up hash → write file → `INSERT ... ON CONFLICT DO NOTHING`),
`scan_inbox()` (skips files younger than 10 s, moves rejected/crashed files to `data/failed/`).

**Why.** One intake function for every source means validation and duplicate detection can't be
skipped (design decisions). Hash file names prevent duplicates *and* path tricks (`../../evil.jpg`).
The real format is checked from the bytes because an extension can lie.

**Analogy.** A bouncer with a fingerprint scanner: everyone comes through one door, fake IDs are
turned away, and someone who already came in is recognised.

**Interview questions**
1. How does the system detect duplicate receipts? Why a hash instead of the file name?
2. What checks does an uploaded image go through, and why each one?
3. What is a path traversal attack and how does this design prevent it?
4. Why does the inbox scan skip files modified in the last 10 seconds?
5. What does `ON CONFLICT DO NOTHING` do here and why is it needed even after the SELECT?

---

## 4. OCR: reading the image

**What it does.** Turns each new image into text with Tesseract (or JSON with Gemini) and stores
the result and timing in `raw.ocr_run`.

**Files.** `src/ocr.py`, `tests/test_ocr.py`, `tests/test_gemini.py`.

**Key code to read.** `run_tesseract()` (`--psm 6`), `ocr_file()` (success: OCR row + status in one
transaction; failure: only the *error type* is stored, status `failed`), `run_gemini()`,
`check_allowed_for_external_ai()` (sample images only, checked by hash), `_call_gemini()` (the one
place that calls the API, replaced in tests).

**Why.** Tesseract is free and offline, so it is the default; Gemini is optional and compared
fairly on fake data. Preprocessing (grayscale, upscaling) was measured and did not clearly help, so
it isn't used. Raw OCR output is kept so it can be re-parsed later without re-running OCR.

**Analogy.** A typist copying a crumpled receipt: fast, but sometimes reads a 1 as an "l".

**Interview questions**
1. What does Tesseract's `--psm` option do, and how did you choose 6?
2. Why store the raw OCR text instead of only the parsed result?
3. How do you make sure real receipts are never sent to Gemini by accident?
4. How do you test code that calls an external API without calling it?
5. What happens when OCR fails on a file?

---

## 5. Parsing: text to fields

**What it does.** Turns OCR text into vendor, date, receipt number, line items, subtotal, tax and
total. Anything it can't read confidently becomes `None`.

**Files.** `src/parse.py`, `tests/test_parse.py`.

**Key code to read.** The regex patterns at the top (`^`, `$`, `re.M`, `re.I`), `fix_digits()`
(O/@ → 0, l/I → 1, only inside number tokens), `parse_money()` (exactly two decimals),
`item_section()` (between the column header and SUBTOTAL/TAX/TOTAL), `parse_item_line()` (finds the
unit token from the right because descriptions contain numbers like `80/20 10LB`).

**Why.** "Never guess": a `None` goes to human review; a wrong guess would silently corrupt
spending numbers. Regex rules are explainable and testable with fixed strings (no OCR needed).

**Analogy.** Filling in a form from someone's messy notes: if you can't read a number, you leave
the box empty and flag it, you don't make one up.

**Interview questions**
1. Why does the parser return `None` instead of a best guess?
2. Why is the unit found by scanning from the right?
3. Which OCR character confusions do you fix, and why only inside number tokens?
4. How do you unit-test a parser for OCR output?
5. Give an example of a bug you found by testing the parser on real OCR output.

---

## 6. Cleaning and loading

**What it does.** Standardizes the parsed values with pandas (dates from 6 formats, money as
`Decimal`, vendor names through a mapping table with fuzzy matching, whitespace and case) and loads
`clean.receipt` + `clean.receipt_line` with status `pending`, keeping the raw values next to the clean ones.

**Files.** `src/clean.py`, `sql/002_clean.sql`, `src/run_pipeline.py`, `tests/test_clean.py`.

**Key code to read.** `clean_date()`, `clean_money()`, `standardize_vendor()` (exact, then
`difflib.get_close_matches`), `clean_receipt()` (DataFrame with `dtype=object` so `None` stays `None`),
`insert_receipt()` (receipt + lines in one transaction), `process_file()` (skips files that already
have a receipt), `run_pipeline.run()`.

**Why.** Never use float for money (binary floats can't represent 0.10 exactly). Keeping raw beside
clean makes every value auditable. The status column (`new → ocr_done → parsed`) makes each step
pick up only unfinished work, so reruns are safe (idempotent).

**Analogy.** Sorting groceries into labelled containers, but keeping the original packaging
label taped on the side.

**Interview questions**
1. Why `Decimal` / `NUMERIC(12,2)` instead of float for money?
2. What does idempotent mean, and how is the pipeline idempotent?
3. Why keep `vendor_raw` next to `vendor_name`?
4. NaN vs. None in pandas: what problem did `dtype=object` solve?
5. Why are the receipt and its lines inserted in one transaction?

---

## 7. Data quality checks

**What it does.** Runs 6 checks on every receipt (required fields, valid date, no negatives,
lines add up to subtotal, total = subtotal + tax, not a duplicate), stores every result, and sets
`needs_review` if anything fails.

**Files.** `src/quality.py`, `sql/003_dq.sql`, `tests/test_quality.py`.

**Key code to read.** Each `check_*` function returns `(passed, details)`; `SIMPLE_CHECKS`;
`check_not_duplicate()` (only flags the *later* receipt); `run_checks()` (delete old results +
insert new ones + update status, in one transaction; approved/rejected receipts keep their status).

**Why.** Bad data is never deleted, only flagged (CLAUDE.md M3.1). Money comparisons allow a
2-cent tolerance for rounding. Storing every result (not only failures) lets the dashboard show
failure rates by check.

**Analogy.** A checklist at the loading dock: missing invoice number? numbers don't add up?
already received? → put it aside for the manager.

**Interview questions**
1. Name the quality checks and the data-quality dimension each covers.
2. Why compare money with a tolerance?
3. Why does the duplicate check flag only the later receipt?
4. Why replace a receipt's old results instead of appending new ones?
5. What measured failure rates did you see on the sample data, and what caused most of them?

---

## 8. Capture page and app security

**What it does.** A phone-friendly Streamlit page with **Take Photo** and **Upload Receipt** tabs;
on Submit, the image goes through ingestion → OCR → parse → clean → checks immediately.

**Files.** `app/Home.py`, `app/app_common.py`, `app/pages/1_Add_Receipt.py`, `src/auth.py`,
`scripts/set_app_password.py`, `.streamlit/config.toml`, `run_pipeline.process_single_image()`.

**Key code to read.** `app_common.setup_page()` / `require_password()` (called at the top of
every page, `st.stop()` if not logged in), `auth.hash_password()` (salted PBKDF2, 600k iterations),
`auth.verify_password()` (`hmac.compare_digest`), `show_result()` messages.

**Why.** Two passwords (staff and developer) are enough for a local family app: the password picks
a simple or a full menu (`Home.py` builds it with `st.navigation`; developer-only pages also check
`setup_page(..., developer_only=True)`). No user accounts needed while it stays local.
The password is stored only as a slow, salted hash. Images are shown by reading bytes and passing
them to `st.image`; static serving is off. Phone cameras need HTTPS, so Tailscale gives a private
HTTPS address without exposing the app to the internet.

**Analogy.** The staff entrance with a keypad: one code for the family, written down nowhere
except as a scrambled version.

**Interview questions**
1. Why hash passwords with a salt and many iterations? What is `compare_digest` for?
2. Why can't a phone use the camera on `http://<laptop-ip>:8501`?
3. Why is Tailscale safer than ngrok for this app?
4. How does every page enforce the password?
5. How did you test the Streamlit pages?

---

## 9. Review

**What it does.** Shows the receipt image next to the extracted fields and failed checks; the
reviewer edits fields and lines, then approves or rejects. Every change is logged in
`clean.correction`, and the checks run again after edits.

**Files.** `src/review.py`, `app/pages/2_Review.py`, `tests/test_review.py`.

**Key code to read.** `convert()` (typed text → clean value), `values_equal()` (compare by value so
`2 == 2.000`), `save_corrections()` (header fields, changed/new/deleted lines, one transaction, then
`quality.run_checks`), `set_review_status()`.

**Why.** Human-in-the-loop: OCR is imperfect, so a person confirms the numbers before they count.
The correction log is an audit trail (who changed what from what). Comparing by value avoids
logging fake "changes".

**Analogy.** The head chef tasting before the dish goes out, and writing down every adjustment.

**Interview questions**
1. Why is there a human review step at all?
2. What is stored in `clean.correction` and why is it useful?
3. What bug would you get if you compared `Decimal('2.000')` and `Decimal('2')` as text?
4. What happens to the mart when an approved receipt is corrected?
5. Why rerun the quality checks after a correction?

---

## 10. Excel export

**What it does.** Exports approved receipts to an Excel file with three sheets: Receipts, Lines,
and Summary (spend by vendor and month with totals).

**Files.** `src/export_excel.py`, `app/pages/3_Export.py`, `tests/test_export_excel.py`.

**Key code to read.** `spend_summary()` (`groupby` + `unstack`, Decimal kept exact),
`build_workbook()` (`pd.ExcelWriter` into `io.BytesIO`), `format_sheet()`.

**Why.** The family already works in Excel; meeting users where they are is part of adoption.
Only approved data is exported.

**Interview questions**
1. Why build the file in memory (`BytesIO`)?
2. How do you pivot spend by vendor and month in pandas?
3. Why export only approved receipts?

---

## 11. Star schema (the mart)

**What it does.** Builds `dim_vendor`, `dim_item`, `dim_date` and `fact_purchase_line` (grain: one
line item on one approved receipt) from approved data, in one transaction, every time.

**Files.** `src/load_mart.py`, `sql/004_mart.sql`, `sql/queries/`, `tests/test_load_mart.py`.

**Key code to read.** `UPSERT_VENDORS`, `UPSERT_DATES` (`generate_series` calendar), `DELETE_FACTS`
+ `INSERT_FACTS`, `ENSURE_UNKNOWN_ROWS` (`UNMAPPED` item, date key 0), the reconciliation test
`test_reconciliation_fact_total_equals_approved_lines`.

**Why.** A star schema makes analytics queries simple and fast to write (join facts to a few
dimensions). A full rebuild (delete + insert in one transaction) is idempotent and automatically
picks up corrections. `line_id UNIQUE` gives lineage back to the clean line and the original photo.

**Analogy.** The fact table is a till roll of every item bought; the dimensions are the reference
cards (who sold it, what it is, which day).

**Interview questions**
1. What is the grain of your fact table and why choose it?
2. Facts vs. dimensions: give examples from this project.
3. Why a full rebuild instead of incremental loading? When would you switch?
4. What is a reconciliation test?
5. How would you trace a number on the dashboard back to the original photo?

---

## 12. Item normalization and units

**What it does.** Maps messy descriptions to standard items with rules in `mart.item_mapping`
(longest matching pattern wins), parses pack sizes (`10LB`, `4.5KG`, `15DZ`, `1GAL`), converts to
standard units (lb, each, L), and fills `standard_quantity` and `unit_price_standard`.

**Files.** `src/normalize.py`, `sql/005_item_mapping.sql`, `app/pages/4_Items.py`, `tests/test_normalize.py`.

**Key code to read.** `pattern_to_regex()`, `find_rule()`, `parse_pack_size()` (last match wins),
`to_standard()` (kg × 2.20462 → lb, DZ × 12 → each, GAL × 3.78541 → L), `standard_quantity()`,
`normalize_facts()` (`executemany` updates), `unmapped_descriptions()`.

**Why.** Without normalization, "CHKN BRST 10LB" and "CHICKEN BREAST BNLS 10 LB" are different
products and prices can't be compared. Rules in a table are editable without code changes; the
Items page shows what still needs a rule.

**Analogy.** A translator's dictionary: each supplier speaks its own dialect; the dictionary turns
all of them into one language.

**Interview questions**
1. Why normalize item names? What breaks without it?
2. How does the rule matching work, and why does the longest pattern win?
3. How do you get a price per pound from "2 cases of 10LB at $32.50"?
4. Why keep rules in a database table instead of in code?
5. What happens to a line with no matching rule?

---

## 13. Price tracking and supplier comparison

**What it does.** SQL views show the price history per item and supplier with % change, flag
increases above a threshold, and compare suppliers' latest prices with **estimated** monthly savings.

**Files.** `sql/006_price_views.sql`, `sql/007_supplier_comparison.sql`, `src/prices.py`,
`app/pages/6_Prices.py`, `app/pages/7_Suppliers.py`, `tests/test_prices.py`, `tests/test_suppliers.py`.

**Key code to read.** `v_price_history` (weighted price = sum(amount) / sum(quantity), `lag()` over
a named `WINDOW`), `v_price_alerts` (threshold from `mart.setting`, copied from `.env` on each build),
`v_supplier_comparison` (`DISTINCT ON` for the latest price, `min() OVER`, `first_value()`),
the hand-calculated test `test_estimated_savings_hand_calculation`.

**Why.** Views keep the logic in SQL where the chatbot and dashboards can share it. Savings are
labelled *estimated* because they ignore delivery fees, minimums, quality and availability: an
honest number beats an impressive one.

**Interview questions**
1. How does `lag()` work, and what does `PARTITION BY` do in your price history?
2. How do you get "the latest row per group" in PostgreSQL?
3. Why is the threshold stored in a table when it is configured in `.env`?
4. How is estimated monthly savings calculated, and what does it ignore?
5. Why a weighted average price instead of the average of unit prices?

---

## 14. Measuring OCR (and comparing with Gemini)

**What it does.** Runs the same extraction code as the pipeline on all 50 sample images and scores
it against the ground truth: header fields, line items (matched by description similarity), timing.

**Files.** `src/evaluate_ocr.py`, `docs/ocr_evaluation.md`, `docs/ocr_evaluation.json`, `tests/test_evaluate_ocr.py`.

**Key code to read.** `compare_header()`, `match_lines()` (greedy, each extracted line used once,
similarity ≥ 0.6), `compare_lines()`, `evaluate()`, `render_report()`.

**Why.** "Never invent metrics": every accuracy number in the README comes from this script.
Field-level and record-level ("fully correct") accuracy tell different stories: Tesseract got the
vendor right 100% of the time but only 69.2% of lines fully right.

**Interview questions**
1. How do you measure OCR accuracy for line items when the number of lines can differ?
2. Field accuracy vs. "fully correct" accuracy: why report both?
3. What were your measured results, and what was the weakest field?
4. Why must the evaluation use the same code path as the pipeline?

---

## 15. Automation

**What it does.** Lets Windows Task Scheduler run the pipeline every 30 minutes safely: a lock file
prevents overlapping runs, a rotating log records what happened, crashing files are set aside.

**Files.** `src/run_pipeline.py` (`PipelineLock`, `setup_logging`, `main`), `README.md` (Task Scheduler
steps), `tests/test_scheduling.py`.

**Key code to read.** `PipelineLock.acquire()` (`os.O_CREAT | os.O_EXCL`: create-if-not-exists in
one atomic step; stale after 2 hours), `main()` exit codes 0/1/2, `scan_inbox()` crash handling,
`clean.process_pending()` crash handling.

**Why.** Idempotent steps make scheduling simple: if a run dies halfway, the next run continues.
A lock based on file age (not process IDs) because on Windows `os.kill` can terminate processes.

**Analogy.** A "do not disturb" sign on the door: if it's up, come back later; if it's been up
for hours, someone forgot it.

**Interview questions**
1. Why does a scheduled job need a lock, and why must creating it be atomic?
2. What is a stale lock and how do you handle it?
3. Why log only IDs and error types?
4. What happens if one inbox file crashes the ingestion?

---

## 16. Dashboard

**What it does.** Streamlit pages: Overview (Home), Spending (date filter, by month/vendor/item),
Prices, Suppliers, OCR Evaluation.

**Files.** `src/dashboard.py`, `app/charts.py`, `app/Home.py`, `app/pages/5_Spending.py`,
`6_Prices.py`, `7_Suppliers.py`, `8_OCR_Evaluation.py`, `tests/test_dashboard.py`.

**Key code to read.** `dashboard.spend_by_month()` (parameterized `BETWEEN`), `charts.vendor_color_scale()`
(each vendor keeps the same color everywhere), `charts.price_lines()`.

**Why.** Queries live in `src/` (testable), drawing lives in `app/`. Bars for comparisons, lines
for change over time, a table view under every chart, tooltips on hover.

**Interview questions**
1. Why keep queries out of the page files?
2. Why should a vendor keep the same color on every chart?
3. When do you use a bar chart vs. a line chart?

---

## 17. Chatbot (text-to-SQL)

**What it does.** Turns a plain-English question into SQL with Gemini, checks the SQL, runs it
read-only on the mart, and shows the SQL, the result table and (on sample data) a one-line answer.

**Files.** `src/chatbot.py`, `app/pages/9_Chatbot.py`, `tests/chatbot_questions.json`, `tests/test_chatbot.py`.

**Key code to read.** `schema_description()` (structure only, from `information_schema`),
`validate_sql()` (one statement, root must be SELECT/UNION, forbidden node types anywhere,
every table `mart.` or a CTE, forbidden function prefixes, `LIMIT 200`), `run_readonly()`
(`SET TRANSACTION READ ONLY`, `SET LOCAL statement_timeout`), `answer_allowed()`, `results_match()`,
`evaluate()`; the 21 attack strings in `UNSAFE_SQL`.

**Why.** AI-written SQL is untrusted input. Defense in depth: even if the validator missed
something, the read-only role physically can't change data, the transaction is read-only, and the
timeout and row limit stop expensive queries (design decisions). Gemini never sees receipt data
when writing SQL; the optional answer step would, so it's limited to sample data.

**Analogy.** A new intern writing database queries: helpful, but you check their work, give them
read-only access, and set a time limit.

**Interview questions**
1. What are the layers of protection around the AI-generated SQL?
2. Why parse the SQL with `sqlglot` instead of checking with a regex like `startswith("SELECT")`?
3. Give an example of a dangerous query that starts with SELECT or WITH.
4. How do you score a text-to-SQL system when the generated SQL can be written many ways?
5. What data does the model see, and how did you limit it?

---

## 18. Testing strategy (across the whole project)

**What it does.** 339 pytest tests: pure-function tests with fixed inputs, database tests against a
separate `receipts_test` database that is emptied before each test, Streamlit page tests with
`AppTest`, and mocked external APIs.

**Files.** `tests/conftest.py` (sets `DB_NAME` to the test DB, `db_conn` fixture truncates tables),
`tests/helpers.py`, every `tests/test_*.py`.

**Why.** Tests let you change code with confidence. A separate test database means tests never
touch real data. Mocking `_call_gemini` / `_call_gemini_text` means tests are free, fast and offline.

**Interview questions**
1. How do your tests avoid touching the real database?
2. What is a pytest fixture? Give an example from this project.
3. What did tests catch that you would have missed otherwise?
4. How do you test code that depends on an external API?

---

## Answers

### 1. Setup
1. A migration is a versioned change to the database structure. `setup_db.py` keeps a table
   `public.schema_version` with the name of every applied file; it runs only files not listed,
   each in a transaction together with its version row, so a file either fully applies and is
   recorded, or nothing happens.
2. Least privilege. `receipts_app` runs the pipeline and app; `receipts_readonly` can only `USAGE`
   the `mart` schema and `SELECT` its tables and views. It's used only by the chatbot, so even a
   bad AI-generated query can't change or read private raw data.
3. `GRANT ... ON ALL TABLES` only covers tables that exist *now*. `ALTER DEFAULT PRIVILEGES FOR ROLE
   receipts_app IN SCHEMA mart` makes future tables and views created by the app readable too.
4. With autocommit, each statement is saved at once, which avoids a psycopg trap we actually hit:
   a SELECT silently opened a transaction and later `conn.transaction()` blocks became savepoints
   that were never committed. We still use `with conn.transaction():` when several statements must
   succeed together (receipt + lines, the mart rebuild).
5. Put them in `.env` (loaded with python-dotenv), add `.env` to `.gitignore`, commit only
   `.env.example` with placeholders, and never print secrets in logs or errors.

### 2. Fake data
1. The known correct answer for each example. Without it you can't measure accuracy.
2. The same seed produces the same data every run, so results are repeatable and tests are stable.
3. JSON numbers become floats in many tools, which can't represent cents exactly; strings keep
   `"32.50"` exact until converted to `Decimal`.
4. 3 wrong totals and 1 subtotal ≠ lines (caught by the quality checks), 1 exact duplicate file
   (caught by the hash at ingestion), 1 re-photographed duplicate (caught by the duplicate check),
   plus a 15% price jump (caught by price alerts).
5. Synthetic receipts are flat, evenly lit and use one font, so OCR accuracy on them is higher than
   on real photos; the numbers show the method works, not real-world accuracy.

### 3. Ingestion
1. By the SHA-256 hash of the file bytes, stored with a `UNIQUE` constraint. File names change
   (IMG_0001.jpg vs. receipt.jpg) but identical bytes always give the same hash.
2. Not empty; ≤ 10 MB (cheap check first); extension is .jpg/.jpeg/.png; the real format read from
   the bytes is JPEG/PNG; width × height ≤ 50 MP (decompression bombs); `Image.verify()` for a
   corrupt structure.
3. A file name like `../../windows/x.jpg` used as a path could write outside the intended folder.
   We never use the original name as a path: files are saved as `<sha256>.<ext>`, and the original
   name is stored only as a label (base name only).
4. The file may still be copying; reading it half-written would reject or store a broken file.
5. If two processes insert the same hash at the same moment, both SELECTs find nothing; the
   `UNIQUE` constraint plus `ON CONFLICT DO NOTHING` lets the second insert do nothing instead of
   crashing, and the code then returns "duplicate".

### 4. OCR
1. Page segmentation mode: how Tesseract splits the page into blocks/lines. We measured several
   modes (and preprocessing) on the samples; `--psm 6` ("one uniform block of text") scored best.
2. So we can re-parse later with a better parser without re-running OCR, and for audit/debugging.
3. `check_allowed_for_external_ai()` hashes the image and only allows hashes of the fake sample
   images, unless `ALLOW_EXTERNAL_AI_ON_PRIVATE=true`; otherwise the pipeline falls back to Tesseract.
4. Put the API call in one small function (`_call_gemini`) and replace it in tests with
   `monkeypatch.setattr` so it returns fixed JSON; the tests also check nothing was "sent".
5. A row is stored in `raw.ocr_run` with only the error type (e.g. `FileNotFoundError`), the file
   status becomes `failed`, and the run continues with the next file.

### 5. Parsing
1. A `None` makes the quality checks send the receipt to review; a wrong guess would quietly
   produce wrong totals and prices that nobody notices.
2. Descriptions contain units and numbers (`ONIONS YELLOW 50 LB`, `GRND BEEF 80/20 10LB`); the real
   unit column is the last unit token before price and amount.
3. O, o, @ → 0 and l, I, | → 1, plus dropping a trailing comma; only in tokens we expect to be
   numbers, because applying them to descriptions would corrupt words.
4. Feed fixed strings that copy real OCR output (including real mistakes) and assert on the result;
   no images or OCR needed, so tests are fast and deterministic.
5. A garbled `SUBTOTAL alhl Ss}` line didn't match the subtotal pattern, so SUBTOTAL and TAX were
   read as items; fixed by ending the item list at any line *starting* with SUBTOTAL/TAX/TOTAL.

### 6. Cleaning
1. Floats are binary and can't represent most decimals exactly (0.1 + 0.2 ≠ 0.3); money needs exact
   arithmetic, so `Decimal` in Python and `NUMERIC(12,2)` in SQL.
2. Running it again gives the same result with no duplicates. Each step only picks rows in the
   status it handles, receipts are unique per file, and the mart is rebuilt in one transaction.
3. To show the reviewer exactly what OCR read, and to audit how a value was standardized.
4. pandas turns `None` into `NaN` in numeric columns, and `NaN` isn't valid SQL NULL; `dtype=object`
   keeps `None`, and `none_if_missing()` converts any `NaN` that slips through.
5. So we never end up with a receipt without its lines (or the file marked parsed without a receipt).

### 7. Quality checks
1. Required fields (completeness), valid/future date (validity), no negatives (validity), lines =
   subtotal and total = subtotal + tax (consistency), not a duplicate (uniqueness).
2. Prices are rounded per line, so sums can differ by a cent or two without being wrong.
3. The first receipt is legitimate; flagging both would make the reviewer reject the real one.
4. Results should describe the receipt's *current* values (after corrections); appending would
   mix old and new results.
5. 41 of 49 receipts needed review; required fields (40) and lines ≠ subtotal (20) were the most
   common, mostly because OCR couldn't read some quantities (often a printed "1").

### 8. Capture and security
1. A salt makes identical passwords hash differently (no precomputed tables); many iterations make
   each guess slow. `compare_digest` takes the same time whether or not the start matches, so
   timing doesn't leak information.
2. Browsers only allow camera access on HTTPS pages or `localhost`.
3. ngrok publishes the app on the public internet; Tailscale gives an HTTPS address reachable only
   by your own logged-in devices.
4. Every page calls `app_common.setup_page()` first, which calls `require_password()`; if the
   session isn't authenticated it shows the login form and calls `st.stop()`.
5. With Streamlit's `AppTest`: run a page, check what's shown before login, type a wrong and a right
   password, check what appears; plus tests of the functions behind the pages.

### 9. Review
1. OCR makes mistakes; a person confirms before numbers are trusted for analytics.
2. Receipt, field name (e.g. `line 2 quantity`), old value, new value, time; it's an audit trail
   and shows which fields OCR gets wrong most.
3. `"2.000" != "2"` as text, so saving an unchanged form would log a fake change.
4. The page rebuilds the mart, and the rebuild deletes and re-inserts facts, so the corrected
   values replace the old ones.
5. The corrected values may now pass (or fail) checks; the status must reflect the current data.

### 10. Excel
1. Streamlit's download button needs bytes; no temporary file is left on disk.
2. `groupby(["vendor_name", "month"])["total"].sum().unstack("month")`, then add total row/column.
3. Unapproved data may be wrong; exports should be as trustworthy as the dashboards.

### 11. Star schema
1. One line item on one approved receipt; the finest detail we have, so any total can be built up
   from it (by item, vendor, day, receipt).
2. Facts: quantity, line total, standard quantity, unit price (measures). Dimensions: vendor, item,
   date (descriptive context to group and filter by).
3. Small data, and a rebuild is simple and automatically correct after corrections or new rules.
   Switch to incremental (upsert on `line_id`) when rebuild time becomes a problem.
4. A test that two independent calculations of the same total agree: sum of fact line totals =
   sum of approved clean line totals.
5. `fact.line_id` → `clean.receipt_line` → `clean.receipt.ocr_run_id` → `raw.ocr_run.file_id` →
   `raw.receipt_file.stored_path` → the image.

### 12. Normalization
1. Different suppliers (and even the same one) name the same product differently, so prices can't
   be tracked or compared per product.
2. Each rule is an ILIKE-style pattern turned into a regex; all matching rules are found and the
   longest pattern wins because it's the most specific (`%TOMATOES%ROMA%` beats `%TOMATO%`).
3. Pack size 10 LB from the description → 2 × 10 = 20 lb; line total 65.00 / 20 = $3.25 per lb.
4. The family can add rules from the Items page without changing code; rules are data.
5. It's linked to the `UNMAPPED` item, keeps its spend, and appears in the unmapped list.

### 13. Prices and suppliers
1. `lag(x)` returns `x` from the previous row in the window; `PARTITION BY item_name, vendor_name`
   restarts the window per item and supplier, so each price is compared with the same supplier's
   previous price for the same item.
2. `SELECT DISTINCT ON (key) ... ORDER BY key, date DESC` keeps the first (newest) row per key.
3. SQL views can't read `.env`; the mart build copies the value into `mart.setting`, which the
   alert view reads (and the read-only chatbot can query alerts too).
4. Per item and supplier: average monthly quantity bought from that supplier × (that supplier's
   latest price − cheapest latest price), summed per item. It ignores delivery fees, minimums,
   quality, pack sizes on offer and availability.
5. Buying 30 lb at $3 and 1 lb at $5 averages $3.06/lb in reality, not $4: weighting by quantity
   reflects what you actually paid.

### 14. Evaluation
1. Pair each true line with the most similar unused extracted line (description similarity ≥ 0.6),
   then compare quantity, price and total of each pair; report how many true lines got a pair.
2. Field accuracy shows *which* field is weak; "fully correct" shows how often a line needs no
   fixing at all, which is what matters for review effort.
3. Tesseract: vendor/date/receipt number 100%, total 96.0%, lines fully correct 69.2%; quantity was
   weakest (78.8%); 527 ms per receipt. Gemini not measured yet.
4. Otherwise you'd measure something other than what the pipeline actually produces.

### 15. Automation
1. Two runs at once could process the same files twice or fight over them. Check-then-create in two
   steps has a race; `O_CREAT | O_EXCL` lets the OS create the file only if it doesn't exist, in one step.
2. A lock left behind by a run that crashed; we treat locks older than 2 hours as stale and remove them.
3. Logs are less protected than the database; IDs and error types are enough to debug without
   leaking receipt contents.
4. It's moved to `data/failed/`, the error type is logged, and the scan continues with the next file.

### 16. Dashboard
1. Queries in `src/dashboard.py` can be unit-tested against the test database; pages stay thin.
2. Color should mean identity; if colors followed rank, a filter could repaint a vendor and mislead.
3. Bars compare categories (spend per vendor); lines show change over time (price history).

### 17. Chatbot
1. `sqlglot` validation (single SELECT, mart only, forbidden statements/functions), `LIMIT 200`,
   the `receipts_readonly` role, a read-only transaction, and a 5-second statement timeout.
2. A regex can be fooled (comments, `WITH x AS (DELETE ...)`, `SELECT ... INTO`, multiple
   statements); parsing builds the full syntax tree so every part can be checked.
3. `WITH d AS (DELETE FROM mart.dim_vendor RETURNING *) SELECT * FROM d`, `SELECT * INTO new_table
   FROM ...`, `SELECT pg_sleep(100)`, `SELECT pg_read_file('...')`.
4. Run a hand-written expected query and the generated one, and compare *results* (values, ignoring
   column names, order and extra columns), not SQL text.
5. When writing SQL: only the mart's table/column structure and the question. The optional answer
   sends up to 20 result rows, so it only runs when all stored images are sample receipts (or the
   owner allows it).

### 18. Testing
1. `conftest.py` sets `DB_NAME` to `receipts_test` before anything connects, and the `db_conn`
   fixture empties the data tables before each test.
2. A reusable setup function that tests ask for by name; e.g. `db_conn` gives an emptied test
   database connection, `tmp_path` gives a temporary folder.
3. Examples: the savepoint/commit bug in `setup_db.py`; the garbled SUBTOTAL line; the duplicate
   file copy picking up the `.json` instead of the image; half-up vs. half-even rounding.
4. Isolate the call in one function and replace it in tests (`monkeypatch`), asserting both on the
   output and on what would have been sent.
