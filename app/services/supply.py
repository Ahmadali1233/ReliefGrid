"""Supply orders: ask HQ, a donor or a supplier for stock, then tick it off as it arrives.

  ordered     sent (WhatsApp, email or copied); nothing has arrived yet
  part        some lines or part of a line arrived; the rest is still expected
  arrived     everything arrived
  closed      some arrived and we stopped waiting for the rest
  cancelled   called off before anything arrived (can be reopened)

Each tick ("Arrived" or "Part arrived") is a receipt: stock goes into the warehouse with the order number as its
reference and waiting requests are allocated straight away. A receipt can be reversed if it was a misclick: the
units come off the shelf again (stock reserved from them, but not yet on a truck, is released first).
"""

import json
import re
from datetime import datetime

from ..db.database import get_conn, now, transaction
from ..engine import URGENCY_LEVELS
from .allocation import run_allocation
from .history import snapshot

DEFAULT_CONTACT = {"name": "HQ supply desk", "whatsapp": "+971554992348", "email": "watchingyoutub998@gmail.com"}
VIA = {"whatsapp": "WhatsApp", "email": "email", "copy": "copied message"}


def _event(conn, message, data=None):
    conn.execute("INSERT INTO events (created_at, kind, message, data) VALUES (?, 'order', ?, ?)",
                 (now(), message, json.dumps(data) if data else None))


def _whole(value, what, minimum=1):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{what} must be a whole number.")
    if value < minimum:
        raise ValueError(f"{what} must be {minimum} or more.")
    if value > 1_000_000:
        raise ValueError(f"{what} of {value:,} looks like a typo.")
    return value


def _amount(q, unit, item):
    unit, low = (unit or "").lower(), item.lower()
    return f"{q:,} {low}" if not unit or unit == "units" or unit in low else f"{q:,} {unit} of {low}"


def _lines_text(lines):
    return ", ".join(_amount(l["quantity"], l.get("unit"), l["item"]) for l in lines)


# ---------- Contact ----------

def contact(conn=None):
    row = (conn or get_conn()).execute("SELECT value FROM settings WHERE key = 'supply_contact'").fetchone()
    return {**DEFAULT_CONTACT, **(json.loads(row["value"]) if row else {})}


def save_contact(raw):
    name = re.sub(r"\s+", " ", str(raw.get("name") or "")).strip()[:60]
    phone = re.sub(r"[^\d+]", "", str(raw.get("whatsapp") or ""))
    email = str(raw.get("email") or "").strip()
    if not name:
        raise ValueError("Give the contact a name, like 'HQ supply desk'.")
    if phone and not re.fullmatch(r"\+?\d{7,15}", phone):
        raise ValueError("The WhatsApp number should be in international form, like +971554992348.")
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("That email address doesn't look right.")
    value = {"name": name, "whatsapp": phone, "email": email}
    with transaction() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('supply_contact', ?)", (json.dumps(value),))
    return value


# ---------- Reading ----------

def _status(o, lines):
    if o["cancelled_at"]:
        return "cancelled"
    if all(l["received"] >= l["quantity"] for l in lines):
        return "arrived"
    if o["closed_at"]:
        return "closed"
    return "part" if any(l["received"] for l in lines) else "ordered"


def orders(conn=None):
    conn = conn or get_conn()
    names = {w["id"]: w["name"] for w in conn.execute("SELECT id, name FROM warehouses")}
    lines, receipts = {}, {}
    for l in conn.execute("SELECT * FROM supply_lines ORDER BY id"):
        lines.setdefault(l["order_id"], []).append(dict(l))
    for r in conn.execute("SELECT * FROM supply_receipts ORDER BY id DESC"):
        r = dict(r)
        r["lines"] = json.loads(r["lines"])
        r["warehouse_name"] = names.get(r["warehouse_id"], r["warehouse_id"])
        receipts.setdefault(r["order_id"], []).append(r)
    out = []
    for o in conn.execute("SELECT * FROM supply_orders ORDER BY created_at DESC, id DESC"):
        o = dict(o)
        o["lines"] = lines.get(o["id"], [])
        for l in o["lines"]:
            l["outstanding"] = 0 if o["cancelled_at"] or o["closed_at"] else max(l["quantity"] - l["received"], 0)
        o["receipts"] = receipts.get(o["id"], [])
        o["status"] = _status(o, o["lines"])
        o["warehouse_name"] = names.get(o["warehouse_id"], o["warehouse_id"])
        o["ordered_units"] = sum(l["quantity"] for l in o["lines"])
        o["received_units"] = sum(l["received"] for l in o["lines"])
        o["outstanding_units"] = sum(l["outstanding"] for l in o["lines"])
        o["summary"] = _lines_text(o["lines"])
        out.append(o)
    return out


