"""Tests for scripts/setup_db.py and the database roles."""

import psycopg
import pytest

from scripts.setup_db import apply_migrations, list_migration_files
from src import db


def test_list_migration_files_skips_000_and_sorts(tmp_path):
    for name in ["002_b.sql", "000_roles.sql", "001_a.sql", "notes.sql"]:
        (tmp_path / name).write_text("SELECT 1;")
    names = [p.name for p in list_migration_files(tmp_path)]
    assert names == ["001_a.sql", "002_b.sql"]


def test_second_run_applies_nothing(migrated_db):
    with db.get_connection() as conn:
        # migrated_db already applied everything, so this run is a no-op
        assert apply_migrations(conn) == []
        assert apply_migrations(conn) == []


def test_each_file_recorded_once(migrated_db):
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT version, count(*) FROM public.schema_version GROUP BY version"
        ).fetchall()
    assert all(count == 1 for _, count in rows)


def test_readonly_role_cannot_write(migrated_db):
    with db.get_connection(readonly=True) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("CREATE TABLE mart.should_fail (x int)")


def test_readonly_role_cannot_read_raw_schema(migrated_db):
    with db.get_connection(readonly=True) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT 1 FROM raw.receipt_file")
