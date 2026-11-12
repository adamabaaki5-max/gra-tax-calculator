-- GRA Tax Calculator database schema (PostgreSQL; also runs unchanged on SQLite for local use).
-- The app creates these tables by itself on first start, so running this file by hand is optional.
-- Tables:
--   tax_years       one row per tax year
--   tax_bands       the bands of each year's annual / monthly table  (linked to tax_years)
--   settings_auth   the single row holding the Rate Settings password (hashed) and login lockout
--   bulk_results    TEMPORARY bulk-calculation results; every row has an expiry time and is deleted when it passes
--                   (linked to tax_years)

CREATE TABLE IF NOT EXISTS tax_years (
    year        INTEGER PRIMARY KEY CHECK (year BETWEEN 2000 AND 2100),
    updated_at  BIGINT  NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tax_bands (
    year      INTEGER NOT NULL REFERENCES tax_years (year) ON DELETE CASCADE,
    period    TEXT    NOT NULL CHECK (period IN ('annual', 'monthly')),
    position  INTEGER NOT NULL CHECK (position >= 0),            -- 0 = "First", last = "Exceeding"
    width     DOUBLE PRECISION CHECK (width IS NULL OR width > 0), -- chargeable income in the band; NULL for "Exceeding"
    rate      DOUBLE PRECISION NOT NULL CHECK (rate >= 0 AND rate <= 100),
    PRIMARY KEY (year, period, position)
);

CREATE TABLE IF NOT EXISTS settings_auth (
    id               INTEGER PRIMARY KEY CHECK (id = 1),          -- always a single row
    password_hash    TEXT,                                        -- NULL = the default password is still in use
    failed_attempts  INTEGER NOT NULL DEFAULT 0,
    locked_until     BIGINT  NOT NULL DEFAULT 0,
    updated_at       BIGINT  NOT NULL DEFAULT 0
);
INSERT INTO settings_auth (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS bulk_results (
    token       TEXT    PRIMARY KEY,
    tax_year    INTEGER NOT NULL REFERENCES tax_years (year) ON DELETE CASCADE,
    period      TEXT    NOT NULL CHECK (period IN ('annual', 'monthly')),
    mode        TEXT    NOT NULL,
    data        TEXT    NOT NULL,                                 -- compressed results (no uploaded file is ever stored)
    created_at  BIGINT  NOT NULL,
    expires_at  BIGINT  NOT NULL                                  -- deleted automatically after this time
);
CREATE INDEX IF NOT EXISTS idx_bulk_results_expires ON bulk_results (expires_at);
