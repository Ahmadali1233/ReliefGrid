"""The command bar: type what you want in plain words and ReliefGrid works out what you mean.

It runs entirely offline (no AI service, no internet), which matters in a disaster zone. It understands questions
("how much baby milk do we have?", "where is WB-1102-004?") and instructions ("Johi Tent City needs 200 water,
critical", "received 300 water at warehouse A", "cap at 7 days", "undo"). It never changes anything by itself:
instructions come back as a preview with the exact API call, and only run when the person presses Enter."""

import re

from ..db.database import get_conn
from . import history, people, queries, tracking
from .dispatch import loads

REF = re.compile(r"\b(req-\d{1,4}|wb-\d{4}-\d{3}|po-\d{4}-\d{3})\b", re.I)
SYNONYMS = {
    "water": ["drinking water", "water", "cartons of water"],
    "ready meals": ["ready meals", "ready meal", "meals", "meal", "food", "rations", "food packs"],
    "blankets": ["blankets", "blanket"],
    "tents": ["tents", "tent"],
    "first aid kits": ["first aid kits", "first-aid kits", "first aid kit", "first aid", "first-aid", "medkits", "medical kits"],
    "baby milk": ["baby milk", "baby formula", "infant formula", "formula", "milk"],
    "hygiene kits": ["hygiene kits", "hygiene kit", "hygiene", "soap"],
}
URGENCY = {"critical": "critical", "urgent": "critical", "emergency": "critical", "asap": "critical",
           "high": "high", "moderate": "moderate", "medium": "moderate", "normal": "moderate", "low": "moderate"}
PAGES = {"dashboard": "", "home": "", "requests": "requests", "dispatch": "dispatch", "trucks": "dispatch",
         "waybills": "dispatch", "inventory": "inventory", "stock": "inventory", "shelters": "shelters", "camps": "shelters",
         "map": "shelters", "log": "log", "activity": "log", "history": "log", "orders": "log?tab=orders",
         "supply orders": "log?tab=orders", "rules": "rules", "settings": "rules", "import": "import"}
COMMON = {"dadu", "camp", "hall", "the", "relief", "centre", "center", "government", "govt", "high", "school",
          "south", "health", "of", "and", "post", "city"}
EXAMPLES = ["Johi Tent City needs 200 water, critical", "How much baby milk do we have?", "Who is waiting for blankets?",
            "Received 300 water at Warehouse A", "Order 48 baby milk", "Cap at 7 days", "Trucks on the road", "Undo"]


def _norm(q):
    q = re.sub(r"(?<=\d),(?=\d{3}\b)", "", q.lower())
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s\-%·]", " ", q)).strip()


def _world(conn):
    shelters = [dict(r) for r in conn.execute("SELECT id, name, priority, people FROM shelters ORDER BY id")]
    warehouses = [dict(r) for r in conn.execute("SELECT id, name FROM warehouses ORDER BY id")]
    items = sorted({r["item"] for r in conn.execute("SELECT item FROM inventory UNION SELECT item FROM requests")})
    phrases = []
    for item in items:
        low = item.lower()
        for p in {low, low.rstrip("s"), *SYNONYMS.get(low, [])}:
            phrases.append((p, item))
    phrases.sort(key=lambda x: -len(x[0]))
    return shelters, warehouses, items, phrases


def _find_shelter(q, shelters):
    """Exact name or ID wins; otherwise score the words that are special to one shelter. Returns (shelter, span, others)."""
    m = re.search(r"\bsh[\s-]?0*(\d{1,3})\b", q)
    if m:
        sid = f"SH-{int(m.group(1)):02d}"
        s = next((s for s in shelters if s["id"] == sid), None)
        if s:
            return s, m.span(), []
    for s in sorted(shelters, key=lambda s: -len(s["name"])):
        i = q.find(_norm(s["name"]))
        if i >= 0:
            return s, (i, i + len(_norm(s["name"]))), []
    words = set(re.findall(r"[a-z]+", q))
    counts = {}
    for s in shelters:
        for w in set(re.findall(r"[a-z]+", s["name"].lower())):
            counts[w] = counts.get(w, 0) + 1
    scored = []
    for s in shelters:
        sw = set(re.findall(r"[a-z]+", s["name"].lower()))
        score = sum(0.5 if w in COMMON and counts[w] > 1 else 2 if counts[w] <= 2 else 1 for w in sw & words)
        if score:
            scored.append((score, s))
    if not scored:
        return None, None, []
    scored.sort(key=lambda x: -x[0])
    best = [s for sc, s in scored if sc == scored[0][0]]
    if scored[0][0] < 2 or len(best) > 1:
        return None, None, [s for _, s in scored[:4]]
    span = None
    for w in sorted(set(re.findall(r"[a-z]+", best[0]["name"].lower())) & words, key=len, reverse=True):
        span = re.search(rf"\b{w}\b", q).span()
        break
    return best[0], span, []


