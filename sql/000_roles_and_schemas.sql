-- 000_roles_and_schemas.sql
-- Run ONCE as the postgres superuser, connected to the `receipts` database
-- (and again on `receipts_test` for the tests).
-- The easiest way is: python scripts/bootstrap_db.py
-- It creates the databases, runs this file, and sets the role passwords from .env.
--
-- In pgAdmin instead: create the database `receipts`, open a Query Tool on it,
-- run this file, then set passwords with:
--   ALTER ROLE receipts_app PASSWORD '...';
--   ALTER ROLE receipts_readonly PASSWORD '...';
--
-- Safe to run more than once.

-- 1. Roles (no passwords here; passwords never go in Git)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'receipts_app') THEN
        CREATE ROLE receipts_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'receipts_readonly') THEN
        CREATE ROLE receipts_readonly LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;
END
$$;

-- 2. Schemas, one per data layer, owned by the app role
CREATE SCHEMA IF NOT EXISTS raw   AUTHORIZATION receipts_app;
CREATE SCHEMA IF NOT EXISTS clean AUTHORIZATION receipts_app;
CREATE SCHEMA IF NOT EXISTS dq    AUTHORIZATION receipts_app;
CREATE SCHEMA IF NOT EXISTS mart  AUTHORIZATION receipts_app;

-- The setup script keeps its public.schema_version table in `public`
GRANT USAGE, CREATE ON SCHEMA public TO receipts_app;

-- 3. Read-only role: can only SELECT from the mart schema
GRANT USAGE ON SCHEMA mart TO receipts_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA mart TO receipts_readonly;
-- Tables and views that receipts_app creates in mart later are readable too
ALTER DEFAULT PRIVILEGES FOR ROLE receipts_app IN SCHEMA mart
    GRANT SELECT ON TABLES TO receipts_readonly;
