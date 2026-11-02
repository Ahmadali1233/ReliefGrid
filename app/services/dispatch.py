"""Dispatch: waybills, trucks and proof of delivery, the way aid logistics and parcel carriers do it.

  reserved     stock is allocated to a shelter but still on the warehouse shelf
  waybill      "Print waybill" puts everything reserved for one route (warehouse -> shelter) on a numbered
               waybill, e.g. WB-1031-007. The number is the tracking number; the QR on the printed slip lets
               the driver and the shelter confirm from a phone.
  on the way   the truck left; the driver is recorded. Only what was on the waybill goes.
  delivered    the shelter counted what arrived and signed. Anything missing or damaged is recorded as a loss
               and that request goes straight back in the queue, so the shelter still gets it.

Allocation rows carry the stage (allocated -> dispatched -> delivered) and the waybill they travel on.
"""

import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timedelta

from ..db.database import get_conn, now, transaction
from ..engine import sort_key
from .history import snapshot

SPEED_KMH = 40          # city driving, door to door
ROAD_FACTOR = 1.3       # roads are longer than a straight line


def drive_minutes(km):
    return round(km * ROAD_FACTOR / SPEED_KMH * 60) if km is not None else None


# ---------- Waybill numbers and phone codes ----------

def _key(conn, name, make):
    row = conn.execute("SELECT value FROM keys WHERE name = ?", (name,)).fetchone()
    if row:
        return row["value"]
    conn.execute("INSERT OR IGNORE INTO keys (name, value) VALUES (?, ?)", (name, make()))
    return conn.execute("SELECT value FROM keys WHERE name = ?", (name,)).fetchone()["value"]


def _next_number(conn):
    """WB-MMDD-NNN. The counter lives outside Undo and resets, so a number is never given out twice."""
    day = datetime.now().strftime("%m%d")
    name = f"waybill-{day}"
    seq = int(_key(conn, name, lambda: "0")) + 1
    while conn.execute("SELECT 1 FROM shipments WHERE id = ?", (f"WB-{day}-{seq:03d}",)).fetchone():
        seq += 1
    conn.execute("UPDATE keys SET value = ? WHERE name = ?", (str(seq), name))
    return f"WB-{day}-{seq:03d}"


def token(waybill, conn=None):
    """The code in a waybill's QR. Only someone holding the slip can confirm that load from a phone."""
    key = _key(conn or get_conn(), "handoff", lambda: secrets.token_hex(16))
    return hmac.new(key.encode(), waybill.encode(), hashlib.sha256).hexdigest()[:16]


def check_token(waybill, value):
    if not value or not hmac.compare_digest(token(waybill), str(value)):
        raise PermissionError("This link isn't valid for that waybill. Scan the QR code on the printed slip again.")


def _clean_name(value, what):
    name = re.sub(r"\s+", " ", value or "").strip()
    if not name:
        raise ValueError(f"Enter the {what}.")
    if len(name) > 60:
        raise ValueError(f"The {what} is too long (60 characters at most).")
    return name


def _units(conn):
    return {r["item"]: r["unit"] for r in conn.execute("SELECT item, MIN(unit) AS unit FROM inventory GROUP BY item")}


def _units_text(conn, by_item):
    units = _units(conn)
    parts = []
    for item, q in sorted(by_item.items()):
        unit = (units.get(item) or "").lower()
        parts.append(f"{q:,} {item.lower()}" if not unit or unit == "units" or unit in item.lower()
                     else f"{q:,} {unit} of {item.lower()}")
    return ", ".join(parts)


def prune(conn):
    """Remove waybills that are still loading but no longer carry anything (e.g. the request was cancelled)."""
    conn.execute("DELETE FROM shipments WHERE status = 'loading' AND id NOT IN "
                 "(SELECT DISTINCT shipment_id FROM allocations WHERE shipment_id IS NOT NULL)")