def _find_items(q, phrases):
    """All (item, start, end) mentions, longest phrase first, no overlaps."""
    found, taken = [], []
    for p, item in phrases:
        for m in re.finditer(rf"\b{re.escape(p)}\b", q):
            if any(m.start() < b and a < m.end() for a, b in taken):
                continue
            taken.append(m.span())
            found.append((item, m.start(), m.end()))
    return sorted(found, key=lambda x: x[1])


def _find_warehouse(q, warehouses):
    m = re.search(r"\b(?:warehouse|wh)[\s-]*([a-z])\b", q)
    if m:
        w = next((w for w in warehouses if w["id"].lower() == f"wh-{m.group(1)}"), None)
        if w:
            return w
    for w in warehouses:
        place = w["name"].split("·")[-1].strip().lower()
        if place and place in q and (place != "dadu" or "warehouse" in q):
            return w
    return None


def _quantity(q):
    q = REF.sub(" ", q)
    for m in re.finditer(r"\b(\d[\d,]*)\b(?!\s*(?:%|percent|days?|hours?|h\b|km))", q):
        n = int(m.group(1).replace(",", ""))
        if n > 0:
            return n, m.span()
    return None, None


def _pairs(q, phrases):
    """'48 baby milk and 200 water' -> [(Baby milk, 48), (Water, 200)]."""
    out = []
    for item, a, b in _find_items(q, phrases):
        before = q[max(0, a - 26):a]
        m = re.search(r"(\d[\d,]*)\s*(?:[a-z]+\s+){0,2}(?:of\s+)?$", before)
        out.append((item, int(m.group(1).replace(",", "")) if m else None))
    return out


def _urgency(q):
    for w, level in URGENCY.items():
        if re.search(rf"\b{w}\b", q):
            return level
    return None


def _stock(item_name):
    return next((i for i in queries.stock_by_item() if i["item"].lower() == item_name.lower()), None)


def _amt(item_name, qty):
    s = _stock(item_name)
    return queries.amount(s, qty) if s else f"{qty:,} {item_name.lower()}"


def answer(text, lines=(), links=(), title=None):
    return {"type": "answer", "title": title or text, "lines": list(lines), "links": list(links)}


