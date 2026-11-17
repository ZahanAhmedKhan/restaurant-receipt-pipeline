"""Load settings from the .env file in the project root.

Every other module imports settings from here, so there is one place
that knows about environment variables.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Project root = the folder that contains src/
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env from the project root. Values already set in the real
# environment win (override=False), which lets tests point at a test DB.
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _get(name, default=None):
    """Read one environment variable, with an optional default."""
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


# --- PostgreSQL ---
DB_HOST = _get("DB_HOST", "localhost")
DB_PORT = int(_get("DB_PORT", "5432"))
DB_NAME = _get("DB_NAME", "receipts")
DB_TEST_NAME = _get("DB_TEST_NAME", "receipts_test")  # used by pytest
DB_APP_USER = _get("DB_APP_USER", "receipts_app")
DB_APP_PASSWORD = _get("DB_APP_PASSWORD")
DB_READONLY_USER = _get("DB_READONLY_USER", "receipts_readonly")
DB_READONLY_PASSWORD = _get("DB_READONLY_PASSWORD")

# --- OCR ---
TESSERACT_CMD = _get("TESSERACT_CMD")
OCR_METHOD = _get("OCR_METHOD", "tesseract")

# --- Gemini (optional) ---
GEMINI_API_KEY = _get("GEMINI_API_KEY")
GEMINI_MODEL = _get("GEMINI_MODEL", "gemini-3.8-flash")
ALLOW_EXTERNAL_AI_ON_PRIVATE = _get("ALLOW_EXTERNAL_AI_ON_PRIVATE", "false").lower() == "true"

# --- Streamlit app ---
APP_PASSWORD_HASH = _get("APP_PASSWORD_HASH")              # staff password
DEVELOPER_PASSWORD_HASH = _get("DEVELOPER_PASSWORD_HASH")  # developer password

# --- Price alerts ---
PRICE_ALERT_THRESHOLD_PCT = float(_get("PRICE_ALERT_THRESHOLD_PCT", "10"))

# --- Folders ---
DATA_DIR = PROJECT_ROOT / "data"
INBOX_DIR = DATA_DIR / "inbox"
RAW_DIR = DATA_DIR / "raw"
FAILED_DIR = DATA_DIR / "failed"
SAMPLE_DIR = DATA_DIR / "sample"
PRIVATE_DIR = DATA_DIR / "private"
SQL_DIR = PROJECT_ROOT / "sql"
EXPORTS_DIR = PROJECT_ROOT / "exports"
LOGS_DIR = PROJECT_ROOT / "logs"
