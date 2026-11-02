"""Runs the engine against the database and records the results in one transaction."""

import json

from ..db.database import get_conn, now
from ..engine import allocate, clean_rules, explain


def load_rules(conn=None):
    """Current rule toggles (defaults merged with anything saved on the Rules screen)."""
    row = (conn or get_conn()).execute("SELECT value FROM settings WHERE key = 'rules'").fetchone()
    return clean_rules(json.loads(row["value"]) if row else {})


def load_state(conn):
    """Everything the engine needs, read from the database."""
    from .people import daily_need, figure_for, figures
    figs = figures(conn)
    reqs = [dict(r) for r in conn.execute(
        """SELECT r.id, r.shelter_id, r.item, r.quantity, r.allocated, r.urgency, r.created_at,
                  s.priority AS shelter_priority, s.lat, s.lon, s.name AS shelter_name, s.people
           FROM requests r JOIN shelters s ON s.id = r.shelter_id
           WHERE r.cancelled = 0""").fetchall()]
    for r in reqs:
        r["daily_need"] = daily_need(r["people"], figure_for(figs, r["item"]))
    stock, units = {}, {}
    for r in conn.execute("SELECT warehouse_id, item, quantity, unit FROM inventory"):
        stock[(r["warehouse_id"], r["item"])] = r["quantity"]
        units.setdefault(r["item"], r["unit"])
    warehouses, wh_names = {}, {}
    for w in conn.execute("SELECT id, name, lat, lon FROM warehouses"):
        warehouses[w["id"]] = (w["lat"], w["lon"])
        wh_names[w["id"]] = w["name"]
    return reqs, stock, warehouses, wh_names, units


def preview(conn, extra_requests=(), extra_stock=None):
    """Dry run: what would happen, without changing anything."""
    reqs, stock, warehouses, wh_names, units = load_state(conn)
    reqs = reqs + list(extra_requests)
    stock = dict(stock)
    for key, units_added in (extra_stock or {}).items():
        stock[key] = stock.get(key, 0) + units_added
    decisions, _ = allocate(reqs, stock, warehouses, load_rules(conn))
    return decisions


def run_allocation(conn, trigger):
    """Allocate waiting requests. Must be called inside database.transaction().

    Returns (run_id or None, decisions).
    """
    from .dispatch import prune
    prune(conn)      # waybills left empty by a cancel or a change
    rules = load_rules(conn)
    reqs, stock, warehouses, wh_names, units = load_state(conn)
    decisions, _ = allocate(reqs, stock, warehouses, rules)
    if not decisions:
        return None, []

    by_id = {r["id"]: r for r in reqs}
    ts = now()
    run_id = conn.execute(
        "INSERT INTO runs (created_at, trigger, rules) VALUES (?, ?, ?)",
        (ts, trigger, json.dumps(rules)),
    ).lastrowid

    for d in decisions:
        r = by_id[d.request_id]
        seen_before = conn.execute(
            "SELECT 1 FROM run_entries WHERE request_id = ? LIMIT 1", (d.request_id,)).fetchone()
        conn.execute(
            "INSERT INTO run_entries (run_id, request_id, item, rank, eligible, given) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, d.request_id, d.item, d.rank, d.eligible, d.given),
        )
        for t in d.takes:
            conn.execute(
                "INSERT INTO allocations (run_id, request_id, warehouse_id, item, quantity, distance_km, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, d.request_id, t.warehouse_id, d.item, t.quantity, t.distance_km, ts),
            )
            conn.execute(
                "UPDATE inventory SET quantity = quantity - ? WHERE warehouse_id = ? AND item = ?",
                (t.quantity, t.warehouse_id, d.item),
            )
            conn.execute(
                "INSERT INTO movements (warehouse_id, item, delta, reason, ref, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (t.warehouse_id, d.item, -t.quantity, "allocation", d.request_id, ts),
            )

        why = explain(d, r["shelter_name"], wh_names, units.get(d.item, "units"), r["shelter_priority"], rules)
        conn.execute(
            "UPDATE requests SET allocated = ?, status = ?, explanation = ? WHERE id = ?",
            (d.total, d.status, json.dumps(why), d.request_id),
        )

        unit = units.get(d.item, "")
        if d.given > 0 and d.already == 0:
            msg = f"{r['shelter_name']} asked for {d.requested:,} {d.item.lower()}: {d.given:,} reserved"
        elif d.given > 0:
            msg = f"{r['shelter_name']}: {d.given:,} more {d.item.lower()} reserved (now {d.total:,} of {d.requested:,})"
        elif not seen_before:
            msg = f"{r['shelter_name']} asked for {d.requested:,} {d.item.lower()}: none in stock, waiting"
        else:
            continue
        conn.execute(
            "INSERT INTO events (created_at, kind, message, data) VALUES (?, ?, ?, ?)",
            (ts, "allocation", msg, json.dumps({
                "request_id": d.request_id, "run_id": run_id, "status": d.status, "given": d.given,
                "unit": unit, "from": [t.warehouse_id for t in d.takes],
            })),
        )
    return run_id, decisions
