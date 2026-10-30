from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.db import connect, init_db
from app.sync import run_sync


@asynccontextmanager
async def lifespan(app):
    conn = connect()
    init_db(conn)
    with httpx.Client() as client:
        run_sync(conn, client)
    conn.close()
    yield


app = FastAPI(title="Tick Tracker API", lifespan=lifespan)
