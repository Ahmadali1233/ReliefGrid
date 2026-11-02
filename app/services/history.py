"""Undo: a copy of the data is saved before every change, and Undo puts the latest copy back.

The activity log is not part of that copy: it only ever grows. Undo leaves the original entries in place, marks
them "undone" and adds an "Undid: ..." entry, so the record of what happened can't be quietly erased."""

import json
from datetime import datetime, timedelta

from ..db.database import now

# Tables restored by Undo, in an order that respects foreign keys.
UNDO_WINDOW_MINUTES = 10   # undo is for "oops, I just typed that wrong", not for rewriting history

TABLES = ["warehouses", "shelters", "inventory", "requests", "runs", "allocations",
          "run_entries", "movements", "settings", "items", "losses", "shipments",
          "supply_orders", "supply_lines", "supply_receipts"]
KEEP = 30


def snapshot(conn, label):
    """Save the current data. Call inside a transaction, before making the change."""
    data = {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t}")] for t in TABLES}
    conn.execute("INSERT INTO snapshots (created_at, label, data) VALUES (?, ?, ?)",
                 (now(), label, json.dumps(data)))
    conn.execute("DELETE FROM snapshots WHERE id NOT IN "
                 "(SELECT id FROM snapshots ORDER BY id DESC LIMIT ?)", (KEEP,))


def _recent(row):
    try:
        age = datetime.now() - datetime.fromisoformat(row["created_at"])
    except (TypeError, ValueError):
        return False
    return age <= timedelta(minutes=UNDO_WINDOW_MINUTES)


def last_label(conn):
    """The change that can be undone right now, or None (nothing recent enough)."""
    row = conn.execute("SELECT label, created_at FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
    return row["label"] if row and _recent(row) else None


def last_snapshot(conn):
    """The change Undo would reverse right now: label, time and seconds left in the window. None if nothing."""
    row = conn.execute("SELECT label, created_at FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
    if not row or not _recent(row):
        return None
    left = UNDO_WINDOW_MINUTES * 60 - (datetime.now() - datetime.fromisoformat(row["created_at"])).total_seconds()
    return {"label": row["label"], "at": row["created_at"], "seconds_left": max(0, int(left))}


def mark_undone(conn, since):
    """Flag the log entries written by the change being undone. They stay in the log, shown as undone."""
    conn.execute("UPDATE events SET data = json_set(COALESCE(data, '{}'), '$.undone', 1) "
                 "WHERE created_at >= ? AND kind != 'undo' AND json_extract(COALESCE(data, '{}'), '$.undone') IS NULL",
                 (since,))


def undo(conn):
    """Restore the most recent snapshot. Returns its label, or None if there is nothing to undo."""
    row = conn.execute("SELECT id, label, data, created_at FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
    if not row or not _recent(row):
        return None
    data = json.loads(row["data"])
    for t in reversed(TABLES):
        conn.execute(f"DELETE FROM {t}")
    for t in TABLES:
        for r in data.get(t, []):
            cols = ", ".join(r)
            marks = ", ".join("?" for _ in r)
            conn.execute(f"INSERT INTO {t} ({cols}) VALUES ({marks})", list(r.values()))
    conn.execute("DELETE FROM snapshots WHERE id = ?", (row["id"],))
    mark_undone(conn, row["created_at"])
    conn.execute("INSERT INTO events (created_at, kind, message, data) VALUES (?, ?, ?, ?)",
                 (now(), "undo", f"Undid: {row['label']}", None))
    return row["label"]
