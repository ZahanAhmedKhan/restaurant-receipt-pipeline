"""Database helpers: open connections and run .sql files.

We use psycopg 3 with plain SQL (no ORM).
"""

from pathlib import Path

import psycopg

from src import config


def get_connection(readonly=False, dbname=None):
    """Open a new connection to PostgreSQL.

    readonly=False -> connect as receipts_app (pipeline and Streamlit)
    readonly=True  -> connect as receipts_readonly (chatbot only)
    dbname         -> override the database name (used by tests)

    The connection is in autocommit mode: each statement is saved right away.
    To save several statements together (all or nothing), wrap them in
        with conn.transaction():
            ...
    """
    if readonly:
        user = config.DB_READONLY_USER
        password = config.DB_READONLY_PASSWORD
    else:
        user = config.DB_APP_USER
        password = config.DB_APP_PASSWORD

    return psycopg.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        dbname=dbname or config.DB_NAME,
        user=user,
        password=password,
        autocommit=True,
    )


def run_sql_file(conn, path):
    """Run every statement in a .sql file on an open connection.

    Call it inside `with conn.transaction():` to make the whole file
    all-or-nothing.
    """
    sql_text = Path(path).read_text(encoding="utf-8")
    # psycopg can run a whole script with several statements in one execute()
    # as long as we pass no parameters.
    conn.execute(sql_text)