def on_order(conn=None):
    """Units still expected per item from open orders (so nobody orders the same shortfall twice)."""
    totals = {}
    for o in orders(conn):
        for l in o["lines"]:
            if l["outstanding"]:
                totals[l["item"]] = totals.get(l["item"], 0) + l["outstanding"]
    return totals


def _get(conn, order_id):
    o = conn.execute("SELECT * FROM supply_orders WHERE id = ?", ((order_id or "").strip().upper(),)).fetchone()
    if not o:
        raise LookupError(f"There's no supply order {order_id}.")
    o = dict(o)
    o["lines"] = [dict(l) for l in conn.execute("SELECT * FROM supply_lines WHERE order_id = ? ORDER BY id", (o["id"],))]
    o["status"] = _status(o, o["lines"])
    return o


# ---------- Changing ----------

def _next_number(conn):
    from .dispatch import _key
    day = datetime.now().strftime("%m%d")
    name = f"order-{day}"
    seq = int(_key(conn, name, lambda: "0")) + 1
    while conn.execute("SELECT 1 FROM supply_orders WHERE id = ?", (f"PO-{day}-{seq:03d}",)).fetchone():
        seq += 1
    conn.execute("UPDATE keys SET value = ? WHERE name = ?", (str(seq), name))
    return f"PO-{day}-{seq:03d}"


def create_order(lines, warehouse_id, sent_via="copy", supplier=None):
    """Record a supply request that was just sent. lines: [{item, quantity, unit?}]."""
    from .actions import _canonical_item
    if sent_via not in VIA:
        raise ValueError("Sent via must be whatsapp, email or copy.")
    if not isinstance(lines, list) or not lines:
        raise ValueError("Add at least one item to order.")
    with transaction() as conn:
        wh = conn.execute("SELECT id, name FROM warehouses WHERE id = ?", (warehouse_id,)).fetchone()
        if not wh:
            raise ValueError("Choose the warehouse it should be delivered to.")
        clean, seen = [], set()
        for raw in lines:
            item = _canonical_item(conn, (raw or {}).get("item"))
            if item.lower() in seen:
                raise ValueError(f"{item} is listed twice. Put it on one line.")
            seen.add(item.lower())
            qty = _whole((raw or {}).get("quantity"), f"Quantity of {item}")
            unit_row = conn.execute("SELECT unit FROM inventory WHERE item = ? LIMIT 1", (item,)).fetchone()
            unit = unit_row["unit"] if unit_row else (str((raw or {}).get("unit") or "units").strip().lower() or "units")
            clean.append({"item": item, "quantity": qty, "unit": unit})
        supplier = re.sub(r"\s+", " ", supplier or contact(conn)["name"]).strip()[:60]
        number = _next_number(conn)
        snapshot(conn, f"supply order {number}")
        conn.execute("INSERT INTO supply_orders (id, created_at, supplier, sent_via, warehouse_id) VALUES (?, ?, ?, ?, ?)",
                     (number, now(), supplier, sent_via, warehouse_id))
        for l in clean:
            conn.execute("INSERT INTO supply_lines (order_id, item, unit, quantity) VALUES (?, ?, ?, ?)",
                         (number, l["item"], l["unit"], l["quantity"]))
        _event(conn, f"{number} ordered from {supplier} by {VIA[sent_via]}: {_lines_text(clean)}, to {wh['name']}",
               {"order": number})
    return {"id": number, "supplier": supplier, "lines": clean, "warehouse": wh["name"]}


