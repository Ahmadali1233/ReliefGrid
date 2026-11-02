"""Read-only views of the data for the dashboard, tables, map and reports."""

import json
import re
from datetime import datetime, timedelta

from ..db.database import get_conn
from ..engine import sort_key
from .allocation import load_rules, preview
from .history import last_label
from .integrity import run_checks
from . import people

STATUS_ORDER = {"unfilled": 0, "partial": 1, "fulfilled": 2, "cancelled": 3}


def requests_list(status=None, urgency=None, item=None, shelter_id=None, q=None):
    conn = get_conn()
    sql = """SELECT r.*, s.name AS shelter_name, s.priority AS shelter_priority, s.lat, s.lon, s.people,
                    (SELECT unit FROM inventory i WHERE i.item = r.item LIMIT 1) AS unit,
                    (SELECT COALESCE(SUM(quantity), 0) FROM allocations a WHERE a.request_id = r.id
                       AND a.status IN ('dispatched', 'delivered')) AS dispatched,
                    (SELECT COALESCE(SUM(quantity), 0) FROM allocations a WHERE a.request_id = r.id
                       AND a.status = 'delivered') AS delivered
             FROM requests r JOIN shelters s ON s.id = r.shelter_id WHERE 1 = 1"""
    params = []
    if status == "waiting":
        sql += " AND r.cancelled = 0 AND r.allocated < r.quantity"
    elif status == "cancelled":
        sql += " AND r.cancelled = 1"
    elif status:
        sql += " AND r.status = ? AND r.cancelled = 0"
        params.append(status)
    if urgency:
        sql += " AND r.urgency = ?"
        params.append(urgency)
    if item:
        sql += " AND r.item = ?"
        params.append(item)
    if shelter_id:
        sql += " AND r.shelter_id = ?"
        params.append(shelter_id)
    if q:
        like = f"%{q.strip()}%"
        sql += " AND (r.id LIKE ? OR r.item LIKE ? OR s.name LIKE ? OR r.shelter_id LIKE ?)"
        params += [like, like, like, like]
    out = []
    figs = people.figures(conn)
    open_totals = {}
    for t in conn.execute("SELECT shelter_id, lower(item) AS item, SUM(quantity) AS q FROM requests "
                          "WHERE cancelled = 0 GROUP BY shelter_id, lower(item)"):
        open_totals[(t["shelter_id"], t["item"])] = t["q"]
    for r in conn.execute(sql, params):
        r = dict(r)
        if r["cancelled"]:
            r["status"] = "cancelled"
        r["remaining"] = 0 if r["cancelled"] else r["quantity"] - r["allocated"]
        r["explanation"] = json.loads(r["explanation"]) if r["explanation"] else None
        r["size_note"], r["size_warning"] = _size_note(r, figs, open_totals)
        out.append(r)
    # Waiting first (in the order they'll be served next), then fulfilled, then cancelled.
    out.sort(key=lambda r: (0 if r["remaining"] > 0 else 1 if r["status"] != "cancelled" else 2, sort_key(r)))
    return out


def _size_note(r, figs, open_totals):
    """('1.5 days of water for 400 people', warning or None) for one request, from the shelter's headcount."""
    fig = people.figure_for(figs, r["item"])
    if not fig or not r.get("people") or r["cancelled"]:
        return None, None
    total = open_totals.get((r["shelter_id"], r["item"].lower()), r["quantity"])
    if fig["per"] == "day":
        need = r["people"] * fig["per_person"]
        note = f"{people._days(r['quantity'] / need)} for {r['people']:,} people"
        if total / need > people.LARGE_REQUEST_DAYS:
            return note, (f"{people._days(total / need)} of {r['item'].lower()} for {r['people']:,} people "
                          f"across its open requests. Check the numbers?")
        return note, None
    need = max(round(r["people"] * fig["per_person"]), 1)
    note = f"for {r['people']:,} people (about {need:,} needed)"
    if total > need * people.LARGE_REQUEST_TIMES:
        return note, f"{total:,} asked for {r['people']:,} people; the planning figure is about {need:,}. Check the numbers?"
    return note, None


