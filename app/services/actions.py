"""Everything that changes data. Each action: save an undo snapshot, change, re-allocate — in one transaction."""

import json
import re

from ..db.database import now, transaction
from ..engine import URGENCY_LEVELS, clean_rules, normalize_urgency
from .allocation import load_rules, run_allocation
from .history import snapshot


class NotFound(LookupError):
    pass


def _event(conn, kind, message, data=None):
    conn.execute("INSERT INTO events (created_at, kind, message, data) VALUES (?, ?, ?, ?)",
                 (now(), kind, message, json.dumps(data) if data is not None else None))


def _canonical_item(conn, item):
    item = re.sub(r"\s+", " ", (item or "")).strip()
    if not item:
        raise ValueError("Choose an item.")
    for row in conn.execute("SELECT item FROM inventory UNION SELECT item FROM requests"):
        if row["item"].lower() == item.lower():
            return row["item"]
    return item[0].upper() + item[1:]


def _whole(value, name, minimum=1):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a whole number.")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{name} must be a whole number, like 40.")
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a whole number, like 40.")
    if n < minimum:
        raise ValueError(f"{name} must be {minimum} or more.")
    if n > 1_000_000:
        raise ValueError(f"{name} of {n:,} looks like a typo.")
    return n


def _next_request_id(conn):
    best = 0
    for row in conn.execute("SELECT id FROM requests"):
        m = re.fullmatch(r"REQ-(\d+)", row["id"])
        if m:
            best = max(best, int(m.group(1)))
    return f"REQ-{best + 1:03d}"


