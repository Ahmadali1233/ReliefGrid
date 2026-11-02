"""Matches unknown column names to ReliefGrid fields, then checks every row.

To accept a new column name on competition day, add it to ALIASES below.
To accept a whole new kind of record, add an entry to ENTITIES and a branch in validate().
"""

import re
from datetime import datetime

from ..engine import normalize_urgency

ENTITIES = {
    "requests": {"label": "Requests", "required": ["id", "shelter_id", "item", "quantity", "urgency"],
                 "optional": ["created_at"]},
    "inventory": {"label": "Inventory (stock received)", "required": ["warehouse_id", "item", "quantity"],
                  "optional": ["unit"]},
    "shelters": {"label": "Shelters", "required": ["id", "name"],
                 "optional": ["priority", "people", "lat", "lon", "location"]},
    "warehouses": {"label": "Warehouses", "required": ["id", "name"], "optional": ["lat", "lon", "location"]},
}

FIELD_LABELS = {
    "id": "ID", "shelter_id": "Shelter ID", "warehouse_id": "Warehouse ID", "item": "Item",
    "quantity": "Quantity", "urgency": "Urgency", "created_at": "Time submitted", "unit": "Unit",
    "name": "Name", "priority": "Shelter priority", "lat": "Latitude", "lon": "Longitude",
    "location": "Coordinates (lat, lon)", "people": "Headcount (people)",
}

ALIASES = {
    "id": ["id", "request_id", "requestid", "req_id", "req_no", "reqno", "request_no", "ref", "reference",
           "request", "shelter_id", "site_id", "warehouse_id", "wh_id", "code", "number"],
    "shelter_id": ["shelter_id", "shelterid", "shelter", "site", "site_id", "camp", "location_id",
                   "destination", "shelter_code"],
    "warehouse_id": ["warehouse_id", "warehouseid", "warehouse", "wh", "wh_id", "depot", "store", "store_id",
                     "hub", "source"],
    "item": ["item", "item_name", "supply", "supplies", "product", "resource", "goods", "commodity", "name_of_item"],
    "quantity": ["quantity", "qty", "amount", "count", "units", "number_of_units", "volume", "stock", "requested"],
    "urgency": ["urgency", "urgency_level", "level", "severity", "need", "triage", "priority_level",
                "request_priority", "priority"],
    "created_at": ["created_at", "time", "timestamp", "submitted", "submitted_at", "date", "requested_at"],
    "unit": ["unit", "units_label", "uom", "unit_of_measure", "measure", "packaging"],
    "name": ["name", "shelter_name", "site_name", "warehouse_name", "title", "label"],
    "priority": ["priority", "shelter_priority", "rank", "vulnerability", "tier", "level"],
    "lat": ["lat", "latitude", "y", "lat_deg", "location_lat", "coordinates_lat"],
    "lon": ["lon", "lng", "long", "longitude", "x", "lon_deg", "location_lon", "location_lng",
            "coordinates_lon", "coordinates_lng"],
    "location": ["location", "coordinates", "coords", "latlon", "lat_lon", "position", "gps"],
    "people": ["people", "headcount", "head_count", "population", "occupants", "residents", "persons",
               "pax", "individuals", "beneficiaries", "displaced", "people_count", "no_of_people", "occupancy"],
}


