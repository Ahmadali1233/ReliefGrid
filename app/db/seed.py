"""Loads the sample data in data/sample/ so the app has something to show on first run.

The sample is a real-looking shift at a relief hub in Dadu: requests came in over the last day, stock was counted
at the start, trucks left and were signed for at believable times, one supply order already arrived and another is
on its way. Every time is relative to the moment the sample is loaded, so the log always reads like today."""

import csv
import json
from datetime import datetime, timedelta

from .database import BASE_DIR, transaction
from ..services.people import seed_defaults

SAMPLE = BASE_DIR / "data" / "sample"
WIPE_ORDER = ["supply_receipts", "supply_lines", "supply_orders", "losses", "shipments", "allocations", "run_entries", "runs", "movements", "events", "requests",
              "inventory", "shelters", "warehouses", "snapshots", "settings", "items"]

HUB = ["Sana (hub)", "Usman (hub)"]                                   # who typed requests in at the hub
STORE = {"WH-A": "Nadeem (Warehouse A)", "WH-B": "Farah (Warehouse B)"}
DRIVERS = ["Truck 3 · Imran", "Truck 5 · Rashid", "Van 2 · Saima", "Truck 7 · Ahmed", "Van 4 · Javed"]
RECEIVERS = {"SH-01": "Ayesha (head teacher)", "SH-02": "Ghulam Rasool (caretaker)", "SH-03": "Shabana (volunteer)",
             "SH-04": "Mukhtiar (camp lead)", "SH-05": "Zubair (volunteer)", "SH-06": "Prof. Asif",
             "SH-07": "Rukhsana (camp lead)", "SH-08": "Dr. Khalid", "SH-09": "Sajid (college office)",
             "SH-10": "Hina (youth worker)", "SH-11": "Bilal (volunteer)", "SH-12": "Nasreen (teacher)",
             "SH-13": "Maulana Rafiq", "SH-14": "Dr. Saira"}
LOADING = {"SH-14"}   # priority 1, but its truck hasn't left yet
# One supply order already arrived (its stock is part of today's shelves), one is still on its way.
ARRIVED_ORDER = {"warehouse_id": "WH-A", "item": "Blankets", "quantity": 150, "unit": "blankets"}
OPEN_ORDER = {"warehouse_id": "WH-B", "item": "First aid kits", "quantity": 100, "unit": "kits"}
SUPPLIER = "HQ supply desk"
SAMPLE_VERSION = "dadu-2"   # bump when the sample changes; untouched old samples are refreshed on start


