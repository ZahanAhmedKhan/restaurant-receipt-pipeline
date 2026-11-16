"""Apply the numbered SQL files in sql/ (001_..., 002_..., ...) in order.

Each file runs once. Applied files are recorded in public.schema_version,
so running this script again does nothing.

000_roles_and_schemas.sql is NOT run here: it needs the postgres superuser
(see scripts/bootstrap_db.py).

Usage:
    python scripts/setup_db.py
    python scripts/setup_db.py --dbname receipts_test
"""

import argparse
import sys
from pathlib import Path

# Let this script import from src/ when run as "python scripts/setup_db.py"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.db import get_connection, run_sql_file  # noqa: E402

CREATE_VERSION_TABLE = """
CREATE TABLE IF NOT EXISTS public.schema_version (
    version     TEXT PRIMARY KEY,               -- file name, e.g. 001_raw.sql
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def list_migration_files(sql_dir=config.SQL_DIR):
    """Return numbered .sql files from 001 upwards, sorted by name."""
    files = []
    for path in sorted(Path(sql_dir).glob("*.sql")):
        prefix = path.name[:3]
        # Only files like 001_xxx.sql; skip 000 (superuser only)
        if prefix.isdigit() and prefix != "000":
            files.append(path)
    return files


def applied_versions(conn):
    """Return the set of file names already recorded in schema_version."""
    rows = conn.execute("SELECT version FROM public.schema_version").fetchall()
    return {row[0] for row in rows}


def apply_migrations(conn, sql_dir=config.SQL_DIR):
    """Run every file not yet applied. Returns the list of names applied now."""
    conn.execute(CREATE_VERSION_TABLE)
    conn.commit()

    done = applied_versions(conn)
    # End the read transaction, so each conn.transaction() below is a real
    # transaction that commits on its own (not a savepoint inside the read).
    conn.commit()
    applied_now = []
    for path in list_migration_files(sql_dir):
        if path.name in done:
            continue
        # One transaction per file: the file and its version row
        # are saved together, or not at all.
        with conn.transaction():
            run_sql_file(conn, path)
            conn.execute(
                "INSERT INTO public.schema_version (version) VALUES (%s)",
                (path.name,),
            )
        applied_now.append(path.name)
    return applied_now


def main():
    parser = argparse.ArgumentParser(description="Apply numbered SQL files.")
    parser.add_argument("--dbname", help="database name (default: DB_NAME from .env)")
    args = parser.parse_args()

    with get_connection(dbname=args.dbname) as conn:
        applied = apply_migrations(conn)

    if applied:
        for name in applied:
            print(f"Applied {name}")
    else:
        print("Database is up to date. Nothing to apply.")


if __name__ == "__main__":
    main()
