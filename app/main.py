"""ReliefGrid — Emergency Relief Operations & Dispatch System. Team FEAST, RIT Dubai 2026."""

import asyncio
import logging
import re
import sqlite3
from urllib.parse import unquote
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import inventory, requests, supply, system
from .db.database import current_actor, get_conn, transaction
from .db.seed import is_empty, load_sample, old_sample
from .services.actions import NotFound

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
log = logging.getLogger("reliefgrid")


@asynccontextmanager
async def lifespan(app):
    conn = get_conn()
    if is_empty(conn):
        load_sample()
    elif old_sample(conn):
        load_sample()
        print("  Sample data updated to the latest version (Dadu district).")
    elif not conn.execute("SELECT 1 FROM settings WHERE key = 'figures_seeded'").fetchone():
        # Databases from before planning figures existed: add the defaults once.
        from .services.people import seed_defaults
        with transaction() as c:
            if not c.execute("SELECT 1 FROM items LIMIT 1").fetchone():
                seed_defaults(c)
            c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('figures_seeded', '1')")
    from .services.dispatch import backfill
    with transaction() as c:
        backfill(c)
    yield


app = FastAPI(
    title="ReliefGrid API",
    description="Matches urgent shelter requests with available supplies. "
                "Every change re-runs allocation in priority order: Critical > High > Moderate.",
    version="1.0.0",
    lifespan=lifespan,
)


def _error(status, message):
    return JSONResponse(status_code=status, content={"error": message})


@app.exception_handler(ValueError)
async def value_error(_: Request, exc: ValueError):
    return _error(400, str(exc))


@app.exception_handler(LookupError)
async def lookup_error(_: Request, exc: LookupError):
    return _error(404, str(exc.args[0]) if exc.args else "Not found.")


@app.exception_handler(PermissionError)
async def forbidden(_: Request, exc: PermissionError):
    return _error(403, str(exc))


@app.exception_handler(NotFound)
async def not_found(_: Request, exc: NotFound):
    return _error(404, str(exc))


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    return _error(exc.status_code, str(exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    parts = []
    for e in exc.errors():
        field = str(e["loc"][-1]).replace("_", " ").capitalize() if e.get("loc") else "Input"
        if e["type"].startswith("int"):
            parts.append(f"{field} must be a whole number.")
        elif e["type"] == "missing":
            parts.append(f"{field} is required.")
        elif e["type"].startswith("float"):
            parts.append(f"{field} must be a number.")
        else:
            parts.append(f"{field}: {e['msg']}.")
    return _error(400, " ".join(dict.fromkeys(parts)) or "Some of the input isn't valid.")


@app.exception_handler(sqlite3.IntegrityError)
async def integrity_error(_: Request, exc: sqlite3.IntegrityError):
    log.warning("Database refused a change: %s", exc)
    return _error(409, "The database refused that change because it would break a rule "
                       "(for example negative stock). Nothing was changed.")


@app.exception_handler(Exception)
async def unexpected(_: Request, exc: Exception):
    log.exception("Unexpected error")
    return _error(500, "Something went wrong on our side. Nothing was changed. Please try again.")


@app.middleware("http")
async def operator(request: Request, call_next):
    """Record who is on shift (sent by the interface) so every log entry says who did it."""
    raw = request.headers.get("x-operator") or ""
    name = re.sub(r"\s+", " ", unquote(raw)).strip()[:40] or None   # sent URL-encoded so any language works
    token = current_actor.set(name)
    try:
        if request.url.path.startswith("/api/"):
            # One API call at a time: every call shares one SQLite connection, so a screen refreshing while a
            # change is being saved must not read the change half-done. Calls take milliseconds, so nobody waits.
            async with _one_at_a_time:
                return await call_next(request)
        return await call_next(request)
    finally:
        current_actor.reset(token)


_one_at_a_time = asyncio.Lock()


app.include_router(system.router)
app.include_router(requests.router)
app.include_router(inventory.router)
app.include_router(supply.router)
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
