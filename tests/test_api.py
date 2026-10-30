import json

import pytest
from fastapi.testclient import TestClient

from app.db import connect, init_db
from app.main import app, get_conn

ROWS = [
    ("a", "2023-06-02T10:00:00", "London", "Marsh tick", "Ixodes apronophorus"),
    ("b", "2023-06-20T10:00:00", "London", "Passerine tick", "Dermacentor frontalis"),
    ("c", "2023-08-31T23:00:00", "Leeds", "Marsh tick", "Ixodes apronophorus"),
    ("d", "2023-09-01T00:00:00", "Unknown", "Unknown", "Unknown"),
]


@pytest.fixture
def conn():
    c = connect(":memory:")
    init_db(c)
    c.executemany("INSERT INTO sightings VALUES (?, ?, ?, ?, ?)", ROWS)
    c.execute(
        "INSERT INTO sync_runs (started_at, finished_at, status, data_source, fetched, kept, duplicates,"
        " rejected, locations_corrected) VALUES ('2026-10-30T10:00:00', '2026-10-30T10:00:01',"
        " 'success', 'live', 6, 4, 1, 1, 1)"
    )
    c.execute(
        "INSERT INTO rejected_records (sync_run_id, raw, reason) VALUES (1, ?, 'missing id')",
        (json.dumps({"date": "2023-01-01"}),),
    )
    c.commit()
    return c


@pytest.fixture
def client(conn):
    app.dependency_overrides[get_conn] = lambda: conn
    yield TestClient(app)
    app.dependency_overrides.clear()


def ids(response):
    return [r["id"] for r in response.json()["results"]]


def test_search_returns_wrapped_results_newest_first(client):
    body = client.get("/sightings").json()
    assert body["data_source"] == "live" and body["count"] == 4
    assert [r["id"] for r in body["results"]] == ["d", "c", "b", "a"]


def test_date_range_end_is_inclusive(client):
    assert ids(client.get("/sightings?start=2023-06-01&end=2023-08-31")) == ["c", "b", "a"]


def test_dates_without_leading_zeros_are_accepted(client):
    assert ids(client.get("/sightings?start=2023-6-1&end=2023-8-31")) == ["c", "b", "a"]


@pytest.mark.parametrize("value", ["banana", "2023/06/01", "01-06-2023", "2023-13-01"])
def test_bad_date_explains_the_format(client, value):
    response = client.get("/sightings", params={"start": value})
    assert response.status_code == 422
    assert "2024-01-01" in response.json()["detail"]


@pytest.mark.parametrize("location", ["London", "london", " LONDON ", "Londn"])
def test_location_filter_uses_cleaning_rules(client, location):
    assert ids(client.get("/sightings", params={"location": location})) == ["b", "a"]


def test_species_filter_ignores_case(client):
    assert ids(client.get("/sightings?species=marsh TICK")) == ["c", "a"]


def test_paging_keeps_total_count(client):
    body = client.get("/sightings?limit=1&offset=1").json()
    assert body["count"] == 4 and [r["id"] for r in body["results"]] == ["c"]


@pytest.mark.parametrize("query", ["limit=5000", "limit=0", "offset=-1"])
def test_bad_input_is_rejected(client, query):
    assert client.get(f"/sightings?{query}").status_code == 422


def test_get_sighting_by_id(client):
    assert ids(client.get("/sightings/a")) == ["a"]
    assert client.get("/sightings/nope").status_code == 404


def test_regions_counts_highest_first(client):
    results = client.get("/reports/regions").json()["results"]
    assert results == [{"location": "London", "count": 2}, {"location": "Leeds", "count": 1},
                       {"location": "Unknown", "count": 1}]


def test_monthly_trend_fills_empty_months(client):
    results = client.get("/reports/trends?interval=month").json()["results"]
    assert results == [{"period": "2023-06-01", "count": 2}, {"period": "2023-07-01", "count": 0},
                       {"period": "2023-08-01", "count": 1}, {"period": "2023-09-01", "count": 1}]


def test_weekly_trend_uses_mondays(client):
    results = client.get("/reports/trends?interval=week&location=London").json()["results"]
    assert results == [{"period": "2023-05-29", "count": 1}, {"period": "2023-06-05", "count": 0},
                       {"period": "2023-06-12", "count": 0}, {"period": "2023-06-19", "count": 1}]


def test_unknown_interval_is_rejected(client):
    assert client.get("/reports/trends?interval=year").status_code == 422


def test_health_reports_live_data(client):
    body = client.get("/health").json()
    assert body["data_source"] == "live" and body["sightings"] == 4
    assert body["message"].startswith("Serving live data")


def test_health_explains_failed_sync(client, conn):
    conn.execute("INSERT INTO sync_runs (started_at, finished_at, status, error)"
                 " VALUES ('2026-10-30T11:00:00', '2026-10-30T11:00:05', 'failed', 'HTTP 500')")
    body = client.get("/health").json()
    assert body["data_source"] == "live"
    assert "latest sync failed: HTTP 500" in body["message"]
    assert body["last_successful_sync_at"] == "2026-10-30T10:00:01"


def test_data_quality_reports_counts_and_rejections(client):
    body = client.get("/data-quality").json()
    assert (body["fetched"], body["kept"], body["duplicates"], body["rejected"]) == (6, 4, 1, 1)
    assert body["rejected_by_reason"] == {"missing id": {"count": 1, "records": [{"date": "2023-01-01"}]}}
    assert body["unknown_locations"] == 1 and body["unknown_species"] == 1
