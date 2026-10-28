-- One-time local database setup. Safe to re-run.
--
--   psql -U postgres -f scripts/setup_db.sql
--
-- Creates a login role "ledger" (password "ledger") that may create databases,
-- plus two databases it owns: "ledger" (the app) and "ledger_test" (pytest).
-- Change the password here AND in .env if this is anything but a local machine.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ledger') THEN
        CREATE ROLE ledger LOGIN PASSWORD 'ledger' CREATEDB;
    END IF;
END
$$;

SELECT 'CREATE DATABASE ledger OWNER ledger'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'ledger')\gexec

SELECT 'CREATE DATABASE ledger_test OWNER ledger'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'ledger_test')\gexec
