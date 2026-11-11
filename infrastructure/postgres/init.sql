-- Runs once when the Postgres volume is first created.
-- Tables themselves are created by the backend (python -m app.cli init-db).
CREATE EXTENSION IF NOT EXISTS pg_trgm;
