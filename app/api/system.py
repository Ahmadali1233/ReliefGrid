"""Dashboard summary, search, logs, integrity, rules, undo, reports, import and demo data."""

import json

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from ..db.database import get_conn, now, rows, transaction
from ..db.seed import load_empty, load_sample
from ..reports import report as reports
from ..services import actions, assistant, history, importing, queries
from ..services.allocation import load_rules
from ..services.integrity import run_checks

router = APIRouter(tags=["Dashboard and system"])

MAX_UPLOAD = 5 * 1024 * 1024


@router.get("/api/version")
def version():
    """Which version of ReliefGrid is running (the interface checks this on start-up)."""
    import os
    from .. import API_LEVEL, VERSION
    return {"version": VERSION, "api_level": API_LEVEL, "phone_url": os.environ.get("RELIEFGRID_PHONE_URL") or None}


@router.get("/api/changes")
def changes():
    """A cheap fingerprint of the data: screens poll it and refresh when someone else (or a phone) changed something."""
    conn = get_conn()
    r = conn.execute("SELECT COALESCE(MAX(id), 0) AS last, COUNT(*) AS n FROM events").fetchone()
    return {"version": f"{r['last']}-{r['n']}"}


@router.get("/api/network")
def network():
    """The relief web on the dashboard: warehouses, shelters (with headcount and status) and every load between them."""
    return queries.network()


@router.get("/api/figures")
def get_figures():
    """Planning figures: how much one person needs of each item, per day or once per stay."""
    from ..services import people
    return {"items": list(people.figures().values()), "people": people.totals()}


@router.put("/api/figures")
def put_figures(body: dict):
    """Replace the planning figures. Body: {"items": [{"item", "per_person", "per": "day"|"stay", "basis"}]}"""
    from ..services import people
    if not isinstance(body.get("items"), list):
        raise ValueError("Send {\"items\": [...]}.")
    return people.save_figures(body["items"])


@router.get("/api/summary")
def summary():
    """Everything the dashboard shows, in one call."""
    return queries.summary()


@router.get("/api/sitrep")
def sitrep():
    """A short situation report, ready to paste into WhatsApp or an email."""
    return queries.sitrep()


@router.get("/api/search")
def search(q: str = ""):
    """Find shelters, requests, items and warehouses by name or ID (used by Quick find, Ctrl+K)."""
    return queries.search(q)


@router.get("/api/allocations")
def allocations(limit: int = 500):
    """Every allocation: which request got how many units from which warehouse, newest first."""
    return rows("""SELECT a.id, a.run_id, a.created_at, a.request_id, r.shelter_id, s.name AS shelter_name,
                          a.item, a.quantity, a.warehouse_id, w.name AS warehouse_name, a.distance_km
                   FROM allocations a JOIN requests r ON r.id = a.request_id
                   JOIN shelters s ON s.id = r.shelter_id JOIN warehouses w ON w.id = a.warehouse_id
                   ORDER BY a.id DESC LIMIT ?""", (limit,))


@router.get("/api/events")
def events(kind: str | None = None, limit: int = 200):
    """The activity log: allocations, restocks, imports, rule changes, undo."""
    return queries.events_list(kind, limit)


@router.post("/api/allocate")
def allocate():
    """Run allocation now (it also runs automatically after every change)."""
    return actions.allocate_now()


@router.get("/api/integrity")
def integrity():
    """Seven checks that prove the numbers are right."""
    checks = run_checks(get_conn())
    return {"passed": sum(c["passed"] for c in checks), "total": len(checks), "checks": checks}


@router.get("/api/rules")
def get_rules():
    return load_rules()


@router.put("/api/rules")
def put_rules(body: dict):
    """Change rule toggles, e.g. {"reserve_for_critical_pct": 20}. Allocation re-runs."""
    return actions.save_rules(body)


@router.get("/api/undo")
def can_undo():
    snap = history.last_snapshot(get_conn())
    return {"label": snap["label"] if snap else None, "at": snap["at"] if snap else None,
            "seconds_left": snap["seconds_left"] if snap else 0}


@router.get("/api/ask")
def ask(q: str = ""):
    """The command bar: a plain-words question or instruction -> an answer, or a previewed action to confirm."""
    return assistant.ask(q[:300])