def create_shipment(conn, warehouse_id, shelter_id, alloc_ids, ts=None):
    """Put allocation rows on a new waybill (inside an open transaction). Returns the waybill number."""
    number = _next_number(conn)
    conn.execute("INSERT INTO shipments (id, warehouse_id, shelter_id, status, created_at) VALUES (?, ?, ?, 'loading', ?)",
                 (number, warehouse_id, shelter_id, ts or now()))
    marks = ",".join("?" for _ in alloc_ids)
    conn.execute(f"UPDATE allocations SET shipment_id = ? WHERE id IN ({marks})", [number, *alloc_ids])
    return number


def backfill(conn):
    """Databases from before waybills: give every load that already left a warehouse a waybill number."""
    groups = conn.execute("""SELECT a.warehouse_id, r.shelter_id, a.status, a.dispatched_at, MAX(a.dispatched_by) AS driver,
                                    MAX(a.delivered_at) AS delivered_at, MAX(a.received_by) AS received_by,
                                    GROUP_CONCAT(a.id) AS ids
                             FROM allocations a JOIN requests r ON r.id = a.request_id
                             WHERE a.status IN ('dispatched', 'delivered') AND a.shipment_id IS NULL
                             GROUP BY a.warehouse_id, r.shelter_id, a.status, a.dispatched_at""").fetchall()
    for g in groups:
        number = create_shipment(conn, g["warehouse_id"], g["shelter_id"], [int(i) for i in g["ids"].split(",")],
                                 g["dispatched_at"])
        conn.execute("UPDATE shipments SET status = ?, dispatched_at = ?, driver = ?, delivered_at = ?, received_by = ? "
                     "WHERE id = ?", ("delivered" if g["status"] == "delivered" else "on_the_way", g["dispatched_at"],
                                      g["driver"], g["delivered_at"], g["received_by"], number))
    return len(groups)


# ---------- Reading ----------

def _route_rows(conn, warehouse_id, shelter_id, status="allocated"):
    return [dict(r) for r in conn.execute(
        """SELECT a.*, r.urgency, r.created_at AS request_created_at, s.priority AS shelter_priority
           FROM allocations a JOIN requests r ON r.id = a.request_id JOIN shelters s ON s.id = r.shelter_id
           WHERE a.warehouse_id = ? AND r.shelter_id = ? AND a.status = ? ORDER BY a.id""",
        (warehouse_id, shelter_id, status))]


def _items(rows, units):
    by = {}
    for r in rows:
        by[r["item"]] = by.get(r["item"], 0) + r["quantity"]
    return [{"item": i, "quantity": q, "unit": units.get(i)} for i, q in sorted(by.items())]