def ask(raw):
    q = _norm(raw or "")
    if not q:
        return {"type": "help", "examples": EXAMPLES}
    conn = get_conn()
    shelters, warehouses, items, phrases = _world(conn)

    # Undo
    if re.fullmatch(r"(undo|undo (that|it|last|the last change)|take (that|it) back|oops)", q):
        snap = history.last_snapshot(conn)
        if not snap:
            return answer("Nothing to undo", ["Undo works on the last change made in the past 10 minutes."])
        return {"type": "action", "title": f"Undo: {snap['label']}", "lines": [f"Made at {snap['at'][11:16]}."],
                "confirm": "Undo it", "call": {"method": "POST", "path": "/api/undo"}, "done": "Undone."}

    # Go to a page
    m = re.fullmatch(r"(?:go to|open|show(?: me)?|take me to)?\s*(?:the )?([a-z ]+?)(?: page| tab)?", q)
    if m and m.group(1).strip() in PAGES:
        page = m.group(1).strip()
        return {"type": "navigate", "title": f"Open {page.title()}", "route": PAGES[page]}
    if re.search(r"\bsitrep\b|situation report", q):
        return {"type": "open", "what": "sitrep", "title": "Write a situation report"}
    if re.search(r"\b(check|checks|integrity|verify|audit)\b", q) and not _find_items(q, phrases):
        return {"type": "open", "what": "integrity", "title": "Run the 7 checks"}

    # Things with a number on them: requests, waybills, supply orders
    ref = REF.search(q)
    if ref:
        code = ref.group(1).upper()
        if code.startswith("REQ-"):
            code = f"REQ-{int(code[4:]):03d}"
            if re.search(r"\b(cancel|delete|remove|drop)\b", q):
                r = conn.execute("SELECT r.*, s.name FROM requests r JOIN shelters s ON s.id = r.shelter_id WHERE r.id = ?",
                                 (code,)).fetchone()
                if not r:
                    return answer(f"There's no request {code}")
                return {"type": "action", "title": f"Cancel {code}",
                        "lines": [f"{r['name']} asked for {_amt(r['item'], r['quantity'])}. Its reserved stock goes back to the next in line."],
                        "confirm": "Cancel request", "call": {"method": "POST", "path": f"/api/requests/{code}/cancel"},
                        "done": f"{code} cancelled."}
        if code.startswith("PO-"):
            return {"type": "navigate", "title": f"Open supply order {code}", "route": f"log?tab=orders&q={code}"}
        try:
            t = tracking.track(code)
        except LookupError:
            return answer(f"Nothing found for {code}", ["Check the number on the slip or the request."])
        steps = [f"{'✓' if s['done'] else '·'} {s['label']}" + (f" · {s['at'][11:16]}" if s.get("at") and s["done"] else "")
                 for s in t["steps"]]
        return answer(t["headline"], steps, [{"label": f"Track {code}", "track": code}], title=f"{code}: {t['headline']}")

    shelter, span, maybe = _find_shelter(q, shelters)
    q_items = q[:span[0]] + " " * (span[1] - span[0]) + q[span[1]:] if span else q
    found = _find_items(q_items, phrases)
    item = found[0][0] if found else None
    qty, _ = _quantity(q_items)
    warehouse = _find_warehouse(q, warehouses)

    # Days cap
    m = re.search(r"\b(?:cap|limit|max(?:imum)?)\b.*?(\d+)\s*days?", q)
    if m or re.search(r"\b(remove|turn off|no|lift)\b.*\bcap\b", q):
        days = int(m.group(1)) if m else 0
        if days > 365:
            return answer("That's more than a year", ["Pick a number of days between 1 and 365, or say 'remove the cap'."])
        return {"type": "action", "title": f"Cap every shelter at {days} days of supply" if days else "Remove the days cap",
                "lines": ["Stock above the cap that isn't on a truck yet is freed for shelters that are short."
                          if days else "Back to strict priority order."],
                "confirm": "Apply rule", "call": {"method": "PUT", "path": "/api/rules", "body": {"max_days_per_shelter": days}},
                "done": "Rule saved.", "kind": "cap"}

    # Order supplies (opens the order form, already filled in)
    if re.match(r"(order|reorder|re-order|buy|request supplies|ask hq|ask for more|get more)\b", q) and not shelter:
        pairs = _pairs(q, phrases)
        if not pairs:
            short = [i for i in queries.stock_by_item() if i.get("to_order")]
            pairs = [(i["item"], i["to_order"]) for i in short]
        else:
            pairs = [(it, n or (_stock(it) or {}).get("to_order") or None) for it, n in pairs]
        lines = [_amt(it, n) if n else it for it, n in pairs] or ["Nothing is short right now."]
        return {"type": "open", "what": "order", "title": "Order supplies from HQ", "lines": lines,
                "prefill": [{"item": it, "quantity": n or ""} for it, n in pairs]}

    # Stock arrived at a warehouse
    if (re.search(r"\b(received|receive|restock|restocked|arrived|unloaded|counted|came in|delivery to)\b", q)
            or (re.search(r"\b(got|get|add|added)\b", q) and (warehouse or re.search(r"\b(warehouse|wh)\b", q)))) \
            and item and qty and not shelter:
        if not warehouse:
            return {"type": "answer", "title": "Which warehouse?",
                    "lines": [f"Add “at {w['name'].split('·')[0].strip()}”." for w in warehouses], "links": []}
        p = queries.restock_preview(item, qty, warehouse["id"])
        lines = [f"Fills {p['requests']} waiting request{'s' if p['requests'] != 1 else ''}"
                 + (f", {p['critical']} critical" if p["critical"] else "") + "."
                 if p["requests"] else "Nobody is waiting for it, so it goes on the shelf."]
        if p["left_over"] and p["requests"]:
            lines.append(f"{_amt(item, p['left_over'])} left on the shelf.")
        return {"type": "action", "title": f"Record {_amt(item, qty)} arriving at {warehouse['name']}", "lines": lines,
                "confirm": "Record delivery", "call": {"method": "POST", "path": "/api/inventory/restock",
                                                       "body": {"warehouse_id": warehouse["id"], "item": item, "quantity": qty}},
                "done": f"{_amt(item, qty)} added to {warehouse['name']}."}

    # A shelter needs something
    if shelter and item and qty:
        level = _urgency(q) or "high"
        p = queries.request_preview(shelter["id"], item, qty, level)
        lines = [f"Gets {p['would_get']:,} now" + (" (all of it)." if p["would_get"] >= qty else
                 f", {qty - p['would_get']:,} waits for stock." if p["would_get"] else ": nothing in stock for it yet.")]
        if p["ahead"]:
            lines.append(f"{p['ahead']} request{'s' if p['ahead'] != 1 else ''} ahead of it in line.")
        if p.get("size") and p["size"].get("warning"):
            lines.append(p["size"]["warning"])
        if p["open_duplicates"]:
            lines.append(f"Already waiting: {p['open_duplicates'][0]['id']} for {_amt(item, p['open_duplicates'][0]['quantity'])}. Check it isn't a duplicate.")
        if not _urgency(q):
            lines.append("Urgency: High (say “critical” or “moderate” to change).")
        return {"type": "action", "title": f"{shelter['name']} needs {_amt(item, qty)} · {level.title()}",
                "lines": lines, "confirm": "Add request",
                "call": {"method": "POST", "path": "/api/requests",
                         "body": {"shelter_id": shelter["id"], "item": item, "quantity": qty, "urgency": level}},
                "done": f"Request added for {shelter['name']}."}

    if item and qty and not shelter and re.search(r"\b(needs?|asks?|asked|wants?|requests?|for)\b", q):
        return {"type": "answer", "title": "Which shelter needs it?",
                "lines": [f"Try “{s['name']} needs {qty:,} {item.lower()}”" for s in maybe[:3]]
                or [f"Try “Johi Tent City needs {qty:,} {item.lower()}”"],
                "links": [{"label": s["name"], "route": f"shelters?id={s['id']}"} for s in maybe[:3]]}
    if maybe and not shelter and not item and len(q) > 2:
        return {"type": "answer", "title": "Which shelter did you mean?", "lines": [s["name"] for s in maybe],
                "links": [{"label": s["name"], "route": f"shelters?id={s['id']}"} for s in maybe]}

    # Questions
    if re.search(r"\b(fair|fairly|fairness|unfair|share)\b", q):
        out = []
        for f in people.fairness(conn):
            for a in f.get("above", [])[:2]:
                out.append(f"{a.get('shelter_name') or a['shelter_id']}: {a['days']:g} days of {f['item'].lower()} (well above)")
            for s in f.get("short", [])[:3]:
                out.append(f"{s.get('shelter_name') or s['shelter_id']}: {s.get('days', 0):g} days of {f['item'].lower()} (short)")
        return answer("Fair share" if out else "Everything is shared fairly right now",
                      out or ["No shelter is far above or far below its fair share."],
                      [{"label": "Open the dashboard", "route": ""}])
    if re.search(r"\b(on the road|on the way|en route|trucks?|driving|vans?)\b", q) and not item and not shelter:
        rows = loads("dispatched")
        lines = [f"{l['waybill']} → {l['shelter_name']} · {l.get('dispatched_by') or ''}".rstrip(" ·") for l in rows[:8]]
        return answer(f"{len(rows)} truck{'s' if len(rows) != 1 else ''} on the road", lines or ["None right now."],
                      [{"label": f"Track {l['waybill']}", "track": l["waybill"]} for l in rows[:3]])
    if re.search(r"\b(waiting|short|needs?|still need|queue|unfilled|missing)\b", q) or (re.search(r"\bwho\b", q) and item):
        reqs = [r for r in queries.requests_list() if r["status"] != "cancelled" and r["remaining"] > 0
                and (not item or r["item"] == item) and (not shelter or r["shelter_id"] == shelter["id"])]
        rank = {"critical": 0, "high": 1, "moderate": 2}
        reqs.sort(key=lambda r: (rank.get(r["urgency"], 3), r["created_at"]))
        name = {s["id"]: s["name"] for s in shelters}
        lines = [f"{r['id']} · {name.get(r['shelter_id'], r['shelter_id'])} · {_amt(r['item'], r['remaining'])} · {r['urgency']}"
                 for r in reqs[:8]]
        what = f" for {item.lower()}" if item else ""
        where = f" at {shelter['name']}" if shelter else ""
        total = sum(r["remaining"] for r in reqs)
        title = (f"{len(reqs)} request{'s' if len(reqs) != 1 else ''} waiting{what}{where}"
                 + (f": {_amt(item, total)}" if item and reqs else ""))
        return answer(title, lines or ["Nobody is waiting."], [{"label": f"Why? {r['id']}", "why": r["id"]} for r in reqs[:2]])
    if re.search(r"\b(ran out|run out|running out|out of|low|shortage|short of|reorder|what should we order)\b", q):
        short = [i for i in queries.stock_by_item() if i.get("to_order") or i["status"] in ("low", "out")]
        lines = [f"{i['item']}: {i['total']:,} free" + (f", {queries.amount(i, i['to_order'])} more needed" if i.get("to_order") else "")
                 + (f", {i['on_order']:,} already ordered" if i.get("on_order") else "") for i in short]
        return {**answer("Running low" if short else "Nothing is running low", lines),
                "links": [{"label": "Order supplies", "order": True}] if short else []}
    if item and not shelter:
        s = _stock(item)
        if not s:
            return answer(f"No {item.lower()} in any warehouse")
        lines = [f"{w['name']}: {w['quantity']:,} free, {w['reserved']:,} reserved" for w in s["warehouses"]]
        if s.get("waiting_requests"):
            lines.append(f"Waiting: {s['waiting_requests']} request{'s' if s['waiting_requests'] != 1 else ''}, {queries.amount(s, s['waiting_units'])}.")
        if s.get("on_order"):
            lines.append(f"On order: {queries.amount(s, s['on_order'])}.")
        if s.get("hours_of_cover"):
            lines.append(f"At today's rate, about {s['hours_of_cover']:g} hours of cover.")
        unit = s.get("unit") or "units"
        return answer(f"{item}: {s['total']:,} {unit} free", lines,
                      [{"label": "Open inventory", "route": "inventory"}], title=f"{item}: {s['total']:,} {unit} free, {s['reserved']:,} reserved")
    if shelter:
        v = next((x for x in queries.shelters_view()["shelters"] if x["id"] == shelter["id"]), None)
        lines = [f"{v['people']:,} people · priority {v['priority']}" if v.get("people") else f"Priority {v['priority']}",
                 f"{v['requests']} request{'s' if v['requests'] != 1 else ''}, {v['waiting']} still waiting"]
        for c in v.get("coverage", []):
            line = f"{c['item']}: {c['given']:,} of {c['requested']:,}"
            if c.get("days") is not None:
                line += f" · {c['days']:g} days"
            lines.append(line)
        return answer(shelter["name"], lines, [{"label": "Open on the map", "route": f"shelters?id={shelter['id']}"}])
    if re.search(r"\b(people|population|headcount|how many)\b", q):
        s = queries.summary()
        p = s.get("people") or {}
        return answer(f"{p.get('people', 0):,} people in {p.get('shelters', len(shelters))} shelters",
                      [f"{len(shelters)} shelters, {len(warehouses)} warehouses."])
    if re.search(r"\b(status|summary|overview|how are we|how is it going|what's happening|whats happening|update)\b", q):
        s = queries.summary()
        return answer(s["headline"], [s["subline"]], [{"label": "Open the dashboard", "route": ""}])

    results = queries.search(raw.strip())["results"]
    return {"type": "results", "title": f"Matches for “{raw.strip()}”" if results else "I didn't catch that",
            "results": results, "examples": [] if results else EXAMPLES[:4]}
