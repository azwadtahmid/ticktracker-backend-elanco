"""SQLite connection, table creation and indexes."""
import sqlite3

DB_PATH = "tick_tracker.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sightings (
    id         TEXT PRIMARY KEY,
    date       TEXT NOT NULL,  -- ISO 8601, so text order = time order
    location   TEXT NOT NULL,
    species    TEXT NOT NULL,
    latin_name TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sightings_date ON sightings(date);
CREATE INDEX IF NOT EXISTS idx_sightings_location ON sightings(location);

CREATE TABLE IF NOT EXISTS sync_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    status              TEXT NOT NULL,  -- 'success' or 'failed'
    data_source         TEXT,           -- 'live' or 'snapshot'
    fetched             INTEGER,
    kept                INTEGER,
    duplicates          INTEGER,
    rejected            INTEGER,
    locations_corrected INTEGER,
    error               TEXT
);

CREATE TABLE IF NOT EXISTS rejected_records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_run_id INTEGER NOT NULL REFERENCES sync_runs(id),
    raw         TEXT NOT NULL,  -- the original record as JSON
    reason      TEXT NOT NULL
);
"""


def connect(path=DB_PATH):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row  # rows behave like dicts: row["location"]
    return conn


def init_db(conn):
    conn.executescript(SCHEMA)
