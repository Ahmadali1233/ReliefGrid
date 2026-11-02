"""SQLite connection handling.

One shared connection guarded by a lock keeps things simple and safe: every change
runs inside a single transaction, so a crash half-way through can never leave
stock deducted without the matching allocation being recorded.
"""

import contextvars
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
SCHEMA = Path(__file__).with_name("schema.sql")

_conn = None
_lock = threading.RLock()

# The operator on shift for the current web request (set from the X-Operator header).
current_actor = contextvars.ContextVar("current_actor", default=None)

# Columns added after the first release: older databases get them automatically.
MIGRATIONS = [
    ("allocations", "status", "TEXT NOT NULL DEFAULT 'allocated'"),
    ("allocations", "dispatched_at", "TEXT"),
    ("allocations", "dispatched_by", "TEXT"),
    ("allocations", "delivered_at", "TEXT"),
    ("allocations", "received_by", "TEXT"),
    ("events", "actor", "TEXT"),
    ("shelters", "people", "INTEGER"),
    ("allocations", "note", "TEXT"),
    ("allocations", "shipment_id", "TEXT"),
    ("losses", "shipment_id", "TEXT"),
]


def _migrate(conn):
    for table, column, ddl in MIGRATIONS:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if cols and column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def db_path():
    return os.environ.get("RELIEFGRID_DB", str(BASE_DIR / "reliefgrid.db"))


def now():
    """Current local time as an ISO string (seconds precision)."""
    return datetime.now().isoformat(timespec="seconds")


def get_conn():
    """The shared connection, created (and the schema applied) on first use."""
    global _conn
    with _lock:
        if _conn is None:
            path = db_path()
            if path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA foreign_keys = ON")
            _conn.create_function("current_actor", 0, lambda: current_actor.get())
            schema = SCHEMA.read_text()
            tables, trigger = schema.split("-- Who did it:")
            _conn.executescript(tables)
            _migrate(_conn)
            _conn.executescript("-- Who did it:" + trigger)
        return _conn


def close_conn():
    """Close the shared connection (used by tests to start fresh)."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


@contextmanager
def transaction():
    """Run a block of changes as one all-or-nothing transaction."""
    conn = get_conn()
    with _lock:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except Exception:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")


def rows(sql, params=()):
    """Run a SELECT and return a list of plain dicts."""
    with _lock:
        return [dict(r) for r in get_conn().execute(sql, params).fetchall()]


def one(sql, params=()):
    """Run a SELECT and return the first row as a dict, or None."""
    with _lock:
        r = get_conn().execute(sql, params).fetchone()
        return dict(r) if r else None
