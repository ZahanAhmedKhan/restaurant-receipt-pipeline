# Restaurant Receipt Pipeline

A local data pipeline that turns photos of supplier receipts into clean, reviewed data in PostgreSQL,
with Excel export, a Streamlit dashboard and a read-only text-to-SQL chatbot.

> Work in progress. See `PROGRESS.md` for status.

## Setup (Windows, PowerShell)

### 1. Python environment

```powershell
cd "C:\Users\zahan\Documents\Restaurant Receipt Tracker"
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
Then edit `.env` with your real values.

### 4. Database (one time)

Set `DB_APP_PASSWORD` and `DB_READONLY_PASSWORD` in `.env` (any long random strings), then:

```powershell
python scripts\bootstrap_db.py      # asks for the postgres superuser password
python scripts\setup_db.py          # creates the tables; safe to run again
```

`bootstrap_db.py` creates the `receipts` and `receipts_test` databases, runs
`sql/000_roles_and_schemas.sql` in both, and sets the two role passwords from `.env`.
(You can also run `000_roles_and_schemas.sql` by hand in pgAdmin; see the comments at the top of the file.)

### 5. Check everything works

```powershell
python -c "import pandas, psycopg, pytesseract, PIL; print('imports ok')"
tesseract --version
```

## Running the pipeline

```powershell
.\.venv\Scripts\Activate.ps1
python -m src.run_pipeline --sample   # load the 50 fake receipts (demo)
python -m src.run_pipeline            # process new photos dropped into data\inbox\
python -m pytest -q                   # run the tests (uses the receipts_test database)
```

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

## The app (Streamlit)

```powershell
python scripts\set_app_password.py    # one time: choose the app password (saved only as a hash)
streamlit run app\Home.py             # opens http://localhost:8501
```

Pages: **Add Receipt** (camera or upload), **Review**, **Export** (Excel download).

Excel export from the terminal: `python -m src.export_excel` (writes `exports\receipts_<date>.xlsx`).

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

## Results

To be filled in with measured numbers only.

### Manual-entry time saved

To be measured.
