import sqlite3
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "tick_tracker.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sightings (
    id         TEXT PRIMARY KEY,
    date       TEXT NOT NULL,
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
    status              TEXT NOT NULL,
    data_source         TEXT,
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
    raw         TEXT NOT NULL,
    reason      TEXT NOT NULL
);
"""


def connect(path=DB_PATH):
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn):
    conn.executescript(SCHEMA)