def loads(status=None):
    """To load: one card per route with everything reserved on it (and its waybill, if printed).
    On the way / delivered: one per waybill."""
    conn = get_conn()
    units = _units(conn)
    places = conn.execute("""SELECT w.id AS wid, w.name AS wname, s.id AS sid, s.name AS sname, s.priority, s.lat, s.lon,
                                    s.people FROM warehouses w, shelters s""").fetchall()
    place = {(p["wid"], p["sid"]): dict(p) for p in places}
    rows = [dict(r) for r in conn.execute(
        """SELECT a.*, r.shelter_id FROM allocations a JOIN requests r ON r.id = a.request_id ORDER BY a.id""")]
    ships = {s["id"]: dict(s) for s in conn.execute("SELECT * FROM shipments")}
    losses = {}
    for l in conn.execute("SELECT shipment_id, item, SUM(quantity) AS q, MAX(note) AS note FROM losses "
                          "WHERE shipment_id IS NOT NULL GROUP BY shipment_id, item"):
        losses.setdefault(l["shipment_id"], []).append({"item": l["item"], "quantity": l["q"], "note": l["note"]})

    def base(wid, sid):
        p = place.get((wid, sid), {})
        return {"warehouse_id": wid, "warehouse_name": p.get("wname", wid), "shelter_id": sid,
                "shelter_name": p.get("sname", sid), "priority": p.get("priority"), "lat": p.get("lat"),
                "lon": p.get("lon"), "people": p.get("people")}

    out = []
    if status in (None, "allocated"):
        routes = {}
        for r in rows:
            if r["status"] == "allocated":
                routes.setdefault((r["warehouse_id"], r["shelter_id"]), []).append(r)
        for (wid, sid), rs in routes.items():
            on_bill = [r for r in rs if r["shipment_id"]]
            waybill = on_bill[0]["shipment_id"] if on_bill else None
            g = {**base(wid, sid), "status": "allocated", "waybill": waybill,
                 "items": _items(rs, units), "total": sum(r["quantity"] for r in rs),
                 "on_waybill": sum(r["quantity"] for r in on_bill),
                 "requests": sorted({r["request_id"] for r in rs}), "max_id": max(r["id"] for r in rs),
                 "allocated_at": max(r["created_at"] for r in rs),
                 "distance_km": min((r["distance_km"] for r in rs if r["distance_km"] is not None), default=None),
                 "token": token(waybill, conn) if waybill else None,
                 "printed_at": ships[waybill]["created_at"] if waybill in ships else None}
            g["off_waybill"] = g["total"] - g["on_waybill"]
            out.append(g)
    for sid_, s in ships.items():
        st = {"on_the_way": "dispatched", "delivered": "delivered"}.get(s["status"])
        if not st or (status and status != st):
            continue
        rs = [r for r in rows if r["shipment_id"] == sid_ and r["status"] == st]
        g = {**base(s["warehouse_id"], s["shelter_id"]), "status": st, "waybill": sid_,
             "items": _items(rs, units), "total": sum(r["quantity"] for r in rs),
             "requests": sorted({r["request_id"] for r in rs}), "max_id": max((r["id"] for r in rs), default=0),
             "distance_km": min((r["distance_km"] for r in rs if r["distance_km"] is not None), default=None),
             "allocated_at": s["created_at"], "dispatched_at": s["dispatched_at"], "dispatched_by": s["driver"],
             "delivered_at": s["delivered_at"], "received_by": s["received_by"], "note": s["note"],
             "lost": losses.get(sid_, []), "token": token(sid_, conn) if st == "dispatched" else None}
        out.append(g)
    for g in out:
        g["drive_minutes"] = drive_minutes(g["distance_km"])
        if g["status"] == "dispatched" and g["drive_minutes"] is not None and g["dispatched_at"]:
            g["eta"] = (datetime.fromisoformat(g["dispatched_at"]) + timedelta(minutes=g["drive_minutes"])).isoformat(timespec="minutes")
    out.sort(key=lambda g: (g["priority"] or 99, g["shelter_name"], g["warehouse_id"], g.get("waybill") or ""))
    return out


def counts():
    conn = get_conn()
    rows = {r["status"]: r for r in conn.execute(
        """SELECT a.status, COUNT(DISTINCT CASE WHEN a.status = 'allocated' THEN a.warehouse_id || '|' || r.shelter_id
                                               ELSE a.shipment_id END) AS loads, SUM(a.quantity) AS units
           FROM allocations a JOIN requests r ON r.id = a.request_id GROUP BY a.status""")}
    return {s: {"loads": rows[s]["loads"] if s in rows else 0, "units": rows[s]["units"] if s in rows else 0}
            for s in ("allocated", "dispatched", "delivered")}


# ---------- Changing ----------

