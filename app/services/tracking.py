"""Track a waybill or a request like a parcel: where is it, what happened, when will it arrive.

Shelters and donors can check for themselves (no phone calls to the hub), and coordinators get one place to
answer "where's our water?". Read-only: confirming a pick-up or a delivery needs the QR code on the slip.
"""

from datetime import datetime

from ..db.database import get_conn
from .allocation import preview
from .dispatch import _items, _units, drive_minutes, loads


def _amount(q, unit, item):
    unit = (unit or "").lower()
    item = item.lower()
    return f"{q:,} {item}" if not unit or unit == "units" or unit in item else f"{q:,} {unit} of {item}"


def _clock(iso):
    try:
        d = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return ""
    return d.strftime("%H:%M") if d.date() == datetime.now().date() else d.strftime("%d %b, %H:%M")


def _ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def track(code):
    code = (code or "").strip().upper()
    if not code:
        raise ValueError("Enter a waybill number (like WB-1031-007) or a request number (like REQ-012).")
    conn = get_conn()
    if conn.execute("SELECT 1 FROM shipments WHERE id = ?", (code,)).fetchone():
        return _waybill(conn, code)
    rid = conn.execute("SELECT id FROM requests WHERE upper(id) = ?", (code,)).fetchone()
    if rid:
        return _request(conn, rid["id"])
    raise LookupError(f"No waybill or request called {code}. Check the number on the slip or message.")


def _waybill(conn, number):
    s = dict(conn.execute("SELECT * FROM shipments WHERE id = ?", (number,)).fetchone())
    units = _units(conn)
    sh = dict(conn.execute("SELECT id, name, people FROM shelters WHERE id = ?", (s["shelter_id"],)).fetchone())
    wh = dict(conn.execute("SELECT id, name FROM warehouses WHERE id = ?", (s["warehouse_id"],)).fetchone())
    rows = [dict(r) for r in conn.execute("SELECT * FROM allocations WHERE shipment_id = ? ORDER BY id", (number,))]
    lost = [dict(r) for r in conn.execute("SELECT item, quantity, note FROM losses WHERE shipment_id = ?", (number,))]
    km = min((r["distance_km"] for r in rows if r["distance_km"] is not None), default=None)
    eta = None
    if s["status"] == "on_the_way" and s["dispatched_at"] and km is not None:
        g = next((g for g in loads("dispatched") if g.get("waybill") == number), None)
        eta = g.get("eta") if g else None
    reserved_at = min((r["created_at"] for r in rows), default=s["created_at"])
    lost_text = ", ".join(f"{_amount(l['quantity'], units.get(l['item']), l['item'])} ({l['note']})" for l in lost)
    steps = [
        {"label": "Stock reserved", "done": True, "at": reserved_at,
         "detail": f"For {', '.join(sorted({r['request_id'] for r in rows}))}" if rows else ""},
        {"label": "Waybill printed", "done": True, "at": s["created_at"], "detail": f"At {wh['name']}"},
        {"label": "Left the warehouse", "done": s["status"] in ("on_the_way", "delivered"), "at": s["dispatched_at"],
         "detail": f"With {s['driver']}" if s["driver"] else ""},
        {"label": "Delivered", "done": s["status"] == "delivered", "at": s["delivered_at"],
         "detail": (f"Signed for by {s['received_by']}" + (f". Missing: {lost_text}, back in the queue" if lost else ""))
         if s["status"] == "delivered" else (f"Expected around {_clock(eta)}" if eta else "")},
    ]
    headline = {
        "loading": f"Being loaded at {wh['name']}",
        "on_the_way": f"On the way to {sh['name']}" + (f", arriving around {_clock(eta)}" if eta else ""),
        "delivered": f"Delivered to {sh['name']}, signed for by {s['received_by']}",
    }[s["status"]]
    return {"type": "waybill", "number": number, "status": s["status"], "headline": headline,
            "from": wh, "to": sh, "items": _items(rows, units), "lost": lost, "eta": eta,
            "distance_km": km, "drive_minutes": drive_minutes(km), "steps": steps,
            "requests": sorted({r["request_id"] for r in rows})}


