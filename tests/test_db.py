import sqlite3

import pytest

from app.db import connect, init_db


def make_db():
    conn = connect(":memory:")
    init_db(conn)
    return conn


def test_tables_are_created():
    conn = make_db()
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"sightings", "sync_runs", "rejected_records"} <= tables


def test_init_db_is_safe_to_run_twice():
    conn = make_db()
    init_db(conn)  # runs on every startup, so must not fail on an existing DB


def test_primary_key_rejects_duplicate_id():
    conn = make_db()
    row = ("abc123", "2023-06-01T10:00:00", "Leeds", "Marsh tick", "Ixodes apronophorus")
    conn.execute("INSERT INTO sightings VALUES (?, ?, ?, ?, ?)", row)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO sightings VALUES (?, ?, ?, ?, ?)", row)


def test_missing_field_is_refused():
    conn = make_db()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO sightings VALUES (?, ?, ?, ?, ?)", ("x1", None, "Leeds", "Marsh tick", "Ixodes apronophorus"))
