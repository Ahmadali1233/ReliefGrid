"""Loads the sample data in data/sample/ so the app has something to show on first run."""

import csv

from .database import BASE_DIR, now, transaction
from ..services.people import seed_defaults

SAMPLE = BASE_DIR / "data" / "sample"
WIPE_ORDER = ["supply_receipts", "supply_lines", "supply_orders", "losses", "shipments", "allocations", "run_entries", "runs", "movements", "events", "requests",
              "inventory", "shelters", "warehouses", "snapshots", "settings", "items"]


def _read(name):
    with open(SAMPLE / name, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def is_empty(conn):
    """True only on the very first run (no data and no choice made yet), so an empty start stays empty."""
    chosen = conn.execute("SELECT 1 FROM settings WHERE key = 'initialized'").fetchone()
    has_data = conn.execute("SELECT COUNT(*) AS n FROM warehouses").fetchone()["n"] > 0
    return not chosen and not has_data


def load_sample(allocate=True):
    """Wipe everything and load the sample data, then run the first allocation."""
    from ..services.allocation import run_allocation

    with transaction() as conn:
        for t in WIPE_ORDER:
            conn.execute(f"DELETE FROM {t}")
        ts = now()
        for w in _read("warehouses.csv"):
            conn.execute("INSERT INTO warehouses (id, name, lat, lon) VALUES (?, ?, ?, ?)",
                         (w["warehouse_id"], w["name"], float(w["lat"]), float(w["lon"])))
        for s in _read("shelters.csv"):
            conn.execute("INSERT INTO shelters (id, name, priority, lat, lon, people) VALUES (?, ?, ?, ?, ?, ?)",
                         (s["shelter_id"], s["name"], int(s["priority"]), float(s["lat"]), float(s["lon"]),
                          int(s["people"]) if s.get("people") else None))
        seed_defaults(conn)
        for i in _read("inventory.csv"):
            q = int(i["quantity"])
            conn.execute("INSERT INTO inventory (warehouse_id, item, quantity, unit) VALUES (?, ?, ?, ?)",
                         (i["warehouse_id"], i["item"], q, i["unit"]))
            conn.execute("INSERT INTO movements (warehouse_id, item, delta, reason, ref, created_at) "
                         "VALUES (?, ?, ?, 'opening stock', NULL, ?)", (i["warehouse_id"], i["item"], q, ts))
        for r in _read("requests.csv"):
            conn.execute("INSERT INTO requests (id, shelter_id, item, quantity, urgency, created_at) "
                         "VALUES (?, ?, ?, ?, ?, ?)",
                         (r["request_id"], r["shelter_id"], r["item"], int(r["quantity"]),
                          r["urgency"], r["created_at"]))
        conn.execute("INSERT INTO events (created_at, kind, message, data) VALUES (?, 'system', ?, NULL)",
                     (ts, "Loaded sample data: 2 warehouses, 14 shelters, 7 items, 48 requests"))
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('initialized', 'sample')")
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('figures_seeded', '1')")
        if allocate:
            run_allocation(conn, "sample data loaded")
            _sample_history(conn)


DRIVERS = ["Truck 3 · Imran", "Truck 5 · Rashid", "Van 2 · Saima", "Truck 7 · Ahmed"]
RECEIVERS = {"SH-01": "Ayesha (head teacher)", "SH-08": "Dr. Khalid", "SH-11": "Bilal (volunteer)"}
LOADING = {"SH-14"}   # priority 1, but its truck hasn't left yet


def _sample_history(conn):
    """Make the sample look like a hub mid-shift: most of the vulnerable shelters already have their deliveries
    (on numbered waybills, signed for), a few trucks are on the road, the rest is waiting to be loaded."""
    from ..services.dispatch import create_shipment
    ts = now()
    pairs = conn.execute("""SELECT DISTINCT a.warehouse_id, r.shelter_id, s.priority FROM allocations a
                            JOIN requests r ON r.id = a.request_id JOIN shelters s ON s.id = r.shelter_id
                            ORDER BY s.priority, r.shelter_id, a.warehouse_id""").fetchall()
    for i, p in enumerate(pairs):
        if p["shelter_id"] in LOADING:
            continue
        delivered = p["priority"] == 1
        on_road = p["priority"] == 2 and i % 3 == 0
        if not delivered and not on_road:
            continue
        ids = [x["id"] for x in conn.execute(
            "SELECT a.id FROM allocations a JOIN requests r ON r.id = a.request_id "
            "WHERE a.warehouse_id = ? AND r.shelter_id = ?", (p["warehouse_id"], p["shelter_id"]))]
        marks = ",".join("?" for _ in ids)
        driver = DRIVERS[i % len(DRIVERS)]
        number = create_shipment(conn, p["warehouse_id"], p["shelter_id"], ids, ts)
        if delivered:
            who = RECEIVERS.get(p["shelter_id"], "Shelter manager")
            conn.execute(f"UPDATE allocations SET status = 'delivered', dispatched_at = ?, dispatched_by = ?, "
                         f"delivered_at = ?, received_by = ? WHERE id IN ({marks})", [ts, driver, ts, who, *ids])
            conn.execute("UPDATE shipments SET status = 'delivered', dispatched_at = ?, driver = ?, delivered_at = ?, "
                         "received_by = ? WHERE id = ?", (ts, driver, ts, who, number))
        else:
            conn.execute(f"UPDATE allocations SET status = 'dispatched', dispatched_at = ?, dispatched_by = ? "
                         f"WHERE id IN ({marks})", [ts, driver, *ids])
            conn.execute("UPDATE shipments SET status = 'on_the_way', dispatched_at = ?, driver = ? WHERE id = ?",
                         (ts, driver, number))
    conn.execute("INSERT INTO events (created_at, kind, message, data) VALUES (?, 'system', ?, NULL)",
                 (ts, "Sample history: most priority-1 shelters delivered and signed for, some trucks on the road"))


def load_empty():
    """Wipe everything for a real deployment: no sample data. Add warehouses, shelters and stock yourself."""
    with transaction() as conn:
        for t in WIPE_ORDER:
            conn.execute(f"DELETE FROM {t}")
        seed_defaults(conn)
        conn.execute("INSERT INTO events (created_at, kind, message, data) VALUES (?, 'system', ?, NULL)",
                     (now(), "Started with an empty database"))
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('initialized', 'empty')")
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('figures_seeded', '1')")
