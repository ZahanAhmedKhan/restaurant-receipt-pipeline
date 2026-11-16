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

### 4. Check everything works

```powershell
python -c "import pandas, psycopg, pytesseract, PIL; print('imports ok')"
tesseract --version
```

## Results

To be filled in with measured numbers only.

### Manual-entry time saved

To be measured.
