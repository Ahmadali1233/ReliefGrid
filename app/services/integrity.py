"""Seven checks that prove the numbers are right. Shown live on the dashboard."""

from ..engine import allocate
from .allocation import load_rules, load_state


def _check(check_id, name, passed, detail):
    return {"id": check_id, "name": name, "passed": bool(passed), "detail": detail}


def run_checks(conn):
    results = []

    # 1. Stock is never negative.
    bad = conn.execute("SELECT warehouse_id, item, quantity FROM inventory WHERE quantity < 0").fetchall()
    results.append(_check(
        "non_negative", "Nothing below zero", not bad,
        "Every item in every warehouse has zero or more units." if not bad else
        "; ".join(f"{r['item']} at {r['warehouse_id']} is {r['quantity']}" for r in bad)))

    # 2. Stock adds up: current stock equals the sum of every recorded movement.
    mismatches = conn.execute("""
        SELECT i.warehouse_id, i.item, i.quantity, COALESCE(SUM(m.delta), 0) AS ledger
        FROM inventory i LEFT JOIN movements m ON m.warehouse_id = i.warehouse_id AND m.item = i.item
        GROUP BY i.warehouse_id, i.item HAVING i.quantity != COALESCE(SUM(m.delta), 0)""").fetchall()
    moves = conn.execute("SELECT COUNT(*) AS n FROM movements").fetchone()["n"]
    results.append(_check(
        "ledger", "Stock adds up", not mismatches,
        f"Current stock matches all {moves:,} recorded stock movements." if not mismatches else
        "; ".join(f"{r['item']} at {r['warehouse_id']}: {r['quantity']} in stock but ledger says {r['ledger']}"
                  for r in mismatches)))

    # 3. No request got more than it asked for, and allocations match the requests table.
    over = conn.execute("""
        SELECT r.id, r.quantity, r.allocated, COALESCE(SUM(a.quantity), 0) AS sent
        FROM requests r LEFT JOIN allocations a ON a.request_id = r.id
        GROUP BY r.id HAVING r.allocated > r.quantity OR r.allocated != COALESCE(SUM(a.quantity), 0)""").fetchall()
    results.append(_check(
        "no_overfill", "No request over-filled", not over,
        "Every request received at most what it asked for, and every unit is accounted for." if not over else
        "; ".join(f"{r['id']}: asked {r['quantity']}, recorded {r['allocated']}, sent {r['sent']}" for r in over)))

    # 4. Whole units only.
    fractional = conn.execute("""
        SELECT 'inventory' AS t FROM inventory WHERE typeof(quantity) != 'integer'
        UNION ALL SELECT 'requests' FROM requests WHERE typeof(quantity) != 'integer' OR typeof(allocated) != 'integer'
        UNION ALL SELECT 'allocations' FROM allocations WHERE typeof(quantity) != 'integer'""").fetchall()
    results.append(_check(
        "whole_units", "Whole units only", not fractional,
        "No half tents: every quantity is a whole number." if not fractional else
        f"{len(fractional)} fractional quantities found."))

    # 5. Priority order kept: within a run, nobody lower down got stock while someone above went short.
    violations = []
    entries = conn.execute(
        "SELECT run_id, item, request_id, rank, eligible, given FROM run_entries ORDER BY run_id, item, rank").fetchall()
    groups = {}
    for e in entries:
        groups.setdefault((e["run_id"], e["item"]), []).append(e)
    for (run_id, item), es in groups.items():
        short_seen = None
        for e in es:
            if short_seen and e["given"] > 0:
                violations.append(f"run {run_id}: {e['request_id']} got {item} while {short_seen} was short")
            if e["given"] < e["eligible"] and short_seen is None:
                short_seen = e["request_id"]
    # Also: no stock sitting unused while someone eligible is waiting.
    reqs, stock, warehouses, _, _ = load_state(conn)
    rules = load_rules(conn)
    pending, _ = allocate(reqs, stock, warehouses, rules)
    idle = [d for d in pending if d.given > 0]
    for d in idle[:3]:
        violations.append(f"{d.request_id} is waiting for {d.item} while {d.given} could be sent")
    runs = conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"]
    results.append(_check(
        "priority", "Priority order kept", not violations,
        f"Checked {len(entries):,} decisions across {runs:,} allocation runs; no stock is idle while someone waits."
        if not violations else "; ".join(violations[:5])))

    # 6. Same data, same answer: run the engine twice on identical input.
    a, _ = allocate(reqs, stock, warehouses, rules)
    b, _ = allocate(list(reversed(reqs)), dict(reversed(list(stock.items()))), warehouses, rules)
    same = [(d.request_id, d.given, [(t.warehouse_id, t.quantity) for t in d.takes]) for d in a] == \
           [(d.request_id, d.given, [(t.warehouse_id, t.quantity) for t in d.takes]) for d in b]
    results.append(_check(
        "deterministic", "Same result on re-run", same,
        "Running the engine again, even with the input shuffled, gives an identical result." if same else
        "Two runs on the same data disagreed."))

    # 7. Chain of custody: every unit that left a warehouse is on a waybill whose stage matches, and every
    #    waybill that left has a driver and every delivered one a signature.
    broken = conn.execute("""
        SELECT a.id, a.status, a.shipment_id, s.status AS ship_status FROM allocations a
        LEFT JOIN shipments s ON s.id = a.shipment_id
        WHERE a.status != 'allocated' AND (s.id IS NULL
              OR (a.status = 'dispatched' AND s.status != 'on_the_way')
              OR (a.status = 'delivered' AND s.status != 'delivered'))""").fetchall()
    unsigned = conn.execute("""SELECT id FROM shipments WHERE (status != 'loading' AND (driver IS NULL OR driver = ''))
                               OR (status = 'delivered' AND (received_by IS NULL OR received_by = ''))""").fetchall()
    moved = conn.execute("SELECT COALESCE(SUM(quantity), 0) AS u FROM allocations WHERE status != 'allocated'").fetchone()["u"]
    bills = conn.execute("SELECT COUNT(*) AS n FROM shipments WHERE status != 'loading'").fetchone()["n"]
    results.append(_check(
        "custody", "Every load on a waybill", not broken and not unsigned,
        f"All {moved:,} units that left a warehouse are on one of {bills:,} waybills, each with a driver, "
        f"and every delivery is signed for." if not broken and not unsigned else
        "; ".join([f"allocation {b['id']} ({b['status']}) has no matching waybill" for b in broken[:3]]
                  + [f"{u['id']} is missing a driver or signature" for u in unsigned[:3]])))

    return results