def cancel_order(order_id):
    with transaction() as conn:
        o = _get(conn, order_id)
        if o["status"] == "cancelled":
            raise ValueError(f"{o['id']} is already cancelled.")
        if any(l["received"] for l in o["lines"]):
            raise ValueError(f"Part of {o['id']} has already arrived. Use \"Stop waiting for the rest\" instead.")
        snapshot(conn, f"cancel {o['id']}")
        conn.execute("UPDATE supply_orders SET cancelled_at = ? WHERE id = ?", (now(), o["id"]))
        _event(conn, f"{o['id']} cancelled ({_lines_text(o['lines'])})", {"order": o["id"]})
    return {"id": o["id"], "status": "cancelled", "notify": notice(o["id"], "cancel")}


# ---------- Telling the supplier ----------
# Undo and Cancel change ReliefGrid, but a WhatsApp or email that already went out can't be unsent.
# So both come back with a ready-made follow-up message for the same person, and sending it is logged.

def notice(order_id, kind, conn=None):
    """The follow-up to send when an order that went out is cancelled ("cancel") or put back on ("reinstate")."""
    conn = conn or get_conn()
    o = _get(conn, order_id)
    wh = conn.execute("SELECT name FROM warehouses WHERE id = ?", (o["warehouse_id"],)).fetchone()
    when = o["created_at"][11:16]
    lines = _lines_text(o["lines"])
    if kind == "cancel":
        subject = f"Cancel supply request {o['id']}"
        text = (f"*Please cancel supply request {o['id']}*\nOur request from {when} for {lines} was sent by mistake. "
                f"Please don't send it.\nSorry for the trouble.\nSent from ReliefGrid")
    else:
        subject = f"Supply request {o['id']} is back on"
        text = (f"*Supply request {o['id']} is back on*\nPlease go ahead after all: {lines}, "
                f"deliver to {wh['name'] if wh else o['warehouse_id']}.\nSorry for the confusion.\nSent from ReliefGrid")
    return {"order": o["id"], "kind": kind, "via": o["sent_via"], "supplier": o["supplier"], "contact": contact(conn),
            "subject": subject, "text": text}


def record_notice(order_id, kind, via):
    """Log that the follow-up was sent (or copied), so the paper trail shows the supplier was told."""
    if kind not in ("cancel", "reinstate"):
        raise ValueError("kind must be cancel or reinstate.")
    if via not in VIA:
        raise ValueError("via must be whatsapp, email or copy.")
    with transaction() as conn:
        o = _get(conn, order_id)
        what = "Cancellation" if kind == "cancel" else "Go-ahead"
        _event(conn, f"{what} for {o['id']} sent to {o['supplier']} by {VIA[via]}", {"order": o["id"]})
    return {"ok": True}


def reopen_order(order_id):
    with transaction() as conn:
        o = _get(conn, order_id)
        if o["status"] not in ("cancelled", "closed"):
            raise ValueError(f"{o['id']} is still open.")
        snapshot(conn, f"reopen {o['id']}")
        conn.execute("UPDATE supply_orders SET cancelled_at = NULL, closed_at = NULL WHERE id = ?", (o["id"],))
        _event(conn, f"{o['id']} reopened: still expecting the rest", {"order": o["id"]})
    return {"id": o["id"], "notify": notice(o["id"], "reinstate") if o["status"] == "cancelled" else None}


def close_order(order_id):
    """Some arrived and the rest isn't coming: stop counting it as on order."""
    with transaction() as conn:
        o = _get(conn, order_id)
        if o["status"] != "part":
            raise ValueError("Only an order that has partly arrived can be closed. Cancel it if nothing arrived.")
        snapshot(conn, f"close {o['id']}")
        conn.execute("UPDATE supply_orders SET closed_at = ? WHERE id = ?", (now(), o["id"]))
        missing = [{"item": l["item"], "unit": l["unit"], "quantity": l["quantity"] - l["received"]}
                   for l in o["lines"] if l["quantity"] > l["received"]]
        _event(conn, f"{o['id']} closed: not waiting for {_lines_text(missing)}", {"order": o["id"]})
    return {"id": o["id"], "status": "closed"}


