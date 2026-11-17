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
   - Program/script: `C:\Users\zahan\Documents\Restaurant Receipt Tracker\.venv\Scripts\pythonw.exe`
   - Add arguments: `-m src.run_pipeline`
   - Start in: `C:\Users\zahan\Documents\Restaurant Receipt Tracker`
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

Safety: Gemini only gets the mart table structure and the question. The SQL it returns must parse
(with `sqlglot`) as a single SELECT on `mart.` objects, gets `LIMIT 200`, and runs as the
`receipts_readonly` role in a read-only transaction with a 5-second timeout.

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
