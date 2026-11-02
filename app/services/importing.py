"""Import flow: preview a file (match columns, check rows), then commit the good rows."""

import json

from ..db.database import get_conn, now, transaction
from ..importers.mapper import ENTITIES, FIELD_LABELS, detect, signature, suggest_mapping, validate
from ..importers.parse import parse_file
from .allocation import run_allocation
from .history import snapshot


def _resolve(columns, rows, entity, mapping):
    conn = get_conn()
    remembered = False
    saved = conn.execute("SELECT entity, mapping FROM column_mappings WHERE signature = ?",
                         (signature(columns),)).fetchone()
    if entity is None and mapping is None and saved:
        # A file with exactly these columns was imported before: reuse that match.
        return saved["entity"], {c: (json.loads(saved["mapping"]).get(c) or None) for c in columns}, True
    if entity is None:
        entity, suggested, _ = detect(columns, rows)
    else:
        if entity not in ENTITIES:
            raise ValueError(f"Unknown record type '{entity}'.")
        suggested = suggest_mapping(columns, rows, entity)
    if mapping is None:
        if saved and saved["entity"] == entity:
            mapping, remembered = json.loads(saved["mapping"]), True
        else:
            mapping = suggested
    mapping = {c: (mapping.get(c) or None) for c in columns}
    return entity, mapping, remembered


def preview(content, filename, entity=None, mapping=None):
    columns, rows = parse_file(content, filename)
    entity, mapping, remembered = _resolve(columns, rows, entity, mapping)
    spec = ENTITIES[entity]
    result = {
        "filename": filename, "entity": entity, "entity_label": spec["label"],
        "entities": {k: v["label"] for k, v in ENTITIES.items()},
        "columns": columns, "mapping": mapping, "remembered": remembered,
        "fields": [{"id": f, "label": FIELD_LABELS[f], "required": f in spec["required"]}
                   for f in spec["required"] + spec["optional"]],
        "row_count": len(rows),
        "sample": [{c: r.get(c, "") for c in columns} for r in rows[:5]],
    }
    try:
        good, issues, warnings = validate(entity, rows, mapping, get_conn())
        result.update(ready=len(good), issues=issues, warnings=warnings, mapping_error=None)
    except ValueError as e:
        result.update(ready=0, issues=[], warnings=[], mapping_error=str(e))
    return result


def commit(content, filename, entity, mapping):
    columns, rows = parse_file(content, filename)
    entity, mapping, _ = _resolve(columns, rows, entity, mapping)
    with transaction() as conn:
        good, issues, warnings = validate(entity, rows, mapping, conn)
        if not good:
            raise ValueError("None of the rows could be imported. Check the problems listed and try again.")
        snapshot(conn, f"import {filename}")
        ts = now()
        if entity == "requests":
            for r in good:
                conn.execute("INSERT INTO requests (id, shelter_id, item, quantity, urgency, created_at) "
                             "VALUES (?, ?, ?, ?, ?, ?)",
                             (r["id"], r["shelter_id"], r["item"], r["quantity"], r["urgency"], r["created_at"] or ts))
        elif entity == "inventory":
            for r in good:
                unit = r["unit"]
                found = conn.execute("SELECT unit FROM inventory WHERE item = ? LIMIT 1", (r["item"],)).fetchone()
                unit = found["unit"] if found else (unit or "units")
                conn.execute(
                    "INSERT INTO inventory (warehouse_id, item, quantity, unit) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(warehouse_id, item) DO UPDATE SET quantity = quantity + excluded.quantity",
                    (r["warehouse_id"], r["item"], r["quantity"], unit))
                conn.execute("INSERT INTO movements (warehouse_id, item, delta, reason, ref, created_at) "
                             "VALUES (?, ?, ?, 'import', ?, ?)", (r["warehouse_id"], r["item"], r["quantity"], filename, ts))
        elif entity == "shelters":
            for r in good:
                conn.execute("INSERT INTO shelters (id, name, priority, lat, lon, people) VALUES (?, ?, ?, ?, ?, ?)",
                             (r["id"], r["name"], r["priority"], r["lat"], r["lon"], r.get("people")))
        else:
            for r in good:
                conn.execute("INSERT INTO warehouses (id, name, lat, lon) VALUES (?, ?, ?, ?)",
                             (r["id"], r["name"], r["lat"], r["lon"]))
        conn.execute("INSERT OR REPLACE INTO column_mappings (signature, entity, mapping) VALUES (?, ?, ?)",
                     (signature(columns), entity, json.dumps(mapping)))
        skipped = f", skipped {len(issues)}" if issues else ""
        conn.execute("INSERT INTO events (created_at, kind, message, data) VALUES (?, 'import', ?, ?)",
                     (ts, f"Imported {len(good)} {ENTITIES[entity]['label'].lower()} from {filename}{skipped}",
                      json.dumps({"skipped": issues, "warnings": warnings})))
        run_id, decisions = run_allocation(conn, f"import {filename}")
    filled = sum(1 for d in decisions if d.given > 0)
    return {"entity": entity, "imported": len(good), "skipped": issues, "warnings": warnings,
            "run_id": run_id, "requests_served": filled}