@router.post("/api/undo")
def undo():
    """Reverse the last change."""
    import re
    from ..services import supply
    snap = history.last_snapshot(get_conn())
    m = re.fullmatch(r"supply order (PO-\d{4}-\d{3})", snap["label"]) if snap else None
    if m:
        # The order already went out by WhatsApp, email or copy-paste. Erasing it would hide that; instead it is
        # cancelled (kept in the log) and the person gets a cancellation message to send to the same supplier.
        with transaction() as conn:
            conn.execute("DELETE FROM snapshots WHERE id = (SELECT MAX(id) FROM snapshots)")
            history.mark_undone(conn, snap["at"])
        supply.cancel_order(m.group(1))
        with transaction() as conn:
            conn.execute("DELETE FROM snapshots WHERE id = (SELECT MAX(id) FROM snapshots)")
            conn.execute("INSERT INTO events (created_at, kind, message, data) VALUES (?, 'undo', ?, ?)",
                         (now(), f"Undid: {snap['label']} (kept in the log as cancelled)", json.dumps({"order": m.group(1)})))
        return {"undone": snap["label"], "notify": supply.notice(m.group(1), "cancel")}
    with transaction() as conn:
        label = history.undo(conn)
    if label is None:
        raise HTTPException(409, "There's nothing to undo. Undo only covers your last change, within 10 minutes.")
    m = re.fullmatch(r"cancel (PO-\d{4}-\d{3})", label)
    return {"undone": label, "notify": supply.notice(m.group(1), "reinstate") if m else None}


@router.get("/api/reports")
def report(format: str = "json"):
    """Fulfilled and unfilled shelter requests. format = json, csv or pdf."""
    data = reports.build()
    stamp = data["generated_at"][:16].replace(":", "").replace("T", "-")
    if format == "json":
        return Response(json.dumps(data, indent=2), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="reliefgrid-report-{stamp}.json"'})
    if format == "csv":
        return Response(reports.to_csv(data), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="reliefgrid-report-{stamp}.csv"'})
    if format == "pdf":
        return Response(reports.to_pdf(data), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="reliefgrid-report-{stamp}.pdf"'})
    raise HTTPException(400, "Format must be json, csv or pdf.")


async def _read(file):
    content = await file.read(MAX_UPLOAD + 1)
    if len(content) > MAX_UPLOAD:
        raise HTTPException(413, "That file is over 5 MB. Split it into smaller files.")
    return content


def _mapping(raw):
    if not raw:
        return None
    try:
        m = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(400, "The column matches couldn't be read.")
    if not isinstance(m, dict):
        raise HTTPException(400, "The column matches couldn't be read.")
    return m


@router.post("/api/import/preview")
async def import_preview(file: UploadFile = File(...), entity: str | None = Form(None),
                         mapping: str | None = Form(None)):
    """Read a CSV, JSON or XML file, match its columns and check every row. Saves nothing."""
    return importing.preview(await _read(file), file.filename, entity or None, _mapping(mapping))


@router.post("/api/import/commit")
async def import_commit(file: UploadFile = File(...), entity: str | None = Form(None),
                        mapping: str | None = Form(None)):
    """Save the good rows from a file (bad rows are skipped and listed), then allocate."""
    return importing.commit(await _read(file), file.filename, entity or None, _mapping(mapping))


SAMPLE_FILES = {"messy_requests.csv": "text/csv", "requests_day2.xml": "application/xml",
                "delivery_truck.json": "application/json"}


@router.get("/api/samples/{name}")
def sample_file(name: str):
    """Demo files for the Import screen."""
    if name not in SAMPLE_FILES:
        raise HTTPException(404, "No such sample file.")
    from ..db.seed import SAMPLE
    return Response((SAMPLE / name).read_bytes(), media_type=SAMPLE_FILES[name])


@router.post("/api/reset")
def reset(body: dict):
    """Demo only: wipe everything and load the sample data, or start empty. Send {"confirm": "RESET", "sample": true}."""
    if (body or {}).get("confirm") != "RESET":
        raise HTTPException(400, 'To wipe all data, send {"confirm": "RESET"}.')
    if body.get("sample", True):
        load_sample()
    else:
        load_empty()
    return {"ok": True, "sample": bool(body.get("sample", True))}