def create_request(shelter_id, item, quantity, urgency):
    with transaction() as conn:
        shelter = conn.execute("SELECT id, name FROM shelters WHERE id = ?", (shelter_id,)).fetchone()
        if not shelter:
            raise ValueError(f"Shelter {shelter_id} doesn't exist.")
        item = _canonical_item(conn, item)
        quantity = _whole(quantity, "Quantity")
        level, ok = normalize_urgency(urgency)
        if not ok:
            raise ValueError(f"Urgency must be one of: {', '.join(l.title() for l in URGENCY_LEVELS)}.")
        snapshot(conn, f"new request for {shelter['name']}")
        rid = _next_request_id(conn)
        conn.execute("INSERT INTO requests (id, shelter_id, item, quantity, urgency, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (rid, shelter_id, item, quantity, level, now()))
        _event(conn, "request", f"New {level} request {rid}: {shelter['name']} needs {quantity:,} {item.lower()}",
               {"request_id": rid})
        run_id, decisions = run_allocation(conn, f"new request {rid}")
    mine = next((d for d in decisions if d.request_id == rid), None)
    return {"id": rid, "given": mine.given if mine else 0, "status": mine.status if mine else "unfilled",
            "requested": quantity, "item": item, "shelter": shelter["name"], "run_id": run_id}


def cancel_request(request_id):
    with transaction() as conn:
        r = conn.execute("SELECT r.*, s.name AS shelter_name FROM requests r JOIN shelters s ON s.id = r.shelter_id "
                         "WHERE r.id = ?", (request_id,)).fetchone()
        if not r:
            raise NotFound(f"Request {request_id} doesn't exist.")
        if r["cancelled"]:
            raise ValueError(f"{request_id} is already cancelled.")
        gone = conn.execute("SELECT COALESCE(SUM(quantity), 0) AS u FROM allocations "
                            "WHERE request_id = ? AND status != 'allocated'", (request_id,)).fetchone()["u"]
        if gone:
            raise ValueError(f"{gone:,} units for {request_id} are already on a truck or delivered, so it can't be "
                             f"cancelled. Record a return as a new delivery instead.")
        snapshot(conn, f"cancel {request_id}")
        returned = 0
        ts = now()
        for a in conn.execute("SELECT warehouse_id, SUM(quantity) AS q FROM allocations WHERE request_id = ? "
                              "GROUP BY warehouse_id", (request_id,)).fetchall():
            conn.execute("UPDATE inventory SET quantity = quantity + ? WHERE warehouse_id = ? AND item = ?",
                         (a["q"], a["warehouse_id"], r["item"]))
            conn.execute("INSERT INTO movements (warehouse_id, item, delta, reason, ref, created_at) "
                         "VALUES (?, ?, ?, 'cancelled request returned', ?, ?)",
                         (a["warehouse_id"], r["item"], a["q"], request_id, ts))
            returned += a["q"]
        # Keep the allocation history but record that the units came back.
        conn.execute("DELETE FROM allocations WHERE request_id = ?", (request_id,))
        conn.execute("UPDATE requests SET cancelled = 1, status = 'cancelled', allocated = 0 WHERE id = ?",
                     (request_id,))
        _event(conn, "cancel", f"Cancelled {request_id} ({r['shelter_name']}); {returned:,} {r['item'].lower()} returned to stock",
               {"request_id": request_id, "returned": returned})
        run_id, decisions = run_allocation(conn, f"cancelled {request_id}")
    return {"id": request_id, "returned": returned, "requests_served": sum(1 for d in decisions if d.given > 0)}


def restock(warehouse_id, item, quantity, unit=None, source=None, reference=None):
    """Record a delivery that has physically arrived at a warehouse (goods received)."""
    source = re.sub(r"\s+", " ", source or "").strip()[:80] or None
    reference = re.sub(r"\s+", " ", reference or "").strip()[:40] or None
    with transaction() as conn:
        wh = conn.execute("SELECT id, name FROM warehouses WHERE id = ?", (warehouse_id,)).fetchone()
        if not wh:
            raise ValueError(f"Warehouse {warehouse_id} doesn't exist.")
        item = _canonical_item(conn, item)
        quantity = _whole(quantity, "Quantity")
        existing_unit = conn.execute("SELECT unit FROM inventory WHERE item = ? LIMIT 1", (item,)).fetchone()
        unit = existing_unit["unit"] if existing_unit else ((unit or "units").strip().lower() or "units")
        snapshot(conn, f"delivery of {quantity:,} {item.lower()}")
        ts = now()
        conn.execute("INSERT INTO inventory (warehouse_id, item, quantity, unit) VALUES (?, ?, ?, ?) "
                     "ON CONFLICT(warehouse_id, item) DO UPDATE SET quantity = quantity + excluded.quantity",
                     (warehouse_id, item, quantity, unit))
        conn.execute("INSERT INTO movements (warehouse_id, item, delta, reason, ref, created_at) "
                     "VALUES (?, ?, ?, 'delivery received', ?, ?)",
                     (warehouse_id, item, quantity, " · ".join(x for x in (source, reference) if x) or None, ts))
        extra = "".join([f" from {source}" if source else "", f" (ref {reference})" if reference else ""])
        _event(conn, "restock", f"{quantity:,} {item.lower()} received at {wh['name']}{extra}",
               {"warehouse_id": warehouse_id, "item": item, "quantity": quantity, "source": source, "reference": reference})
        run_id, decisions = run_allocation(conn, f"delivery of {item}")
    served = [d for d in decisions if d.given > 0]
    return {"item": item, "quantity": quantity, "requests_served": len(served),
            "fully": sum(1 for d in served if d.status == "fulfilled"), "run_id": run_id}


def _people(value):
    if value is None or value == "":
        return None
    return _whole(value, "Headcount", minimum=0)


def add_shelter(shelter_id, name, priority=2, lat=None, lon=None, people=None):
    shelter_id = (shelter_id or "").strip()
    name = re.sub(r"\s+", " ", name or "").strip()
    if not shelter_id or not name:
        raise ValueError("A shelter needs an ID and a name.")
    priority = _whole(priority, "Priority")
    people = _people(people)
    for v, lo, hi, label in ((lat, -90, 90, "Latitude"), (lon, -180, 180, "Longitude")):
        if v is not None and not lo <= float(v) <= hi:
            raise ValueError(f"{label} must be between {lo} and {hi}.")
    with transaction() as conn:
        if conn.execute("SELECT 1 FROM shelters WHERE id = ?", (shelter_id,)).fetchone():
            raise ValueError(f"Shelter {shelter_id} already exists.")
        snapshot(conn, f"add shelter {name}")
        conn.execute("INSERT INTO shelters (id, name, priority, lat, lon, people) VALUES (?, ?, ?, ?, ?, ?)",
                     (shelter_id, name, priority, lat, lon, people))
        _event(conn, "shelter", f"Added shelter {name} ({shelter_id}), priority {priority}"
               + (f", {people:,} people" if people is not None else ""))
    return {"id": shelter_id, "name": name}


def update_shelter(shelter_id, people=None, priority=None, clear_people=False):
    """Headcounts change every day; priority can change too (e.g. a clinic opens on site)."""
    with transaction() as conn:
        s = conn.execute("SELECT * FROM shelters WHERE id = ?", (shelter_id,)).fetchone()
        if not s:
            raise NotFound(f"Shelter {shelter_id} doesn't exist.")
        new_people = None if clear_people else (s["people"] if people is None else _people(people))
        new_priority = s["priority"] if priority is None else _whole(priority, "Priority")
        if new_people == s["people"] and new_priority == s["priority"]:
            raise ValueError("Nothing changed.")
        snapshot(conn, f"update {s['name']}")
        conn.execute("UPDATE shelters SET people = ?, priority = ? WHERE id = ?", (new_people, new_priority, shelter_id))
        changes = []
        if new_people != s["people"]:
            before = f"{s['people']:,}" if s["people"] is not None else "unknown"
            after = f"{new_people:,}" if new_people is not None else "unknown"
            changes.append(f"headcount {before} → {after}")
        if new_priority != s["priority"]:
            changes.append(f"priority {s['priority']} → {new_priority}")
        _event(conn, "shelter", f"{s['name']}: {', '.join(changes)}", {"shelter_id": shelter_id})
        run_id, decisions = run_allocation(conn, f"{s['name']} updated")
    return {"id": shelter_id, "people": new_people, "priority": new_priority,
            "requests_served": sum(1 for d in decisions if d.given > 0)}


def add_warehouse(warehouse_id, name, lat=None, lon=None):
    warehouse_id = (warehouse_id or "").strip()
    name = re.sub(r"\s+", " ", name or "").strip()
    if not warehouse_id or not name:
        raise ValueError("A warehouse needs an ID and a name.")
    with transaction() as conn:
        if conn.execute("SELECT 1 FROM warehouses WHERE id = ?", (warehouse_id,)).fetchone():
            raise ValueError(f"Warehouse {warehouse_id} already exists.")
        snapshot(conn, f"add warehouse {name}")
        conn.execute("INSERT INTO warehouses (id, name, lat, lon) VALUES (?, ?, ?, ?)",
                     (warehouse_id, name, lat, lon))
        _event(conn, "warehouse", f"Added warehouse {name} ({warehouse_id})")
    return {"id": warehouse_id, "name": name}


def save_rules(new_rules):
    with transaction() as conn:
        current = load_rules(conn)
        rules = clean_rules({**current, **(new_rules or {})})
        if rules == current:
            return {"rules": rules, "requests_served": 0, "released": 0}
        snapshot(conn, "change rules")
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('rules', ?)", (json.dumps(rules),))
        changed = ", ".join(f"{k.replace('_', ' ')} → {v}" for k, v in rules.items() if current.get(k) != v)
        _event(conn, "rules", f"Rules changed: {changed}")
        released = _rebalance(conn, rules)
        run_id, decisions = run_allocation(conn, "rules changed")
    return {"rules": rules, "requests_served": sum(1 for d in decisions if d.given > 0), "released": released}


def _rebalance(conn, rules):
    """When a shelter cap is switched on, stock already reserved above the cap (still in the warehouse, not on
    a truck) goes back on the shelf so others can have it. Loads on a truck or delivered are never touched."""
    from .allocation import load_state

    unit_cap = rules.get("max_per_shelter_per_item", 0)
    days = rules.get("max_days_per_shelter", 0)
    if not unit_cap and not days:
        return 0
    reqs, _, _, _, _ = load_state(conn)
    limits, given = {}, {}
    for r in reqs:
        key = (r["shelter_id"], r["item"])
        given[key] = given.get(key, 0) + r["allocated"]
        caps = [unit_cap] if unit_cap else []
        if days and r.get("daily_need"):
            caps.append(-(-int(round(r["daily_need"] * days * 1000)) // 1000))
        if caps:
            limits[key] = min(caps)
    names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM shelters")}
    ts, total = now(), 0
    for key, limit in sorted(limits.items()):
        excess = given.get(key, 0) - limit
        if excess <= 0:
            continue
        rows = conn.execute(
            """SELECT a.id, a.request_id, a.warehouse_id, a.quantity, r.urgency, r.created_at
               FROM allocations a JOIN requests r ON r.id = a.request_id
               WHERE r.shelter_id = ? AND a.item = ? AND a.status = 'allocated' AND r.cancelled = 0""", key).fetchall()
        # Least urgent, newest first.
        rows = sorted(rows, key=lambda a: (URGENCY_LEVELS.index(a["urgency"]), a["created_at"], a["id"]), reverse=True)
        freed = 0
        for a in rows:
            if excess == 0:
                break
            take = min(excess, a["quantity"])
            if take == a["quantity"]:
                conn.execute("DELETE FROM allocations WHERE id = ?", (a["id"],))
            else:
                conn.execute("UPDATE allocations SET quantity = quantity - ? WHERE id = ?", (take, a["id"]))
            conn.execute("UPDATE inventory SET quantity = quantity + ? WHERE warehouse_id = ? AND item = ?",
                         (take, a["warehouse_id"], key[1]))
            conn.execute("INSERT INTO movements (warehouse_id, item, delta, reason, ref, created_at) "
                         "VALUES (?, ?, ?, 'released by shelter cap', ?, ?)",
                         (a["warehouse_id"], key[1], take, a["request_id"], ts))
            req = conn.execute("SELECT quantity, allocated FROM requests WHERE id = ?", (a["request_id"],)).fetchone()
            allocated = req["allocated"] - take
            conn.execute("UPDATE requests SET allocated = ?, status = ? WHERE id = ?",
                         (allocated, "partial" if allocated > 0 else "unfilled", a["request_id"]))
            excess -= take
            freed += take
        if freed:
            total += freed
            _event(conn, "rules", f"{names.get(key[0], key[0])}: {freed:,} {key[1].lower()} released back to stock "
                                  f"(over the shelter cap, not yet on a truck)", {"shelter_id": key[0], "item": key[1]})
    return total


def allocate_now():
    with transaction() as conn:
        snapshot(conn, "manual allocation run")
        run_id, decisions = run_allocation(conn, "manual run")
    return {"run_id": run_id, "requests_served": sum(1 for d in decisions if d.given > 0)}


def update_request(request_id, quantity=None, urgency=None):
    """A shelter calls back: change how many it needs, or how urgent it is.

    You can't go below what's already on a truck or delivered. If the new quantity is below what's
    reserved in the warehouse, the extra goes back on the shelf and is re-allocated to others.
    """
    with transaction() as conn:
        r = conn.execute("SELECT r.*, s.name AS shelter_name FROM requests r JOIN shelters s ON s.id = r.shelter_id "
                         "WHERE r.id = ?", (request_id,)).fetchone()
        if not r:
            raise NotFound(f"Request {request_id} doesn't exist.")
        if r["cancelled"]:
            raise ValueError(f"{request_id} is cancelled.")
        new_qty = r["quantity"] if quantity is None else _whole(quantity, "Quantity")
        new_urg = r["urgency"]
        if urgency is not None:
            new_urg, ok = normalize_urgency(urgency)
            if not ok:
                raise ValueError(f"Urgency must be one of: {', '.join(l.title() for l in URGENCY_LEVELS)}.")
        if new_qty == r["quantity"] and new_urg == r["urgency"]:
            raise ValueError("Nothing changed.")
        moved = conn.execute("SELECT COALESCE(SUM(quantity), 0) AS u FROM allocations WHERE request_id = ? "
                             "AND status != 'allocated'", (request_id,)).fetchone()["u"]
        if new_qty < moved:
            raise ValueError(f"{moved:,} units are already on a truck or delivered, so the quantity can't go below {moved:,}.")
        snapshot(conn, f"change {request_id}")
        ts = now()
        released = 0
        excess = r["allocated"] - new_qty
        if excess > 0:
            for a in conn.execute("SELECT id, warehouse_id, quantity FROM allocations WHERE request_id = ? "
                                  "AND status = 'allocated' ORDER BY id DESC", (request_id,)).fetchall():
                if excess == 0:
                    break
                take = min(excess, a["quantity"])
                if take == a["quantity"]:
                    conn.execute("DELETE FROM allocations WHERE id = ?", (a["id"],))
                else:
                    conn.execute("UPDATE allocations SET quantity = quantity - ? WHERE id = ?", (take, a["id"]))
                conn.execute("UPDATE inventory SET quantity = quantity + ? WHERE warehouse_id = ? AND item = ?",
                             (take, a["warehouse_id"], r["item"]))
                conn.execute("INSERT INTO movements (warehouse_id, item, delta, reason, ref, created_at) "
                             "VALUES (?, ?, ?, 'request reduced', ?, ?)", (a["warehouse_id"], r["item"], take, request_id, ts))
                excess -= take
                released += take
        allocated = r["allocated"] - released
        status = "fulfilled" if allocated >= new_qty else "partial" if allocated > 0 else "unfilled"
        conn.execute("UPDATE requests SET quantity = ?, urgency = ?, allocated = ?, status = ? WHERE id = ?",
                     (new_qty, new_urg, allocated, status, request_id))
        changes = []
        if new_qty != r["quantity"]:
            changes.append(f"quantity {r['quantity']:,} → {new_qty:,}")
        if new_urg != r["urgency"]:
            changes.append(f"urgency {r['urgency']} → {new_urg}")
        _event(conn, "request", f"Changed {request_id} ({r['shelter_name']}): {', '.join(changes)}"
               + (f"; {released:,} returned to stock" if released else ""), {"request_id": request_id})
        run_id, decisions = run_allocation(conn, f"changed {request_id}")
    mine = next((d for d in decisions if d.request_id == request_id), None)
    return {"id": request_id, "quantity": new_qty, "urgency": new_urg, "released": released,
            "allocated": mine.total if mine else allocated,
            "requests_served": sum(1 for d in decisions if d.given > 0 and d.request_id != request_id)}