def receive(order_id, lines=None, warehouse_id=None):
    """Tick off what arrived. lines: {item: units}; leave it out when everything still expected has arrived."""
    with transaction() as conn:
        o = _get(conn, order_id)
        if o["status"] in ("cancelled", "closed", "arrived"):
            raise ValueError(f"{o['id']} is {o['status']}. Reopen it first if more arrived.")
        warehouse_id = warehouse_id or o["warehouse_id"]
        wh = conn.execute("SELECT id, name FROM warehouses WHERE id = ?", (warehouse_id,)).fetchone()
        if not wh:
            raise ValueError("That warehouse doesn't exist.")
        by_item = {l["item"].lower(): l for l in o["lines"]}
        if lines is None:
            got = {l["item"]: l["quantity"] - l["received"] for l in o["lines"] if l["quantity"] > l["received"]}
        else:
            if not isinstance(lines, dict) or not lines:
                raise ValueError("Say how much of each item arrived.")
            got = {}
            for item, qty in lines.items():
                l = by_item.get(str(item).strip().lower())
                if not l:
                    raise ValueError(f"{item} isn't on {o['id']}.")
                qty = _whole(qty, f"Units of {l['item']}", minimum=0)
                left = l["quantity"] - l["received"]
                if qty > left:
                    raise ValueError(f"Only {left:,} {l['item'].lower()} are still expected on {o['id']}. "
                                     f"Record anything extra as a separate delivery.")
                if qty:
                    got[l["item"]] = qty
        if not got:
            raise ValueError("Nothing to tick off: enter how much arrived.")
        snapshot(conn, f"receive {o['id']}")
        ts = now()
        for item, qty in got.items():
            l = by_item[item.lower()]
            conn.execute("UPDATE supply_lines SET received = received + ? WHERE id = ?", (qty, l["id"]))
            conn.execute("INSERT INTO inventory (warehouse_id, item, quantity, unit) VALUES (?, ?, ?, ?) "
                         "ON CONFLICT(warehouse_id, item) DO UPDATE SET quantity = quantity + excluded.quantity",
                         (warehouse_id, item, qty, l["unit"] or "units"))
            conn.execute("INSERT INTO movements (warehouse_id, item, delta, reason, ref, created_at) "
                         "VALUES (?, ?, ?, 'delivery received', ?, ?)", (warehouse_id, item, qty, o["id"], ts))
        rid = conn.execute("INSERT INTO supply_receipts (order_id, created_at, warehouse_id, lines) VALUES (?, ?, ?, ?)",
                           (o["id"], ts, warehouse_id, json.dumps(got))).lastrowid
        after = _get(conn, o["id"])
        text = _lines_text([{"item": i, "quantity": q, "unit": by_item[i.lower()]["unit"]} for i, q in got.items()])
        word = "arrived in full" if after["status"] == "arrived" else "part arrived"
        _event(conn, f"{o['id']} {word} at {wh['name']}: {text}", {"order": o["id"], "receipt": rid})
        _, decisions = run_allocation(conn, f"{o['id']} arrived")
    served = [d for d in decisions if d.given > 0]
    return {"id": o["id"], "receipt": rid, "status": after["status"], "units": sum(got.values()), "received": got,
            "requests_served": len(served)}


