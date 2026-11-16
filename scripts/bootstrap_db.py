"""One-time database bootstrap, run as the postgres superuser.

What it does (safe to run again):
  1. Creates the databases `receipts` and `receipts_test` if missing.
  2. Runs sql/000_roles_and_schemas.sql in both (roles, schemas, grants).
  3. Sets the passwords of receipts_app and receipts_readonly from .env.

It asks for the postgres password at the prompt; it is never saved.

Usage:
    python scripts/bootstrap_db.py
"""

import getpass
import sys
from pathlib import Path

import psycopg
from psycopg import sql

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.db import run_sql_file  # noqa: E402

ROLES_FILE = config.SQL_DIR / "000_roles_and_schemas.sql"


def connect_as_postgres(password, dbname):
    """Connect as the superuser. autocommit is needed for CREATE DATABASE."""
    return psycopg.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        dbname=dbname,
        user="postgres",
        password=password,
        autocommit=True,
    )


def create_database_if_missing(conn, dbname):
    exists = conn.execute(
        "SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)
    ).fetchone()
    if exists:
        print(f"Database {dbname} already exists.")
        return
    # Identifiers (names) can't be %s parameters; sql.Identifier quotes them safely.
    conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
    print(f"Created database {dbname}.")


def set_role_password(conn, role, password):
    # ALTER ROLE does not accept %s parameters, so we use sql.Literal,
    # which escapes the value safely.
    conn.execute(
        sql.SQL("ALTER ROLE {} PASSWORD {}").format(
            sql.Identifier(role), sql.Literal(password)
        )
    )


def main():
    if not config.DB_APP_PASSWORD or not config.DB_READONLY_PASSWORD:
        print("Set DB_APP_PASSWORD and DB_READONLY_PASSWORD in .env first.")
        sys.exit(1)

    pg_password = getpass.getpass("postgres superuser password: ")
    test_dbname = config.DB_TEST_NAME

    try:
        conn = connect_as_postgres(pg_password, "postgres")
    except psycopg.OperationalError:
        print("Could not log in as postgres. Check the password and that the "
              "PostgreSQL service is running, then try again.")
        sys.exit(1)

    with conn:
        for dbname in (config.DB_NAME, test_dbname):
            create_database_if_missing(conn, dbname)

    for dbname in (config.DB_NAME, test_dbname):
        with connect_as_postgres(pg_password, dbname) as conn:
            run_sql_file(conn, ROLES_FILE)
            print(f"Ran 000_roles_and_schemas.sql on {dbname}.")

    with connect_as_postgres(pg_password, "postgres") as conn:
        set_role_password(conn, config.DB_APP_USER, config.DB_APP_PASSWORD)
        set_role_password(conn, config.DB_READONLY_USER, config.DB_READONLY_PASSWORD)
    print("Role passwords set from .env.")
    print("Next: python scripts/setup_db.py")


if __name__ == "__main__":
    main()
