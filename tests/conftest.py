"""Shared pytest setup.

Tests always use the TEST database (DB_TEST_NAME, default receipts_test),
never the real one. We set DB_NAME before src.config is imported.
"""

import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
# Streamlit adds app/ to the path when it runs app/Home.py; tests that run
# a page file directly need the same, so pages can `import app_common`.
sys.path.insert(0, str(PROJECT_ROOT / "app"))

load_dotenv(PROJECT_ROOT / ".env", override=False)
os.environ["DB_NAME"] = os.getenv("DB_TEST_NAME", "receipts_test")

from src import db  # noqa: E402
from scripts.setup_db import apply_migrations  # noqa: E402

# Schemas whose tables we empty before each database test
DATA_SCHEMAS = ("raw", "clean", "dq", "mart")


def _connect_or_skip():
    try:
        return db.get_connection()
    except Exception as error:  # database not set up on this machine
        pytest.skip(f"Test database not available: {type(error).__name__}")


@pytest.fixture(scope="session")
def migrated_db():
    """Apply all migrations to the test database once per test run."""
    conn = _connect_or_skip()
    apply_migrations(conn)
    conn.close()
    return True


@pytest.fixture
def db_conn(migrated_db):
    """A connection to an emptied test database."""
    conn = db.get_connection()
    _truncate_all(conn)
    yield conn
    conn.close()


def _truncate_all(conn):
    """Empty every table in the data schemas (keeps seed tables listed below)."""
    keep = {("mart", "item_mapping"), ("clean", "vendor_mapping")}
    rows = conn.execute(
        """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema = ANY(%s) AND table_type = 'BASE TABLE'
        """,
        (list(DATA_SCHEMAS),),
    ).fetchall()
    tables = [f'"{s}"."{t}"' for s, t in rows if (s, t) not in keep]
    if tables:
        # Table names come from the catalog, not from user input
        conn.execute("TRUNCATE " + ", ".join(tables) + " RESTART IDENTITY CASCADE")