def _read(name):
    with open(SAMPLE / name, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _iso(d):
    return d.isoformat(timespec="seconds")


def old_sample(conn):
    """True when the database still holds the sample from an older version (for example the Dubai names) and
    nobody has added anything of their own since: the latest sample can replace it without losing work."""
    row = lambda k: conn.execute("SELECT value FROM settings WHERE key = ?", (k,)).fetchone()
    if not row("initialized") or row("initialized")["value"] != "sample":
        return False
    if row("sample_version") and row("sample_version")["value"] == SAMPLE_VERSION:
        return False
    names = {r["name"] for r in _read("shelters.csv")}
    mine = conn.execute("SELECT COUNT(*) AS n FROM events WHERE kind NOT IN ('allocation', 'system')").fetchone()["n"]
    return not any(r["name"] in names for r in conn.execute("SELECT name FROM shelters")) or mine == 0


def is_empty(conn):
    """True only on the very first run (no data and no choice made yet), so an empty start stays empty."""
    chosen = conn.execute("SELECT 1 FROM settings WHERE key = 'initialized'").fetchone()
    has_data = conn.execute("SELECT COUNT(*) AS n FROM warehouses").fetchone()["n"] > 0
    return not chosen and not has_data


def _number(conn, kind, prefix, when):
    """Next WB-/PO- number for the day `when` falls on. Uses the same never-reused counters as live work."""
    from ..services.dispatch import _key
    day = when.strftime("%m%d")
    name = f"{kind}-{day}"
    seq = int(_key(conn, name, lambda: "0")) + 1
    conn.execute("UPDATE keys SET value = ? WHERE name = ?", (str(seq), name))
    return f"{prefix}-{day}-{seq:03d}"


def _event(conn, when, kind, message, data=None, actor=None):
    conn.execute("INSERT INTO events (created_at, kind, message, data, actor) VALUES (?, ?, ?, ?, ?)",
                 (_iso(when), kind, message, json.dumps(data) if data else None, actor))


def load_sample(allocate=True):
    """Wipe everything and load the sample data, then run the first allocation."""
    from ..services.allocation import run_allocation

    end = datetime.now().replace(microsecond=0)
    reqs = _read("requests.csv")
    # Requests arrived about every 26 minutes over the last day; the newest one 18 minutes ago. Order is kept.
    req_time = {r["request_id"]: end - timedelta(minutes=18 + (len(reqs) - 1 - i) * 26) for i, r in enumerate(reqs)}
    opened = min(req_time.values()) - timedelta(minutes=75)

    with transaction() as conn:
        for t in WIPE_ORDER:
            conn.execute(f"DELETE FROM {t}")
        warehouses = {}
        for w in _read("warehouses.csv"):
            warehouses[w["warehouse_id"]] = w["name"]
            conn.execute("INSERT INTO warehouses (id, name, lat, lon) VALUES (?, ?, ?, ?)",
                         (w["warehouse_id"], w["name"], float(w["lat"]), float(w["lon"])))
        for s in _read("shelters.csv"):
            conn.execute("INSERT INTO shelters (id, name, priority, lat, lon, people) VALUES (?, ?, ?, ?, ?, ?)",
                         (s["shelter_id"], s["name"], int(s["priority"]), float(s["lat"]), float(s["lon"]),
                          int(s["people"]) if s.get("people") else None))
        seed_defaults(conn)
        _event(conn, opened - timedelta(minutes=5), "system",
               f"Sample data loaded: Dadu district, {len(warehouses)} warehouses, 14 shelters, {len(reqs)} requests",
               actor="ReliefGrid")
        a = ARRIVED_ORDER
        for i in _read("inventory.csv"):
            q = int(i["quantity"])
            conn.execute("INSERT INTO inventory (warehouse_id, item, quantity, unit) VALUES (?, ?, ?, ?)",
                         (i["warehouse_id"], i["item"], q, i["unit"]))
            first = q - a["quantity"] if (i["warehouse_id"], i["item"]) == (a["warehouse_id"], a["item"]) else q
            conn.execute("INSERT INTO movements (warehouse_id, item, delta, reason, ref, created_at) "
                         "VALUES (?, ?, ?, 'opening stock', NULL, ?)", (i["warehouse_id"], i["item"], first, _iso(opened)))
        for wid, wname in warehouses.items():
            _event(conn, opened + timedelta(minutes=4 if wid == "WH-A" else 9), "restock",
                   f"Opening stock counted at {wname}", {"warehouse_id": wid}, actor=STORE.get(wid))
        _sample_orders(conn, warehouses, opened, end)
        for r in reqs:
            conn.execute("INSERT INTO requests (id, shelter_id, item, quantity, urgency, created_at) "
                         "VALUES (?, ?, ?, ?, ?, ?)",
                         (r["request_id"], r["shelter_id"], r["item"], int(r["quantity"]), r["urgency"],
                          _iso(req_time[r["request_id"]])))
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('initialized', 'sample')")
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('sample_version', ?)", (SAMPLE_VERSION,))
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('figures_seeded', '1')")
        if allocate:
            run_allocation(conn, "sample data loaded")
            _retime_allocations(conn, req_time)
            _sample_history(conn, warehouses, req_time, end)


def _sample_orders(conn, warehouses, opened, end):
    from ..services.supply import _lines_text
    a, o = ARRIVED_ORDER, OPEN_ORDER
    placed, arrived = opened + timedelta(minutes=50), opened + timedelta(hours=5, minutes=20)
    number = _number(conn, "order", "PO", placed)
    conn.execute("INSERT INTO supply_orders (id, created_at, supplier, sent_via, warehouse_id) VALUES (?, ?, ?, 'whatsapp', ?)",
                 (number, _iso(placed), SUPPLIER, a["warehouse_id"]))
    conn.execute("INSERT INTO supply_lines (order_id, item, unit, quantity, received) VALUES (?, ?, ?, ?, ?)",
                 (number, a["item"], a["unit"], a["quantity"], a["quantity"]))
    text = _lines_text([a])
    _event(conn, placed, "order", f"{number} ordered from {SUPPLIER} by WhatsApp: {text}, to {warehouses[a['warehouse_id']]}",
           {"order": number}, actor=HUB[0])
    conn.execute("INSERT INTO movements (warehouse_id, item, delta, reason, ref, created_at) "
                 "VALUES (?, ?, ?, 'delivery received', ?, ?)", (a["warehouse_id"], a["item"], a["quantity"], number, _iso(arrived)))
    rid = conn.execute("INSERT INTO supply_receipts (order_id, created_at, warehouse_id, lines) VALUES (?, ?, ?, ?)",
                       (number, _iso(arrived), a["warehouse_id"], json.dumps({a["item"]: a["quantity"]}))).lastrowid
    _event(conn, arrived, "order", f"{number} arrived in full at {warehouses[a['warehouse_id']]}: {text}",
           {"order": number, "receipt": rid}, actor=STORE[a["warehouse_id"]])
    placed = end - timedelta(minutes=55)
    number = _number(conn, "order", "PO", placed)
    conn.execute("INSERT INTO supply_orders (id, created_at, supplier, sent_via, warehouse_id) VALUES (?, ?, ?, 'whatsapp', ?)",
                 (number, _iso(placed), SUPPLIER, o["warehouse_id"]))
    conn.execute("INSERT INTO supply_lines (order_id, item, unit, quantity) VALUES (?, ?, ?, ?)",
                 (number, o["item"], o["unit"], o["quantity"]))
    _event(conn, placed, "order", f"{number} ordered from {SUPPLIER} by WhatsApp: {_lines_text([o])}, to {warehouses[o['warehouse_id']]}",
           {"order": number}, actor=HUB[1])


def _retime_allocations(conn, req_time):
    """The first allocation ran just now; in the story each request was reserved the moment it was typed in."""
    order = sorted(req_time, key=req_time.get)
    for i, rid in enumerate(order):
        at = _iso(req_time[rid] + timedelta(seconds=40))
        conn.execute("UPDATE allocations SET created_at = ? WHERE request_id = ?", (at, rid))
        conn.execute("UPDATE events SET created_at = ?, actor = ? WHERE kind = 'allocation' AND json_extract(data, '$.request_id') = ?",
                     (at, HUB[i % 2], rid))


def _sample_history(conn, warehouses, req_time, end):
    """A hub mid-shift: most of the vulnerable shelters already have their deliveries (on numbered waybills, signed
    for), a few trucks are on the road, the rest is waiting to be loaded. Times follow real driving distances."""
    from ..services.dispatch import _units_text, drive_minutes
    pairs = conn.execute("""SELECT a.warehouse_id, r.shelter_id, s.priority, s.name AS shelter_name,
                                   MAX(r.created_at) AS last_request, MAX(a.distance_km) AS km
                            FROM allocations a JOIN requests r ON r.id = a.request_id JOIN shelters s ON s.id = r.shelter_id
                            GROUP BY a.warehouse_id, r.shelter_id ORDER BY s.priority, r.shelter_id, a.warehouse_id""").fetchall()
    plan = []
    for i, p in enumerate(pairs):
        if p["shelter_id"] in LOADING:
            continue
        want = "delivered" if p["priority"] == 1 else "on_the_way" if p["priority"] == 2 and i % 3 == 0 else None
        if not want:
            continue
        drive = drive_minutes(p["km"]) or 30
        ready = datetime.fromisoformat(p["last_request"]) + timedelta(minutes=20 + (i % 3) * 9)
        left = ready + timedelta(minutes=15)
        if want == "delivered" and left + timedelta(minutes=drive + 5) > end:
            want = "on_the_way"
        if want == "on_the_way":
            left = max(ready + timedelta(minutes=10), end - timedelta(minutes=max(4, drive * 0.55)))
            if left > end - timedelta(minutes=3):
                continue                                    # too fresh: still being loaded
        plan.append((ready, left, want, drive, i, p))
    for ready, left, want, drive, i, p in sorted(plan, key=lambda x: x[1]):
        ids = [x["id"] for x in conn.execute(
            "SELECT a.id FROM allocations a JOIN requests r ON r.id = a.request_id WHERE a.warehouse_id = ? AND r.shelter_id = ?",
            (p["warehouse_id"], p["shelter_id"]))]
        by_item = {}
        for x in conn.execute(f"SELECT item, quantity FROM allocations WHERE id IN ({','.join('?' * len(ids))})", ids):
            by_item[x["item"]] = by_item.get(x["item"], 0) + x["quantity"]
        marks = ",".join("?" for _ in ids)
        ready = max(ready, left - timedelta(minutes=18 + i % 3 * 7))     # the slip is printed shortly before loading
        number = _number(conn, "waybill", "WB", ready)
        driver = DRIVERS[i % len(DRIVERS)]
        wname, sname, text = warehouses[p["warehouse_id"]], p["shelter_name"], _units_text(conn, by_item)
        conn.execute("INSERT INTO shipments (id, warehouse_id, shelter_id, status, created_at, dispatched_at, driver) "
                     "VALUES (?, ?, ?, 'on_the_way', ?, ?, ?)", (number, p["warehouse_id"], p["shelter_id"], _iso(ready), _iso(left), driver))
        conn.execute(f"UPDATE allocations SET shipment_id = ?, status = 'dispatched', dispatched_at = ?, dispatched_by = ? "
                     f"WHERE id IN ({marks})", [number, _iso(left), driver, *ids])
        _event(conn, ready, "waybill", f"{number} printed for {sname}: {text}",
               {"waybill": number, "shelter_id": p["shelter_id"]}, actor=STORE.get(p["warehouse_id"]))
        _event(conn, left, "dispatch", f"{number} left {wname} for {sname} with {driver}: {text}",
               {"waybill": number, "warehouse_id": p["warehouse_id"], "shelter_id": p["shelter_id"], "units": sum(by_item.values())},
               actor=driver)
        if want == "delivered":
            got = left + timedelta(minutes=drive + 3 + i % 4)
            who = RECEIVERS.get(p["shelter_id"], "Shelter manager")
            conn.execute(f"UPDATE allocations SET status = 'delivered', delivered_at = ?, received_by = ? WHERE id IN ({marks})",
                         [_iso(got), who, *ids])
            conn.execute("UPDATE shipments SET status = 'delivered', delivered_at = ?, received_by = ? WHERE id = ?",
                         (_iso(got), who, number))
            _event(conn, got, "delivered", f"{number} delivered to {sname}, signed by {who}: {text}",
                   {"waybill": number, "shelter_id": p["shelter_id"], "units": sum(by_item.values()), "lost": 0, "requeued": []},
                   actor=who)


def load_empty():
    """Wipe everything for a real deployment: no sample data. Add warehouses, shelters and stock yourself."""
    with transaction() as conn:
        for t in WIPE_ORDER:
            conn.execute(f"DELETE FROM {t}")
        seed_defaults(conn)
        _event(conn, datetime.now(), "system", "Started with an empty database", actor="ReliefGrid")
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('initialized', 'empty')")
