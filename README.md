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

## Results

To be filled in with measured numbers only.

### Manual-entry time saved

To be measured.
