import json
import logging
import os
import time
from datetime import datetime

import httpx

from app.cleaning import clean_all

ELANCO_API_URL = os.environ.get("ELANCO_API_URL", "https://dev-task.elancoapps.com/data/tick-sightings")
SEED_PATH = "data/seed.json"
TIMEOUT_SECONDS = 10
RETRY_DELAYS = [1, 2]

logger = logging.getLogger(__name__)


class SyncError(Exception):
    pass


def now():
    return datetime.now().isoformat(timespec="seconds")


def fetch_sightings(client):
    last_error = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        if attempt:
            time.sleep(RETRY_DELAYS[attempt - 1])
        try:
            response = client.get(ELANCO_API_URL, timeout=TIMEOUT_SECONDS)
        except httpx.TransportError as e:
            last_error = f"{type(e).__name__}: {e}"
            continue
        if response.status_code == 429 or response.status_code >= 500:
            last_error = f"HTTP {response.status_code}"
            continue
        if response.status_code != 200:
            raise SyncError(f"HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError:
            raise SyncError("response is not valid JSON")
        if not isinstance(data, list):
            raise SyncError("response is not a list of sightings")
        return data
    raise SyncError(f"gave up after {len(RETRY_DELAYS) + 1} attempts: {last_error}")


def save(conn, started, raw_records, data_source, status, error):
    result = clean_all(raw_records)
    if not result["kept"]:
        raise SyncError("no valid sightings in response")
    with conn:
        run = conn.execute(
            "INSERT INTO sync_runs (started_at, finished_at, status, data_source, fetched, kept, duplicates,"
            " rejected, locations_corrected, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (started, now(), status, data_source, len(raw_records), len(result["kept"]), result["duplicates"],
             len(result["rejected"]), result["locations_corrected"], error),
        )
        conn.execute("DELETE FROM sightings")
        conn.executemany(
            "INSERT INTO sightings (id, date, location, species, latin_name)"
            " VALUES (:id, :date, :location, :species, :latin_name)",
            result["kept"],
        )
        conn.executemany(
            "INSERT INTO rejected_records (sync_run_id, raw, reason) VALUES (?, ?, ?)",
            [(run.lastrowid, json.dumps(raw), reason) for raw, reason in result["rejected"]],
        )
    return status


def run_sync(conn, client):
    started = now()
    try:
        return save(conn, started, fetch_sightings(client), "live", "success", None)
    except Exception as e:
        error = str(e) or type(e).__name__
    logger.warning("Sync failed: %s", error)

    if conn.execute("SELECT COUNT(*) FROM sightings").fetchone()[0]:
        with conn:
            conn.execute(
                "INSERT INTO sync_runs (started_at, finished_at, status, error) VALUES (?, ?, 'failed', ?)",
                (started, now(), error),
            )
        return "failed"

    with open(SEED_PATH, encoding="utf-8") as f:
        return save(conn, started, json.load(f), "snapshot", "failed", error)