def normalize_column(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def signature(columns):
    return "|".join(sorted(normalize_column(c) for c in columns))


def _looks_numeric(values):
    """True when most values look like numbers (a few typos like 'ten' don't change the column's meaning)."""
    vals = [v for v in values if str(v).strip()]
    numeric = sum(1 for v in vals if re.fullmatch(r"-?[\d,]+(\.\d+)?", str(v).strip()))
    return bool(vals) and numeric / len(vals) >= 0.7


def suggest_mapping(columns, rows, entity):
    """Return {column: field or None} for one entity."""
    spec = ENTITIES[entity]
    fields = spec["required"] + spec["optional"]
    mapping, used = {}, set()
    norm = {c: normalize_column(c) for c in columns}
    # Pass 1: exact field-name matches. Pass 2: aliases, in each field's priority order.
    for c in columns:
        if norm[c] in fields and norm[c] not in used:
            mapping[c] = norm[c]
            used.add(norm[c])
    for field in fields:
        if field in used:
            continue
        for alias in ALIASES.get(field, []):
            col = next((c for c in columns if c not in mapping and norm[c] == alias), None)
            if col is None:
                continue
            sample = [r.get(col, "") for r in rows[:20]]
            if field == "quantity" and not _looks_numeric(sample):
                continue                  # "units" holding words is a unit label, not a quantity
            if field == "unit" and _looks_numeric(sample):
                continue
            mapping[col] = field
            used.add(field)
            break
    for c in columns:
        mapping.setdefault(c, None)
    return mapping


def detect(columns, rows):
    """Guess what kind of records a file holds. Returns (entity, mapping, scores)."""
    best, scores = None, {}
    for entity, spec in ENTITIES.items():
        m = suggest_mapping(columns, rows, entity)
        found = set(v for v in m.values() if v)
        required = len(set(spec["required"]) & found)
        missing = len(spec["required"]) - required
        scores[entity] = required - missing * 0.5 + len(found) * 0.01
        if best is None or scores[entity] > scores[best[0]]:
            best = (entity, m)
    return best[0], best[1], scores


def _clean_item(raw, known_items):
    item = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not item:
        return None
    for known in known_items:
        if known.lower() == item.lower():
            return known
    return item[0].upper() + item[1:]


def _parse_int(raw, allow_zero=False):
    text = str(raw or "").strip().replace(",", "").replace(" ", "")
    if text == "":
        return None, "is missing"
    if not re.fullmatch(r"-?\d+(\.0+)?", text):
        if re.fullmatch(r"-?\d+\.\d+", text):
            return None, f"is {raw}, but it must be a whole number"
        return None, f"is '{raw}', which isn't a number"
    value = int(float(text))
    if value < 0:
        return None, f"is {value}. It can't be negative"
    if value == 0 and not allow_zero:
        return None, "is 0. It must be 1 or more"
    if value > 1_000_000:
        return None, f"is {value:,}, which looks like a typo (over a million)"
    return value, None


def _parse_coord(raw, low, high):
    text = str(raw or "").strip()
    if not text:
        return None, None
    try:
        v = float(text)
    except ValueError:
        return None, f"'{raw}' isn't a coordinate"
    if not low <= v <= high:
        return None, f"{v} is outside {low} to {high}"
    return v, None


def validate(entity, rows, mapping, conn):
    """Check every row. Returns (good, issues, warnings).

    good:     list of clean records ready to save
    issues:   rows that will be skipped, each {"row": n, "message": "..."}
    warnings: rows saved with a small fix, each {"row": n, "message": "..."}
    """
    spec = ENTITIES[entity]
    inverse = {}
    for col, field in mapping.items():
        if field:
            inverse.setdefault(field, col)
    missing = [f for f in spec["required"] if f not in inverse
               and not (f in ("lat", "lon") and "location" in inverse)]
    if missing:
        names = ", ".join(FIELD_LABELS[m] for m in missing)
        raise ValueError(f"Match a column to: {names}.")

    def get(row, field):
        col = inverse.get(field)
        return row.get(col, "") if col else ""

    known_items = [r["item"] for r in conn.execute(
        "SELECT item FROM inventory UNION SELECT item FROM requests")]
    shelters = {r["id"] for r in conn.execute("SELECT id FROM shelters")}
    warehouses = {r["id"] for r in conn.execute("SELECT id FROM warehouses")}
    existing_requests = {r["id"] for r in conn.execute("SELECT id FROM requests")}

    good, issues, warnings, seen = [], [], [], {}
    for row in rows:
        n = row.get("__row")
        problem = None

        def fail(msg):
            issues.append({"row": n, "message": msg})

        if entity == "requests":
            rid = get(row, "id").strip()
            item = _clean_item(get(row, "item"), known_items)
            qty, qerr = _parse_int(get(row, "quantity"))
            urgency, recognised = normalize_urgency(get(row, "urgency"))
            sid = get(row, "shelter_id").strip()
            if not rid:
                problem = "has no request ID"
            elif rid in seen:
                problem = f"has the same ID as row {seen[rid]} ({rid})"
            elif rid in existing_requests:
                problem = f"{rid} already exists"
            elif not item:
                problem = "has no item"
            elif qerr:
                problem = f"quantity {qerr}"
            elif sid not in shelters:
                problem = f"shelter {sid or '(blank)'} doesn't exist yet. Import shelters first"
            if problem:
                fail(problem)
                if rid and rid not in seen:
                    seen[rid] = n
                continue
            seen[rid] = n
            if not recognised:
                raw = get(row, "urgency") or "(blank)"
                warnings.append({"row": n, "message": f"urgency '{raw}' not recognised, so treated as Moderate"})
            created = get(row, "created_at").strip()
            try:
                created = datetime.fromisoformat(created).isoformat(timespec="seconds") if created else None
            except ValueError:
                created = None
            if item not in known_items:
                known_items.append(item)
            good.append({"id": rid, "shelter_id": sid, "item": item, "quantity": qty,
                         "urgency": urgency, "created_at": created})

        elif entity == "inventory":
            wid = get(row, "warehouse_id").strip()
            item = _clean_item(get(row, "item"), known_items)
            qty, qerr = _parse_int(get(row, "quantity"))
            if wid not in warehouses:
                fail(f"warehouse {wid or '(blank)'} doesn't exist")
                continue
            if not item:
                fail("has no item")
                continue
            if qerr:
                fail(f"quantity {qerr}")
                continue
            key = (wid, item)
            if key in seen:
                prev = seen[key]
                prev["quantity"] += qty
                warnings.append({"row": n, "message": f"{item} at {wid} appears twice, so the amounts were added"})
                continue
            if item not in known_items:
                known_items.append(item)
            rec = {"warehouse_id": wid, "item": item, "quantity": qty,
                   "unit": (get(row, "unit").strip().lower() or None)}
            seen[key] = rec
            good.append(rec)

        else:  # shelters / warehouses
            rid = get(row, "id").strip()
            name = re.sub(r"\s+", " ", get(row, "name")).strip()
            lat, lerr = _parse_coord(get(row, "lat"), -90, 90)
            lon, oerr = _parse_coord(get(row, "lon"), -180, 180)
            loc = get(row, "location").strip()
            if loc and lat is None and lon is None:
                parts = re.split(r"[,; ]+", loc.strip("()[] "))
                if len(parts) == 2:
                    lat, lerr = _parse_coord(parts[0], -90, 90)
                    lon, oerr = _parse_coord(parts[1], -180, 180)
                else:
                    lerr = f"coordinates '{loc}' should look like '25.27, 55.30'"
            existing = shelters if entity == "shelters" else warehouses
            if not rid:
                problem = "has no ID"
            elif rid in seen:
                problem = f"has the same ID as row {seen[rid]} ({rid})"
            elif rid in existing:
                problem = f"{rid} already exists"
            elif not name:
                problem = "has no name"
            elif lerr or oerr:
                problem = f"latitude/longitude: {lerr or oerr}"
            if problem:
                fail(problem)
                continue
            seen[rid] = n
            rec = {"id": rid, "name": name, "lat": lat, "lon": lon}
            if entity == "shelters":
                pri_raw = get(row, "priority").strip()
                if pri_raw:
                    pri, perr = _parse_int(pri_raw)
                    if perr:
                        warnings.append({"row": n, "message": f"priority {perr}, so set to 2"})
                        pri = 2
                else:
                    pri = 2
                rec["priority"] = pri
                ppl_raw = get(row, "people").strip()
                rec["people"] = None
                if ppl_raw:
                    ppl, perr = _parse_int(ppl_raw, allow_zero=True)
                    if perr or ppl < 0:
                        warnings.append({"row": n, "message": f"headcount '{ppl_raw}' isn't a whole number, so it was left blank"})
                    else:
                        rec["people"] = ppl
            if lat is None or lon is None:
                warnings.append({"row": n, "message": "no coordinates, so it won't appear on the map"})
            good.append(rec)

    return good, issues, warnings
