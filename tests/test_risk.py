import pytest
from fastapi.testclient import TestClient

from app.db import connect, init_db
from app.main import app, get_conn, risk_level, shift_month

DATES = {
    "London": ["2022-05-10", "2023-06-10", "2024-05-01", "2024-06-15", "2024-07-20"],
    "Leeds": ["2022-06-01", "2022-07-01", "2023-05-05", "2023-07-07"],
    "Bristol": ["2024-07-01"],
    "Unknown": ["2024-07-02"],
}


@pytest.fixture
def client():
    conn = connect(":memory:")
    init_db(conn)
    rows = [
        (f"{city}-{i}", f"{d}T12:00:00", city, "Marsh tick", "Ixodes apronophorus")
        for city, dates in DATES.items()
        for i, d in enumerate(dates)
    ]
    conn.executemany("INSERT INTO sightings VALUES (?, ?, ?, ?, ?)", rows)
    app.dependency_overrides[get_conn] = lambda: conn
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_risk_compares_window_with_same_window_in_earlier_years(client):
    results = {r["location"]: r for r in client.get("/reports/risk").json()["results"]}
    assert set(results) == {"London", "Leeds", "Bristol"}
    assert results["London"] == {"location": "London", "window": "2024-05 to 2024-07", "count": 3,
                                 "usual": 1.0, "ratio": 3.0, "level": "high", "low_data": False}
    assert (results["Leeds"]["count"], results["Leeds"]["usual"], results["Leeds"]["level"]) == (0, 2.0, "low")
    assert results["Bristol"]["level"] == "high" and results["Bristol"]["ratio"] is None
    assert results["Bristol"]["low_data"] is True


def test_risk_with_no_data_is_empty():
    conn = connect(":memory:")
    init_db(conn)
    app.dependency_overrides[get_conn] = lambda: conn
    try:
        assert TestClient(app).get("/reports/risk").json()["results"] == []
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("count, usual, level", [
    (3, 2, "high"),
    (1, 2, "low"),
    (2, 2, "normal"),
    (0, 0, "normal"),
    (1, 0, "high"),
])
def test_risk_level(count, usual, level):
    assert risk_level(count, usual) == level


@pytest.mark.parametrize("month, by, expected", [
    ("2024-07", -2, "2024-05"),
    ("2024-01", -1, "2023-12"),
    ("2024-12", 1, "2025-01"),
    ("2024-05", -24, "2022-05"),
])
def test_shift_month(month, by, expected):
    assert shift_month(month, by) == expected