def _release(conn, warehouse_id, item, units, ts, ref):
    """Free up reserved stock (not yet on a truck) at a warehouse, least urgent first. Returns units freed."""
    rows = conn.execute(
        """SELECT a.id, a.request_id, a.quantity, r.urgency, r.created_at FROM allocations a
           JOIN requests r ON r.id = a.request_id
           WHERE a.warehouse_id = ? AND a.item = ? AND a.status = 'allocated'""", (warehouse_id, item)).fetchall()
    rows = sorted(rows, key=lambda a: (URGENCY_LEVELS.index(a["urgency"]), a["created_at"], a["id"]), reverse=True)
    freed = 0
    for a in rows:
        if freed >= units:
            break
        take = min(units - freed, a["quantity"])
        if take == a["quantity"]:
            conn.execute("DELETE FROM allocations WHERE id = ?", (a["id"],))
        else:
            conn.execute("UPDATE allocations SET quantity = quantity - ? WHERE id = ?", (take, a["id"]))
        conn.execute("UPDATE inventory SET quantity = quantity + ? WHERE warehouse_id = ? AND item = ?",
                     (take, warehouse_id, item))
        conn.execute("INSERT INTO movements (warehouse_id, item, delta, reason, ref, created_at) "
                     "VALUES (?, ?, ?, 'released: receipt reversed', ?, ?)", (warehouse_id, item, take, ref, ts))
        req = conn.execute("SELECT quantity, allocated FROM requests WHERE id = ?", (a["request_id"],)).fetchone()
        allocated = req["allocated"] - take
        conn.execute("UPDATE requests SET allocated = ?, status = ? WHERE id = ?",
                     (allocated, "partial" if allocated else "unfilled", a["request_id"]))
        freed += take
    return freed


def reverse_receipt(receipt_id):
    """Undo a tick (misclick or misunderstanding): the units come off the shelf again."""
    with transaction() as conn:
        r = conn.execute("SELECT * FROM supply_receipts WHERE id = ?", (receipt_id,)).fetchone()
        if not r:
            raise LookupError("That receipt doesn't exist.")
        if r["reversed_at"]:
            raise ValueError("That tick was already undone.")
        got = json.loads(r["lines"])
        ts = now()
        snapshot(conn, f"undo receipt on {r['order_id']}")
        for item, qty in got.items():
            shelf = conn.execute("SELECT quantity FROM inventory WHERE warehouse_id = ? AND item = ?",
                                 (r["warehouse_id"], item)).fetchone()
            on_shelf = shelf["quantity"] if shelf else 0
            if on_shelf < qty:
                _release(conn, r["warehouse_id"], item, qty - on_shelf, ts, r["order_id"])
                on_shelf = conn.execute("SELECT quantity FROM inventory WHERE warehouse_id = ? AND item = ?",
                                        (r["warehouse_id"], item)).fetchone()["quantity"]
            if on_shelf < qty:
                raise ValueError(f"{qty - on_shelf:,} of those {item.lower()} have already left on trucks, so this "
                                 f"tick can't be undone. Record a correction as a new delivery instead.")
            conn.execute("UPDATE inventory SET quantity = quantity - ? WHERE warehouse_id = ? AND item = ?",
                         (qty, r["warehouse_id"], item))
            conn.execute("INSERT INTO movements (warehouse_id, item, delta, reason, ref, created_at) "
                         "VALUES (?, ?, ?, 'receipt reversed', ?, ?)", (r["warehouse_id"], item, -qty, r["order_id"], ts))
            conn.execute("UPDATE supply_lines SET received = received - ? WHERE order_id = ? AND item = ?",
                         (qty, r["order_id"], item))
        conn.execute("UPDATE supply_receipts SET reversed_at = ? WHERE id = ?", (ts, receipt_id))
        conn.execute("UPDATE supply_orders SET closed_at = NULL WHERE id = ?", (r["order_id"],))
        units = {l["item"]: l["unit"] for l in conn.execute("SELECT item, unit FROM supply_lines WHERE order_id = ?",
                                                            (r["order_id"],))}
        _event(conn, f"{r['order_id']}: tick undone, {_lines_text([{'item': i, 'quantity': q, 'unit': units.get(i)} for i, q in got.items()])} "
                     f"taken back off the shelf", {"order": r["order_id"], "receipt": receipt_id})
        run_allocation(conn, f"receipt on {r['order_id']} undone")
    return {"id": r["order_id"], "receipt": receipt_id}
