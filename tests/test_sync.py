import httpx
import pytest

from app import sync
from app.db import connect, init_db

GOOD = {"id": "a", "date": "2023-06-01T10:00:00", "location": "Leeds",
        "species": "Marsh tick", "latinName": "Ixodes apronophorus"}
BAD = {"id": "b", "date": "not a date", "location": "Leeds",
       "species": "Marsh tick", "latinName": "Ixodes apronophorus"}


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(sync, "RETRY_DELAYS", [0, 0])


@pytest.fixture
def conn():
    c = connect(":memory:")
    init_db(c)
    return c


def fake_elanco(*responses):
    calls = []

    def handler(request):
        calls.append(request)
        response = responses[min(len(calls), len(responses)) - 1]
        if response == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        return response

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def last_run(conn):
    return conn.execute("SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1").fetchone()


def test_good_response_is_saved_as_live(conn):
    client, _ = fake_elanco(httpx.Response(200, json=[GOOD, BAD]))
    assert sync.run_sync(conn, client) == "success"
    assert count(conn, "sightings") == 1
    assert count(conn, "rejected_records") == 1
    run = last_run(conn)
    assert (run["status"], run["data_source"], run["fetched"], run["kept"], run["rejected"]) == ("success", "live", 2, 1, 1)


def test_500_then_success_is_retried(conn):
    client, calls = fake_elanco(httpx.Response(500), httpx.Response(200, json=[GOOD]))
    assert sync.run_sync(conn, client) == "success"
    assert len(calls) == 2


def test_429_is_retried(conn):
    client, calls = fake_elanco(httpx.Response(429), httpx.Response(200, json=[GOOD]))
    assert sync.run_sync(conn, client) == "success"
    assert len(calls) == 2


def test_404_is_not_retried(conn):
    client, calls = fake_elanco(httpx.Response(404))
    sync.run_sync(conn, client)
    assert len(calls) == 1


def test_failure_keeps_existing_data(conn):
    sync.run_sync(conn, fake_elanco(httpx.Response(200, json=[GOOD]))[0])
    client, calls = fake_elanco(httpx.Response(500))
    assert sync.run_sync(conn, client) == "failed"
    assert len(calls) == 3
    assert count(conn, "sightings") == 1
    run = last_run(conn)
    assert run["status"] == "failed" and run["data_source"] is None and "HTTP 500" in run["error"]


@pytest.mark.parametrize("response", [
    httpx.Response(200, text="<html>oops</html>"),
    httpx.Response(200, json={"error": "something"}),
    httpx.Response(200, json=[]),
    httpx.Response(200, json=[BAD]),
])
def test_junk_response_keeps_existing_data(conn, response):
    sync.run_sync(conn, fake_elanco(httpx.Response(200, json=[GOOD]))[0])
    assert sync.run_sync(conn, fake_elanco(response)[0]) == "failed"
    assert count(conn, "sightings") == 1


def test_first_run_failure_loads_snapshot(conn):
    client, calls = fake_elanco("timeout")
    assert sync.run_sync(conn, client) == "failed"
    assert len(calls) == 3
    assert count(conn, "sightings") == 1000
    run = last_run(conn)
    assert run["data_source"] == "snapshot" and "ReadTimeout" in run["error"]


def test_crash_mid_save_rolls_back(conn, monkeypatch):
    sync.run_sync(conn, fake_elanco(httpx.Response(200, json=[GOOD]))[0])
    broken = {"id": "z", "date": None, "location": "Leeds", "species": "Marsh tick", "latin_name": "x"}
    monkeypatch.setattr(sync, "clean_all", lambda raw: {
        "kept": [dict(GOOD, id="new", latin_name="x"), broken],
        "rejected": [], "duplicates": 0, "locations_corrected": 0,
    })
    assert sync.run_sync(conn, fake_elanco(httpx.Response(200, json=[GOOD]))[0]) == "failed"
    assert [r["id"] for r in conn.execute("SELECT id FROM sightings")] == ["a"]
