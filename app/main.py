import json
from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query

from app import db
from app.cleaning import clean_location
from app.sync import run_sync


@asynccontextmanager
async def lifespan(app):
    conn = db.connect()
    db.init_db(conn)
    with httpx.Client() as client:
        run_sync(conn, client)
    conn.close()
    yield


app = FastAPI(title="Tick Tracker API", lifespan=lifespan)

PERIOD_SQL = {
    "month": "date(date, 'start of month')",
    "week": "date(date, '-6 days', 'weekday 1')",
}

RISK_WINDOW_MONTHS = 3
HIGH_RATIO = 1.5
LOW_RATIO = 0.5
LOW_DATA_BELOW = 1


def get_conn():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def loaded_run(conn):
    return conn.execute(
        "SELECT * FROM sync_runs WHERE data_source IS NOT NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()


def wrap(conn, results, count=None):
    run = loaded_run(conn)
    return {
        "data_source": run["data_source"] if run else None,
        "count": len(results) if count is None else count,
        "results": results,
    }


def filters(start, end, location, species):
    where, params = [], []
    if start:
        where.append("date >= ?")
        params.append(start.isoformat())
    if end:
        where.append("date < ?")
        params.append((end + timedelta(days=1)).isoformat())
    if location:
        where.append("LOWER(location) = LOWER(?)")
        params.append(clean_location(location)[0])
    if species:
        where.append("LOWER(species) = LOWER(?)")
        params.append(species)
    return (" WHERE " + " AND ".join(where)) if where else "", params


def next_period(period, interval):
    if interval == "week":
        return period + timedelta(days=7)
    return date(period.year + period.month // 12, period.month % 12 + 1, 1)


def shift_month(month, by):
    total = int(month[:4]) * 12 + int(month[5:7]) - 1 + by
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def risk_level(count, usual):
    if usual == 0:
        return "high" if count else "normal"
    ratio = count / usual
    if ratio >= HIGH_RATIO:
        return "high"
    if ratio <= LOW_RATIO:
        return "low"
    return "normal"


@app.get("/sightings")
def search_sightings(
    start: date | None = None,
    end: date | None = None,
    location: str | None = None,
    species: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    conn=Depends(get_conn),
):
    where, params = filters(start, end, location, species)
    total = conn.execute(f"SELECT COUNT(*) FROM sightings{where}", params).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM sightings{where} ORDER BY date DESC LIMIT ? OFFSET ?", params + [limit, offset]
    ).fetchall()
    return wrap(conn, [dict(r) for r in rows], total)


@app.get("/sightings/{sighting_id}")
def get_sighting(sighting_id: str, conn=Depends(get_conn)):
    row = conn.execute("SELECT * FROM sightings WHERE id = ?", (sighting_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Sighting not found")
    return wrap(conn, [dict(row)])


@app.get("/reports/regions")
def sightings_per_region(start: date | None = None, end: date | None = None, conn=Depends(get_conn)):
    where, params = filters(start, end, None, None)
    rows = conn.execute(
        f"SELECT location, COUNT(*) AS count FROM sightings{where} GROUP BY location ORDER BY count DESC, location",
        params,
    ).fetchall()
    return wrap(conn, [dict(r) for r in rows])


@app.get("/reports/trends")
def trends(
    interval: Literal["week", "month"] = "month",
    start: date | None = None,
    end: date | None = None,
    location: str | None = None,
    species: str | None = None,
    conn=Depends(get_conn),
):
    where, params = filters(start, end, location, species)
    rows = conn.execute(
        f"SELECT {PERIOD_SQL[interval]} AS period, COUNT(*) AS count FROM sightings{where}"
        " GROUP BY period ORDER BY period",
        params,
    ).fetchall()
    counts = {r["period"]: r["count"] for r in rows}
    results = []
    if counts:
        period, last = date.fromisoformat(min(counts)), date.fromisoformat(max(counts))
        while period <= last:
            results.append({"period": period.isoformat(), "count": counts.get(period.isoformat(), 0)})
            period = next_period(period, interval)
    return wrap(conn, results)


@app.get("/reports/risk")
def risk(conn=Depends(get_conn)):
    rows = conn.execute(
        "SELECT location, substr(date, 1, 7) AS month, COUNT(*) AS count FROM sightings"
        " WHERE location != 'Unknown' GROUP BY location, month"
    ).fetchall()
    if not rows:
        return wrap(conn, [])
    counts = {(r["location"], r["month"]): r["count"] for r in rows}
    first = min(month for _, month in counts)
    latest = max(month for _, month in counts)
    window = [shift_month(latest, -i) for i in range(RISK_WINDOW_MONTHS)]

    years_back = 0
    while shift_month(window[-1], -12 * (years_back + 1)) >= first:
        years_back += 1

    results = []
    for city in sorted({city for city, _ in counts}):
        count = sum(counts.get((city, month), 0) for month in window)
        past = sum(
            counts.get((city, shift_month(month, -12 * years)), 0)
            for month in window
            for years in range(1, years_back + 1)
        )
        usual = past / years_back if years_back else 0
        results.append({
            "location": city,
            "window": f"{window[-1]} to {window[0]}",
            "count": count,
            "usual": round(usual, 2),
            "ratio": round(count / usual, 2) if usual else None,
            "level": risk_level(count, usual),
            "low_data": usual < LOW_DATA_BELOW,
        })
    results.sort(key=lambda r: (-r["count"], r["location"]))
    return wrap(conn, results)


@app.get("/health")
def health(conn=Depends(get_conn)):
    last = conn.execute("SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1").fetchone()
    loaded = loaded_run(conn)
    last_success = conn.execute(
        "SELECT finished_at FROM sync_runs WHERE status = 'success' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    sightings = conn.execute("SELECT COUNT(*) FROM sightings").fetchone()[0]

    if loaded is None:
        message = "No data loaded yet"
    elif loaded["data_source"] == "snapshot":
        message = f"Serving snapshot data from data/seed.json; live sync failed: {loaded['error']}"
    elif last["status"] == "failed":
        message = f"Serving last good live data from {loaded['finished_at']}; latest sync failed: {last['error']}"
    else:
        message = f"Serving live data synced at {loaded['finished_at']}"

    return {
        "status": "ok",
        "data_source": loaded["data_source"] if loaded else None,
        "message": message,
        "sightings": sightings,
        "last_sync": dict(last) if last else None,
        "last_successful_sync_at": last_success["finished_at"] if last_success else None,
    }


@app.get("/data-quality")
def data_quality(conn=Depends(get_conn)):
    run = loaded_run(conn)
    if run is None:
        return {"data_source": None, "message": "No data loaded yet"}

    rejected_by_reason = {}
    for row in conn.execute("SELECT reason, raw FROM rejected_records WHERE sync_run_id = ?", (run["id"],)):
        group = rejected_by_reason.setdefault(row["reason"], {"count": 0, "records": []})
        group["count"] += 1
        group["records"].append(json.loads(row["raw"]))

    unknown = conn.execute(
        "SELECT SUM(location = 'Unknown') AS locations, SUM(species = 'Unknown') AS species FROM sightings"
    ).fetchone()

    return {
        "data_source": run["data_source"],
        "synced_at": run["finished_at"],
        "fetched": run["fetched"],
        "kept": run["kept"],
        "duplicates": run["duplicates"],
        "rejected": run["rejected"],
        "locations_corrected": run["locations_corrected"],
        "rejected_by_reason": rejected_by_reason,
        "unknown_locations": unknown["locations"] or 0,
        "unknown_species": unknown["species"] or 0,
    }