def print_waybill(warehouse_id, shelter_id):
    """Put everything reserved on a route onto its waybill (new, or the one already being loaded)."""
    with transaction() as conn:
        rows = _route_rows(conn, warehouse_id, shelter_id)
        if not rows:
            raise ValueError("Nothing is reserved on that route.")
        existing = next((r["shipment_id"] for r in rows if r["shipment_id"]), None)
        loose = [r["id"] for r in rows if not r["shipment_id"]]
        if existing and not loose:
            return {"waybill": existing, "token": token(existing, conn), "added": 0}
        snapshot(conn, f"waybill for {shelter_id}")
        if existing:
            marks = ",".join("?" for _ in loose)
            conn.execute(f"UPDATE allocations SET shipment_id = ? WHERE id IN ({marks})", [existing, *loose])
            number = existing
        else:
            number = create_shipment(conn, warehouse_id, shelter_id, loose)
        name = conn.execute("SELECT name FROM shelters WHERE id = ?", (shelter_id,)).fetchone()["name"]
        conn.execute("INSERT INTO events (created_at, kind, message, data) VALUES (?, 'waybill', ?, ?)",
                     (now(), f"{number} {'updated' if existing else 'printed'} for {name}: "
                             f"{_units_text(conn, {i['item']: i['quantity'] for i in _items(rows, {})})}",
                      json.dumps({"waybill": number, "shelter_id": shelter_id})))
    return {"waybill": number, "token": token(number), "added": len(loose)}


def _shipment(conn, waybill):
    s = conn.execute("SELECT * FROM shipments WHERE id = ?", ((waybill or "").strip().upper(),)).fetchone()
    if not s:
        raise ValueError(f"There's no waybill {waybill}.")
    return dict(s)


def mark_dispatched(warehouse_id=None, shelter_id=None, driver="", upto_id=None, waybill=None):
    """The truck left. With a waybill, only what's on it goes (and with upto_id, only what the driver was shown).
    With just a route, a waybill is made for everything reserved on it first."""
    driver = _clean_name(driver, "driver or vehicle")
    with transaction() as conn:
        if waybill:
            s = _shipment(conn, waybill)
            if s["status"] != "loading":
                raise ValueError(f"{s['id']} has already left the warehouse.")
            warehouse_id, shelter_id = s["warehouse_id"], s["shelter_id"]
        names = conn.execute("SELECT (SELECT name FROM warehouses WHERE id = ?) AS w, (SELECT name FROM shelters "
                             "WHERE id = ?) AS s", (warehouse_id, shelter_id)).fetchone()
        if not names["w"] or not names["s"]:
            raise ValueError("That warehouse or shelter doesn't exist.")
        rows = _route_rows(conn, warehouse_id, shelter_id)
        if waybill:
            rows = [r for r in rows if r["shipment_id"] == s["id"]]
        if upto_id is not None:
            later = [r["id"] for r in rows if r["id"] > int(upto_id)]
            rows = [r for r in rows if r["id"] <= int(upto_id)]
        else:
            later = []
        if not rows:
            raise ValueError(f"Nothing is waiting to be loaded at {names['w']} for {names['s']}.")
        snapshot(conn, f"dispatch to {names['s']}")
        ts = now()
        if later:   # reserved after the driver looked: waits for the next truck
            marks = ",".join("?" for _ in later)
            conn.execute(f"UPDATE allocations SET shipment_id = NULL WHERE id IN ({marks})", later)
        if waybill:
            number = s["id"]
        else:
            existing = next((r["shipment_id"] for r in rows if r["shipment_id"]), None)
            number = existing or create_shipment(conn, warehouse_id, shelter_id, [r["id"] for r in rows], ts)
            loose = [r["id"] for r in rows if r["shipment_id"] != number]
            if loose:
                marks = ",".join("?" for _ in loose)
                conn.execute(f"UPDATE allocations SET shipment_id = ? WHERE id IN ({marks})", [number, *loose])
        ids = [r["id"] for r in rows]
        marks = ",".join("?" for _ in ids)
        conn.execute(f"UPDATE allocations SET status = 'dispatched', dispatched_at = ?, dispatched_by = ? "
                     f"WHERE id IN ({marks})", [ts, driver, *ids])
        conn.execute("UPDATE shipments SET status = 'on_the_way', dispatched_at = ?, driver = ? WHERE id = ?",
                     (ts, driver, number))
        by_item = {}
        for r in rows:
            by_item[r["item"]] = by_item.get(r["item"], 0) + r["quantity"]
        units = sum(by_item.values())
        conn.execute("INSERT INTO events (created_at, kind, message, data) VALUES (?, 'dispatch', ?, ?)",
                     (ts, f"{number} left {names['w']} for {names['s']} with {driver}: {_units_text(conn, by_item)}",
                      json.dumps({"waybill": number, "warehouse_id": warehouse_id, "shelter_id": shelter_id,
                                  "units": units})))
        prune(conn)
    return {"waybill": number, "units": units, "shelter": names["s"], "warehouse": names["w"], "driver": driver}