def request_detail(request_id):
    found = [r for r in requests_list() if r["id"] == request_id]
    if not found:
        return None
    r = found[0]
    conn = get_conn()
    r["allocations"] = [dict(a) for a in conn.execute(
        """SELECT a.quantity, a.warehouse_id, w.name AS warehouse_name, a.distance_km, a.created_at, a.run_id,
                  a.status, a.dispatched_at, a.dispatched_by, a.delivered_at, a.received_by
           FROM allocations a JOIN warehouses w ON w.id = a.warehouse_id
           WHERE a.request_id = ? ORDER BY a.id""", (request_id,))]
    r["losses"] = [dict(x) for x in conn.execute(
        "SELECT quantity, warehouse_id, note, reported_by, created_at FROM losses WHERE request_id = ? ORDER BY id",
        (request_id,))]
    return r


FORECAST_WINDOW_HOURS = 6


def _add_forecast(conn, items):
    """Hours of stock left at the recent request rate ("runs out in ~3 h at today's pace").

    Rate = units requested in the last 6 hours of activity (counted back from the newest request),
    so it works whatever day the data is from.
    """
    reqs = [dict(r) for r in conn.execute("SELECT item, quantity, created_at FROM requests WHERE cancelled = 0")]
    times = []
    for r in reqs:
        try:
            r["t"] = datetime.fromisoformat(r["created_at"])
            times.append(r["t"])
        except (TypeError, ValueError):
            r["t"] = None
    latest = max(times) if times else None
    for it in items.values():
        it["rate_per_hour"] = 0.0
        it["hours_of_cover"] = None
        if latest is None:
            continue
        start = latest - timedelta(hours=FORECAST_WINDOW_HOURS)
        units = sum(r["quantity"] for r in reqs if r["item"] == it["item"] and r["t"] and r["t"] > start)
        rate = units / FORECAST_WINDOW_HOURS
        it["rate_per_hour"] = round(rate, 1)
        if rate > 0:
            it["hours_of_cover"] = round(it["total"] / rate, 1)


def stock_by_item():
    conn = get_conn()
    rules = load_rules(conn)
    received = {r["item"]: r["n"] for r in conn.execute(
        "SELECT item, SUM(delta) AS n FROM movements WHERE delta > 0 GROUP BY item")}
    waiting, waiting_requests = {}, {}
    for r in conn.execute("SELECT item, SUM(quantity - allocated) AS n, SUM(quantity > allocated) AS c "
                          "FROM requests WHERE cancelled = 0 GROUP BY item"):
        waiting[r["item"]], waiting_requests[r["item"]] = r["n"], r["c"]
    reserved = {(r["warehouse_id"], r["item"]): r["n"] for r in conn.execute(
        "SELECT warehouse_id, item, SUM(quantity) AS n FROM allocations WHERE status = 'allocated' "
        "GROUP BY warehouse_id, item")}
    items = {}
    for r in conn.execute("""SELECT i.item, i.unit, i.warehouse_id, w.name AS warehouse_name, i.quantity
                             FROM inventory i JOIN warehouses w ON w.id = i.warehouse_id ORDER BY i.item, i.warehouse_id"""):
        it = items.setdefault(r["item"], {"item": r["item"], "unit": r["unit"], "total": 0, "reserved": 0, "warehouses": []})
        held = reserved.get((r["warehouse_id"], r["item"]), 0)
        it["total"] += r["quantity"]
        it["reserved"] += held
        it["warehouses"].append({"id": r["warehouse_id"], "name": r["warehouse_name"], "quantity": r["quantity"],
                                 "reserved": held})
    # Requests held by a shelter cap won't get more even if stock arrives, so they don't count as "short".
    held_units, held_reqs = {}, {}
    for d in preview(conn):
        if d.capped and d.eligible == 0 and d.remaining > 0:
            held_units[d.item] = held_units.get(d.item, 0) + d.remaining
            held_reqs[d.item] = held_reqs.get(d.item, 0) + 1
    for it in items.values():
        it["received"] = received.get(it["item"], 0)
        it["held_by_rule"] = held_units.get(it["item"], 0)
        it["waiting_units"] = waiting.get(it["item"], 0) - it["held_by_rule"]
        it["waiting_requests"] = waiting_requests.get(it["item"], 0) - held_reqs.get(it["item"], 0)
        pct = (it["total"] / it["received"] * 100) if it["received"] else 0
        it["percent_left"] = round(pct, 1)
        if it["total"] == 0:
            it["status"] = "out"
        elif pct < rules["low_stock_pct"]:
            it["status"] = "low"
        else:
            it["status"] = "ok"
        it["short_by"] = max(it["waiting_units"] - it["total"], 0)
    _add_forecast(conn, items)
    from .supply import on_order
    ordered = on_order(conn)
    for it in items.values():
        it["days_on_shelf"] = people.days_on_shelf(conn, it["item"], it["total"])
        it["on_order"] = ordered.get(it["item"], 0)
        it["to_order"] = max(it["short_by"] - it["on_order"], 0)
    order = {"out": 0, "low": 1, "ok": 2}
    return sorted(items.values(), key=lambda i: (order[i["status"]], i["percent_left"], i["item"]))


