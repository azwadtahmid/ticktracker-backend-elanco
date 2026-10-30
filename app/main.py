"""FastAPI app: the HTTP endpoints. They read only from SQLite, never from Elanco's API."""
from fastapi import FastAPI

app = FastAPI(title="Tick Tracker API")