def confirm_delivered(waybill=None, received_by="", received=None, note=None, warehouse_id=None, shelter_id=None):
    """The shelter counted the load and signed.

    received: optional {item: units that actually arrived}. Anything missing or damaged is recorded as a loss
    (with the note), taken off the least urgent request first, and that request goes back in the queue so the
    shelter still gets it from stock. Without a waybill, every truck on its way on that route is signed for.
    """
    received_by = _clean_name(received_by, "name of the person who received it")
    if not waybill:
        conn = get_conn()
        bills = [r["id"] for r in conn.execute("SELECT id FROM shipments WHERE status = 'on_the_way' AND warehouse_id = ? "
                                               "AND shelter_id = ? ORDER BY id", (warehouse_id, shelter_id))]
        if not bills:
            raise ValueError("Nothing is on its way on that route.")
        if received and len(bills) > 1:
            raise ValueError("More than one truck is on that route. Give the waybill number with the counts.")
        results = [confirm_delivered(b, received_by, received, note) for b in bills]
        return {**results[-1], "units": sum(r["units"] for r in results), "waybills": bills}

    from .allocation import run_allocation
    note = re.sub(r"\s+", " ", note or "").strip()[:200] or None
    with transaction() as conn:
        s = _shipment(conn, waybill)
        if s["status"] == "delivered":
            raise ValueError(f"{s['id']} was already signed for by {s['received_by']}.")
        if s["status"] != "on_the_way":
            raise ValueError(f"{s['id']} hasn't left the warehouse yet.")
        w_name = conn.execute("SELECT name FROM warehouses WHERE id = ?", (s["warehouse_id"],)).fetchone()["name"]
        s_name = conn.execute("SELECT name FROM shelters WHERE id = ?", (s["shelter_id"],)).fetchone()["name"]
        rows = [dict(r) for r in conn.execute(
            """SELECT a.*, r.urgency, r.created_at AS request_created_at, sh.priority AS shelter_priority
               FROM allocations a JOIN requests r ON r.id = a.request_id JOIN shelters sh ON sh.id = r.shelter_id
               WHERE a.shipment_id = ? AND a.status = 'dispatched' ORDER BY a.id""", (s["id"],))]
        sent = {}
        for r in rows:
            sent[r["item"]] = sent.get(r["item"], 0) + r["quantity"]
        short = {}
        for item, value in (received or {}).items():
            match = next((i for i in sent if i.lower() == str(item).strip().lower()), None)
            if match is None:
                raise ValueError(f"{item} isn't on {s['id']}.")
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"The count for {match} must be a whole number.")
            if value < 0 or value > sent[match]:
                raise ValueError(f"{match}: {sent[match]:,} were sent, so the count must be between 0 and {sent[match]:,}.")
            if value < sent[match]:
                short[match] = sent[match] - value
        if short and not note:
            raise ValueError("Say what happened to the missing units (for example: 2 cartons crushed).")
        snapshot(conn, f"delivery of {s['id']}")
        ts = now()
        requeued = []
        for item, missing in short.items():
            mine = sorted((r for r in rows if r["item"] == item),     # least urgent request carries the loss
                          key=lambda r: sort_key({"urgency": r["urgency"], "shelter_priority": r["shelter_priority"],
                                                  "created_at": r["request_created_at"], "id": r["request_id"]}),
                          reverse=True)
            for r in mine:
                if missing == 0:
                    break
                take = min(missing, r["quantity"])
                if take == r["quantity"]:
                    conn.execute("DELETE FROM allocations WHERE id = ?", (r["id"],))
                else:
                    conn.execute("UPDATE allocations SET quantity = quantity - ? WHERE id = ?", (take, r["id"]))
                req = conn.execute("SELECT quantity, allocated FROM requests WHERE id = ?", (r["request_id"],)).fetchone()
                allocated = req["allocated"] - take
                conn.execute("UPDATE requests SET allocated = ?, status = ? WHERE id = ?",
                             (allocated, "fulfilled" if allocated >= req["quantity"] else "partial" if allocated else "unfilled",
                              r["request_id"]))
                conn.execute("INSERT INTO losses (request_id, warehouse_id, shelter_id, item, quantity, note, reported_by, "
                             "created_at, shipment_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                             (r["request_id"], s["warehouse_id"], s["shelter_id"], item, take, note, received_by, ts, s["id"]))
                requeued.append({"request_id": r["request_id"], "item": item, "quantity": take})
                missing -= take
        conn.execute("UPDATE allocations SET status = 'delivered', delivered_at = ?, received_by = ?, note = ? "
                     "WHERE shipment_id = ? AND status = 'dispatched'", (ts, received_by, note, s["id"]))
        conn.execute("UPDATE shipments SET status = 'delivered', delivered_at = ?, received_by = ?, note = ? WHERE id = ?",
                     (ts, received_by, note, s["id"]))
        got = {item: q - short.get(item, 0) for item, q in sent.items()}
        units, lost = sum(got.values()), sum(short.values())
        msg = (f"{s['id']} delivered to {s_name}, signed by {received_by}: "
               f"{_units_text(conn, {k: v for k, v in got.items() if v}) or 'nothing usable'}")
        if lost:
            msg += f". Missing or damaged: {_units_text(conn, short)} ({note}); back in the queue"
        conn.execute("INSERT INTO events (created_at, kind, message, data) VALUES (?, 'delivered', ?, ?)",
                     (ts, msg, json.dumps({"waybill": s["id"], "shelter_id": s["shelter_id"], "units": units,
                                           "lost": lost, "requeued": requeued})))
        served = 0
        if requeued:
            _, decisions = run_allocation(conn, f"short delivery on {s['id']}")
            served = sum(1 for d in decisions if d.given > 0)
    return {"waybill": s["id"], "units": units, "lost": lost, "requeued": requeued, "shelter": s_name,
            "received_by": received_by, "requests_served": served}


# ---------- Phone and tracking ----------

def handoff(waybill, value):
    """What a phone that scanned a waybill's QR shows."""
    check_token(waybill, value)
    conn = get_conn()
    s = _shipment(conn, waybill)
    stage = {"loading": "to_load", "on_the_way": "on_the_way", "delivered": "delivered"}[s["status"]]
    wh = dict(conn.execute("SELECT id, name FROM warehouses WHERE id = ?", (s["warehouse_id"],)).fetchone())
    sh = dict(conn.execute("SELECT id, name, people, priority FROM shelters WHERE id = ?", (s["shelter_id"],)).fetchone())
    mine = [g for g in loads() if g.get("waybill") == s["id"]]
    load = mine[0] if mine else None
    if load and stage == "to_load":       # only what's on the waybill goes on this truck
        rows = [dict(r) for r in conn.execute("SELECT id, item, quantity FROM allocations WHERE shipment_id = ? "
                                              "AND status = 'allocated'", (s["id"],))]
        load = {**load, "items": _items(rows, _units(conn)), "total": sum(r["quantity"] for r in rows),
                "max_id": max((r["id"] for r in rows), default=0)}
    return {"waybill": s["id"], "stage": stage, "warehouse": wh, "shelter": sh, "load": load,
            "driver": s["driver"], "dispatched_at": s["dispatched_at"], "received_by": s["received_by"],
            "delivered_at": s["delivered_at"]}