def summary():
    conn = get_conn()
    reqs = [r for r in requests_list() if r["status"] != "cancelled"]
    stock = stock_by_item()
    by_urgency = {}
    for level in ("critical", "high", "moderate"):
        group = [r for r in reqs if r["urgency"] == level]
        by_urgency[level] = {
            "total": len(group),
            "fulfilled": sum(1 for r in group if r["status"] == "fulfilled"),
            "partial": sum(1 for r in group if r["status"] == "partial"),
            "unfilled": sum(1 for r in group if r["status"] == "unfilled"),
        }
    crit = by_urgency["critical"]
    units_requested = sum(r["quantity"] for r in reqs)
    units_allocated = sum(r["allocated"] for r in reqs)
    waiting = [r for r in reqs if r["remaining"] > 0]
    out_items = [s for s in stock if s["status"] == "out"]
    low_items = [s for s in stock if s["status"] == "low"]

    # The one sentence a coordinator needs.
    short = sorted([s for s in stock if s["short_by"] > 0], key=lambda s: -s["short_by"])
    if not reqs:
        headline, subline = "No requests yet.", "Add a request or import a file to get started."
    else:
        if crit["total"] == 0:
            headline = f"{len(reqs) - len(waiting)} of {len(reqs)} requests covered."
        elif crit["fulfilled"] == crit["total"]:
            headline = f"All {crit['total']} critical requests covered."
        else:
            headline = f"{crit['fulfilled']} of {crit['total']} critical requests covered."
        held_ids = {d.request_id for d in preview(conn) if d.capped and d.eligible == 0 and d.remaining > 0}
        if short:
            s = short[0]
            n = sum(1 for r in waiting if r["item"] == s["item"] and r["id"] not in held_ids)
            unit = s["unit"] if s["unit"] not in ("units", "") else s["item"].lower()
            verb = "ran out" if s["total"] == 0 else "is short"
            subline = (f"{s['item']} {verb} first. {s['short_by']:,} more {unit} would cover "
                       f"{n} waiting request{'s' if n != 1 else ''}.")
            if s.get("on_order"):
                subline += (f" {s['on_order']:,} already ordered" +
                            (", so that's covered." if not s["to_order"] else f"; {s['to_order']:,} still to order."))
        elif waiting:
            subline = f"{len(waiting)} requests are waiting on the current rules (reserve or shelter cap)."
        else:
            subline = "Every request is covered. Nothing is waiting."

    from .dispatch import counts as dispatch_counts
    flow = dispatch_counts()
    checks = run_checks(conn)
    events = [dict(e) for e in conn.execute(
        "SELECT id, created_at, kind, message FROM events ORDER BY id DESC LIMIT 8")]
    counts = {k: conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
              for k, t in (("shelters", "shelters"), ("warehouses", "warehouses"))}
    counts["requests"] = len(reqs)
    counts["items"] = len(stock)
    last_run = conn.execute("SELECT id, created_at, trigger FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    ppl = people.totals(conn)
    heads = {r["id"]: r["people"] for r in conn.execute("SELECT id, people FROM shelters")}
    crit_wait_shelters = {r["shelter_id"] for r in waiting if r["urgency"] == "critical"}
    ppl["waiting_critical"] = sum(heads.get(sid) or 0 for sid in crit_wait_shelters)
    ppl["shelters_waiting_critical"] = len(crit_wait_shelters)
    fair = people.fairness(conn)
    held = [d for d in preview(conn) if d.capped and d.eligible == 0 and d.remaining > 0]
    names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM shelters")}
    rules = load_rules(conn)
    return {
        "people": ppl,
        "rules": rules,
        "held_by_rule": [{"request_id": d.request_id, "shelter_id": d.shelter_id, "shelter_name": names.get(d.shelter_id),
                          "item": d.item, "urgency": d.urgency, "remaining": d.remaining, "cap_kind": d.cap_kind,
                          "cap_limit": d.cap_limit} for d in held],
        "fairness": [{"item": f["item"], "fair_days": f["fair_days"], "lowest": f["lowest"], "highest": f["highest"],
                      "short": f["short"][:4], "above": f["above"][:3]} for f in fair],
        "headline": headline, "subline": subline, "counts": counts,
        "last_run": dict(last_run) if last_run else None,
        "kpis": {
            "critical_total": crit["total"], "critical_fulfilled": crit["fulfilled"],
            "units_requested": units_requested, "units_allocated": units_allocated,
            "out_of_stock": [s["item"] for s in out_items], "low_stock": [s["item"] for s in low_items],
            "waiting": len(waiting),
            "units_to_load": flow["allocated"]["units"], "loads_to_load": flow["allocated"]["loads"],
            "units_on_the_way": flow["dispatched"]["units"], "loads_on_the_way": flow["dispatched"]["loads"],
            "units_delivered": flow["delivered"]["units"],
            "waiting_by_urgency": {lvl: sum(1 for r in waiting if r["urgency"] == lvl)
                                   for lvl in ("critical", "high", "moderate")},
        },
        "by_urgency": by_urgency,
        "stock": stock,
        "next_in_line": sorted(waiting, key=sort_key)[:5],
        "short_item": short[0]["item"] if reqs and short else None,
        "integrity": {"passed": sum(c["passed"] for c in checks), "total": len(checks), "checks": checks},
        "events": events,
        "can_undo": last_label(conn),
    }


def shelters_view():
    conn = get_conn()
    reqs = requests_list()
    cov = {}
    for c in people.coverage(conn):
        cov.setdefault(c["shelter_id"], []).append(c)
    fair = people.fairness(conn)
    out = []
    for s in conn.execute("SELECT * FROM shelters ORDER BY id"):
        s = dict(s)
        mine = [r for r in reqs if r["shelter_id"] == s["id"] and r["status"] != "cancelled"]
        s["requests"] = len(mine)
        s["waiting"] = sum(1 for r in mine if r["remaining"] > 0)
        s["units_requested"] = sum(r["quantity"] for r in mine)
        s["units_received"] = sum(r["allocated"] for r in mine)
        s["units_delivered"] = sum(r["delivered"] for r in mine)
        if not mine:
            s["status"] = "none"
        elif s["waiting"] == 0:
            s["status"] = "served"
        elif s["units_received"] > 0:
            s["status"] = "partial"
        else:
            s["status"] = "waiting"
        s["coverage"] = sorted(cov.get(s["id"], []), key=lambda c: c["item"])
        s["short_items"] = [f["item"] for f in fair if any(x["shelter_id"] == s["id"] for x in f["short"])]
        s["above_items"] = [f["item"] for f in fair if any(x["shelter_id"] == s["id"] for x in f["above"])]
        s["routes"] = [dict(r) for r in conn.execute(
            """SELECT a.warehouse_id, SUM(a.quantity) AS quantity FROM allocations a
               JOIN requests r ON r.id = a.request_id WHERE r.shelter_id = ? GROUP BY a.warehouse_id""", (s["id"],))]
        out.append(s)
    warehouses = [dict(w) for w in conn.execute("SELECT * FROM warehouses ORDER BY id")]
    return {"shelters": out, "warehouses": warehouses}


def network():
    """Everything the relief web needs: nodes (warehouses, shelters) and the loads between them by stage."""
    conn = get_conn()
    reqs = [r for r in requests_list() if r["status"] != "cancelled"]
    links = {}
    for a in conn.execute("""SELECT a.warehouse_id, r.shelter_id, a.status, SUM(a.quantity) AS units
                             FROM allocations a JOIN requests r ON r.id = a.request_id
                             GROUP BY a.warehouse_id, r.shelter_id, a.status"""):
        link = links.setdefault((a["warehouse_id"], a["shelter_id"]), {
            "warehouse_id": a["warehouse_id"], "shelter_id": a["shelter_id"],
            "allocated": 0, "dispatched": 0, "delivered": 0})
        link[a["status"]] = a["units"]
    shelters = []
    for s in conn.execute("SELECT id, name, priority, people, lat, lon FROM shelters ORDER BY id"):
        s = dict(s)
        mine = [r for r in reqs if r["shelter_id"] == s["id"]]
        waiting = [r for r in mine if r["remaining"] > 0]
        s["requests"] = len(mine)
        s["waiting"] = len(waiting)
        s["waiting_critical"] = sum(1 for r in waiting if r["urgency"] == "critical")
        s["waiting_items"] = sorted({r["item"] for r in waiting})
        mine_links = [l for l in links.values() if l["shelter_id"] == s["id"]]
        s["allocated"] = sum(l["allocated"] for l in mine_links)
        s["dispatched"] = sum(l["dispatched"] for l in mine_links)
        s["delivered"] = sum(l["delivered"] for l in mine_links)
        if s["waiting"]:
            s["state"] = "waiting"
        elif s["dispatched"]:
            s["state"] = "on_the_way"
        elif s["allocated"]:
            s["state"] = "to_load"
        elif s["delivered"]:
            s["state"] = "delivered"
        else:
            s["state"] = "none"
        shelters.append(s)
    warehouses = [dict(w) for w in conn.execute("SELECT id, name, lat, lon FROM warehouses ORDER BY id")]
    return {"warehouses": warehouses, "shelters": shelters, "links": list(links.values()),
            "people": people.totals(conn)}


EVENT_REF = re.compile(r"\b(?:REQ-\d{3,}|WB-\d{4}-\d{3}|PO-\d{4}-\d{3})\b")
EVENT_GROUP = {"allocation": "requests", "request": "requests", "cancel": "requests",
               "waybill": "trucks", "dispatch": "trucks", "delivered": "trucks",
               "restock": "stock", "import": "stock", "order": "orders",
               "rules": "settings", "shelter": "settings", "warehouse": "settings", "undo": "undo", "system": "system"}


def events_list(kind=None, limit=200):
    """The activity log, newest first. Each entry also says which group it belongs to and which shelters, items and
    numbered things (REQ-, WB-, PO-) it is about, so the log can be filtered and followed thread by thread."""
    conn = get_conn()
    sql, params = "SELECT * FROM events", []
    if kind:
        sql += " WHERE kind = ?"
        params.append(kind)
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(int(limit))
    shelters = sorted(((r["name"], r["id"]) for r in conn.execute("SELECT id, name FROM shelters")), key=lambda x: -len(x[0]))
    items = [r["item"] for r in conn.execute("SELECT item FROM inventory UNION SELECT item FROM requests")]
    reqs = {r["id"]: (r["shelter_id"], r["item"]) for r in conn.execute("SELECT id, shelter_id, item FROM requests")}
    ships = {r["id"]: r["shelter_id"] for r in conn.execute("SELECT id, shelter_id FROM shipments")}
    lines = {}
    for r in conn.execute("SELECT order_id, item FROM supply_lines"):
        lines.setdefault(r["order_id"], set()).add(r["item"])
    out = []
    for e in conn.execute(sql, params):
        e = dict(e)
        e["data"] = json.loads(e["data"]) if e["data"] else None
        data, msg = e["data"] or {}, e["message"]
        refs = list(dict.fromkeys(EVENT_REF.findall(msg)))
        for key in ("request_id", "waybill", "order"):
            if isinstance(data.get(key), str) and data[key] not in refs:
                refs.append(data[key])
        found_sh, found_it = set(), set()
        if isinstance(data.get("shelter_id"), str):
            found_sh.add(data["shelter_id"])
        for ref in refs:
            if ref in reqs:
                found_sh.add(reqs[ref][0])
                found_it.add(reqs[ref][1])
            found_sh.update([ships[ref]] if ref in ships else [])
            found_it.update(lines.get(ref, ()))
        low = msg.lower()
        found_sh.update(sid for name, sid in shelters if name.lower() in low)
        found_it.update(i for i in items if i.lower() in low)
        e.update(group=EVENT_GROUP.get(e["kind"], "system"), refs=refs, shelters=sorted(found_sh), items=sorted(found_it),
                 undone=bool(data.get("undone")))
        out.append(e)
    return out


def restock_preview(item, quantity, warehouse_id):
    """Which waiting requests would a delivery fill?"""
    conn = get_conn()
    decisions = preview(conn, extra_stock={(warehouse_id, item): quantity})
    served = [d for d in decisions if d.given > 0 and d.item == item]
    newly_done = {d.request_id for d in decisions if d.status == "fulfilled"}
    live = [r for r in requests_list() if r["status"] != "cancelled"]
    crit = [r for r in live if r["urgency"] == "critical"]
    crit_done = sum(1 for r in crit if r["status"] == "fulfilled" or r["id"] in newly_done)
    waiting_after = sum(1 for r in live if r["remaining"] > 0 and r["id"] not in newly_done)
    return {
        "requests": len(served),
        "fully": sum(1 for d in served if d.status == "fulfilled"),
        "units_used": sum(d.given for d in served),
        "critical": sum(1 for d in served if d.urgency == "critical"),
        "critical_covered_after": crit_done,
        "critical_total": len(crit),
        "waiting_after": waiting_after,
        "left_over": max(quantity - sum(d.given for d in served), 0),
    }


def amount(stock_item, qty):
    """'540 cartons of water', or just '120 blankets' when the unit is the item."""
    unit, item = (stock_item.get("unit") or "").lower(), stock_item["item"].lower()
    if not unit or unit == "units" or unit in item:
        return f"{qty:,} {item}"
    return f"{qty:,} {unit} of {item}"


def sitrep():
    """A short situation report, ready to paste into WhatsApp or an email."""
    s = summary()
    k = s["kpis"]
    when = datetime.now().strftime("%a %d %b, %H:%M")
    lines = [f"*ReliefGrid situation report* · {when}"]
    if k["critical_total"]:
        lines.append(f"Critical: {k['critical_fulfilled']} of {k['critical_total']} covered.")
    w = k["waiting_by_urgency"]
    lines.append(f"Waiting: {k['waiting']} requests ({w['critical']} critical, {w['high']} high, {w['moderate']} moderate)."
                 if k["waiting"] else "Waiting: none. Every request is covered.")
    short = [i for i in s["stock"] if i["short_by"] > 0]
    if short:
        lines.append("Need now: " + ", ".join(amount(i, i["short_by"]) for i in short) + ".")
    ordered = [i for i in s["stock"] if i.get("on_order")]
    if ordered:
        lines.append("Already ordered: " + ", ".join(amount(i, i["on_order"]) for i in ordered) + ".")
    if k["out_of_stock"]:
        lines.append(f"Out of stock: {', '.join(k['out_of_stock'])}.")
    low = [i for i in s["stock"] if i["status"] == "low"]
    if low:
        lines.append("Running low: " + ", ".join(
            f"{i['item']} ({i['total']:,}" + (f", ~{i['hours_of_cover']:g} h left" if i.get("hours_of_cover") else "") + ")"
            for i in low) + ".")
    pct = round(k["units_allocated"] / k["units_requested"] * 100) if k["units_requested"] else 0
    lines.append(f"Allocated: {k['units_allocated']:,} of {k['units_requested']:,} units ({pct}%) "
                 f"to {s['counts']['shelters']} shelters from {s['counts']['warehouses']} warehouses.")
    lines.append(f"Trucks: {k['units_delivered']:,} units delivered and signed for, {k['units_on_the_way']:,} on the road, "
                 f"{k['units_to_load']:,} waiting to be loaded.")
    if s["people"]["people"]:
        lines.append(f"People: {s['people']['people']:,} in shelters"
                     + (f"; {s['people']['waiting_critical']:,} still waiting on something critical." if s["people"]["waiting_critical"] else "."))
    lines.append(f"Checks: {s['integrity']['passed']}/{s['integrity']['total']} integrity checks passed.")
    return {"text": "\n".join(lines), "headline": s["headline"]}


def request_preview(shelter_id, item, quantity, urgency):
    """What would happen if this request were added right now?"""
    conn = get_conn()
    s = conn.execute("SELECT id, priority, lat, lon, people FROM shelters WHERE id = ?", (shelter_id,)).fetchone()
    if not s:
        return None
    fake = {"id": "~preview", "shelter_id": shelter_id, "item": item, "quantity": quantity, "allocated": 0,
            "urgency": urgency, "created_at": "9999", "shelter_priority": s["priority"],
            "lat": s["lat"], "lon": s["lon"]}
    decisions = preview(conn, extra_requests=[fake])
    mine = next((d for d in decisions if d.request_id == "~preview"), None)
    in_stock = conn.execute("SELECT COALESCE(SUM(quantity), 0) AS n FROM inventory WHERE item = ?",
                            (item,)).fetchone()["n"]
    open_same = [dict(r) for r in conn.execute(
        "SELECT id, quantity, allocated, urgency, created_at FROM requests WHERE shelter_id = ? AND lower(item) = lower(?) "
        "AND cancelled = 0 AND allocated < quantity ORDER BY created_at DESC", (shelter_id, item))]
    return {"would_get": mine.given if mine else 0, "in_stock": in_stock,
            "ahead": mine.ahead_count if mine else 0, "open_duplicates": open_same,
            "size": people.size_check(conn, dict(s), item, quantity) if quantity > 0 else None}


def search(q):
    """Quick find: shelters, requests, items and warehouses whose name or ID contains the search text."""
    text = (q or "").strip().lower()
    if not text:
        return {"results": []}
    conn = get_conn()
    like = f"%{text}%"
    out = []
    for r in conn.execute("""SELECT sh.id, sh.status, sh.driver, sh.received_by, s.name FROM shipments sh
                             JOIN shelters s ON s.id = sh.shelter_id WHERE lower(sh.id) LIKE ? ORDER BY sh.id DESC LIMIT 6""",
                          (like,)):
        stage = {"loading": "being loaded", "on_the_way": f"on the way with {r['driver']}",
                 "delivered": f"delivered, signed by {r['received_by']}"}[r["status"]]
        out.append({"type": "waybill", "id": r["id"], "label": f"{r['id']} · {r['name']}", "detail": stage, "track": r["id"]})
    from .supply import orders as supply_orders
    for o in [o for o in supply_orders(conn) if text in o["id"].lower()][:4]:
        out.append({"type": "order", "id": o["id"], "label": f"{o['id']} · {o['supplier']}",
                    "detail": f"{o['summary']} · {o['status']}", "route": "log?tab=orders"})
    for r in conn.execute("SELECT id, name, priority FROM shelters WHERE lower(name) LIKE ? OR lower(id) LIKE ? "
                          "ORDER BY name LIMIT 6", (like, like)):
        out.append({"type": "shelter", "id": r["id"], "label": r["name"], "detail": f"{r['id']} · priority {r['priority']}",
                    "route": f"shelters?id={r['id']}"})
    for r in conn.execute("""SELECT r.id, r.item, r.quantity, r.allocated, r.urgency, s.name FROM requests r
                             JOIN shelters s ON s.id = r.shelter_id
                             WHERE lower(r.id) LIKE ? OR lower(s.name) LIKE ? OR lower(r.item) LIKE ?
                             ORDER BY (r.quantity > r.allocated) DESC, r.created_at DESC LIMIT 8""", (like, like, like)):
        out.append({"type": "request", "id": r["id"], "label": f"{r['id']} · {r['name']}",
                    "detail": f"{r['item']} · {r['allocated']:,} of {r['quantity']:,} · {r['urgency']}", "why": r["id"]})
    for r in conn.execute("SELECT item, SUM(quantity) AS q, MIN(unit) AS unit FROM inventory WHERE lower(item) LIKE ? "
                          "GROUP BY item LIMIT 5", (like,)):
        out.append({"type": "item", "id": r["item"], "label": r["item"], "detail": f"{r['q']:,} {r['unit']} on shelf",
                    "route": "inventory"})
    for r in conn.execute("SELECT id, name FROM warehouses WHERE lower(name) LIKE ? OR lower(id) LIKE ? LIMIT 3",
                          (like, like)):
        out.append({"type": "warehouse", "id": r["id"], "label": r["name"], "detail": r["id"], "route": "inventory"})
    return {"results": out}