def _request(conn, rid):
    r = dict(conn.execute("""SELECT r.*, s.name AS shelter_name, s.people FROM requests r
                             JOIN shelters s ON s.id = r.shelter_id WHERE r.id = ?""", (rid,)).fetchone())
    units = _units(conn)
    unit = units.get(r["item"])
    amt = lambda q: _amount(q, unit, r["item"])          # noqa: E731
    rows = [dict(a) for a in conn.execute("SELECT * FROM allocations WHERE request_id = ? ORDER BY id", (rid,))]
    ships = {s["id"]: dict(s) for s in conn.execute(
        "SELECT * FROM shipments WHERE id IN (SELECT shipment_id FROM allocations WHERE request_id = ?) "
        "OR id IN (SELECT shipment_id FROM losses WHERE request_id = ?)", (rid, rid))}
    lost = [dict(x) for x in conn.execute("SELECT quantity, note, shipment_id, created_at FROM losses WHERE request_id = ?",
                                          (rid,))]
    reserved = sum(a["quantity"] for a in rows if a["status"] == "allocated")
    on_way = sum(a["quantity"] for a in rows if a["status"] == "dispatched")
    delivered = sum(a["quantity"] for a in rows if a["status"] == "delivered")
    remaining = 0 if r["cancelled"] else r["quantity"] - r["allocated"]
    eta_by_bill = {g["waybill"]: g.get("eta") for g in loads("dispatched")}

    shipments = []
    for number, s in sorted(ships.items()):
        q = sum(a["quantity"] for a in rows if a["shipment_id"] == number)
        shipments.append({"waybill": number, "status": s["status"], "quantity": q, "driver": s["driver"],
                          "dispatched_at": s["dispatched_at"], "delivered_at": s["delivered_at"],
                          "received_by": s["received_by"], "eta": eta_by_bill.get(number)})

    queue = None
    if remaining > 0:
        d = next((d for d in preview(conn) if d.request_id == rid), None)
        if d and d.capped and d.eligible == 0:
            queue = {"held": True, "text": "Held: the shelter already has its share under the current rules."}
        elif d:
            queue = {"held": False, "position": d.rank_in_item, "ahead_units": d.used_ahead + 0,
                     "text": f"{_ordinal(d.rank_in_item)} in line for {r['item'].lower()} when more arrives."}

    first = lambda key, cond=lambda a: True: min((a[key] for a in rows if a[key] and cond(a)), default=None)  # noqa: E731
    steps = [
        {"label": "Requested", "done": True, "at": r["created_at"],
         "detail": f"{amt(r['quantity'])}, {r['urgency']} urgency"},
        {"label": "Stock reserved", "done": r["allocated"] > 0, "at": first("created_at"),
         "detail": f"{r['allocated']:,} of {r['quantity']:,} reserved" if r["allocated"] else (queue or {}).get("text", "")},
        {"label": "On a truck", "done": on_way + delivered > 0, "at": first("dispatched_at"),
         "detail": ", ".join(f"{s['waybill']} with {s['driver']}" for s in shipments if s["dispatched_at"])},
        {"label": "Delivered", "done": delivered > 0, "at": first("delivered_at", lambda a: a["status"] == "delivered"),
         "detail": (f"{delivered:,} of {r['quantity']:,} signed for by "
                    + ", ".join(sorted({a['received_by'] for a in rows if a['status'] == 'delivered' and a['received_by']})))
         if delivered else ""},
    ]
    if r["cancelled"]:
        headline = "Cancelled"
    elif delivered >= r["quantity"]:
        headline = f"Delivered: all {amt(r['quantity'])}"
    elif on_way:
        eta = min((s["eta"] for s in shipments if s["status"] == "on_the_way" and s["eta"]), default=None)
        headline = f"On the way: {amt(on_way)}" + (f", arriving around {_clock(eta)}" if eta else "")
    elif reserved:
        headline = f"Reserved: {amt(reserved)} waiting for a truck"
    elif remaining > 0:
        headline = f"Waiting for stock: {amt(remaining)}" + (f". {queue['text']}" if queue and not queue["held"] else "")
    else:
        headline = f"Delivered: {amt(delivered)}"
    return {"type": "request", "number": rid, "headline": headline, "shelter": {"id": r["shelter_id"],
            "name": r["shelter_name"], "people": r["people"]}, "item": r["item"], "unit": unit,
            "quantity": r["quantity"], "urgency": r["urgency"], "cancelled": bool(r["cancelled"]),
            "reserved": reserved, "on_the_way": on_way, "delivered": delivered, "waiting": max(remaining, 0),
            "lost": lost, "queue": queue, "shipments": shipments, "steps": steps}
