"""Robustness: bad input of every kind is rejected with a clear message, and nothing changes.

These used to be an on-screen demo. They belong here: run on every test run, so a change that weakens
validation fails the build instead of being discovered by a judge (or a coordinator at 3 a.m.).
"""

import random

import pytest

from app.engine import allocate

GOOD = {"shelter_id": "SH-04", "item": "Water", "quantity": 10, "urgency": "high"}
R, S, SH, W, RU = "/api/requests", "/api/inventory/restock", "/api/shelters", "/api/warehouses", "/api/rules"

JSON_CASES = [
    (R, {**GOOD, "quantity": -5}), (R, {**GOOD, "quantity": 0}), (R, {**GOOD, "quantity": 2.5}),
    (R, {**GOOD, "quantity": "ten"}), (R, {**GOOD, "quantity": 1e12}), (R, {**GOOD, "quantity": None}),
    (R, {"shelter_id": "SH-04", "item": "Water", "urgency": "high"}), (R, {**GOOD, "urgency": "whenever"}),
    (R, {**GOOD, "urgency": ""}), (R, {**GOOD, "shelter_id": "SH-999"}), (R, {**GOOD, "shelter_id": ""}),
    (R, {**GOOD, "shelter_id": "SH-01' OR '1'='1"}), (R, {**GOOD, "shelter_id": "<script>alert(1)</script>"}),
    (R, {**GOOD, "item": ""}), (R, {**GOOD, "item": "     "}), (R, {"shelter_id": "SH-04", "quantity": 5, "urgency": "high"}),
    (R, {}), (R, []), (R, {**GOOD, "quantity": True}),
    (S, {"warehouse_id": "WH-A", "item": "Water", "quantity": -100}), (S, {"warehouse_id": "WH-A", "item": "Water", "quantity": 0}),
    (S, {"warehouse_id": "WH-A", "item": "Water", "quantity": "lots"}), (S, {"warehouse_id": "WH-A", "item": "Water", "quantity": 99000000}),
    (S, {"warehouse_id": "WH-Z", "item": "Water", "quantity": 10}), (S, {"warehouse_id": "WH-A", "item": "", "quantity": 10}),
    (S, {"warehouse_id": "WH-A", "item": "Water"}),
    (SH, {"id": "SH-X1", "name": "Test", "lat": 999, "lon": 55}), (SH, {"id": "SH-X2", "name": "Test", "lat": 25, "lon": -500}),
    (SH, {"id": "SH-X3", "name": "Test", "priority": 0}), (SH, {"id": "SH-X4", "name": "Test", "priority": "first"}),
    (SH, {"id": "SH-X5", "name": ""}), (SH, {"id": "SH-01", "name": "Copy"}),
    (W, {"id": "WH-A", "name": "Copy"}), (W, {"id": "", "name": "Nameless"}),
    ("/api/dispatch/dispatched", {"warehouse_id": "WH-A", "shelter_id": "SH-04", "driver": ""}),
    ("/api/dispatch/dispatched", {"warehouse_id": "WH-Q", "shelter_id": "SH-04", "driver": "Truck 1"}),
    ("/api/dispatch/delivered", {"warehouse_id": "WH-A", "shelter_id": "SH-04", "received_by": ""}),
    ("/api/reset", {}), ("/api/reset", {"confirm": "yes"}),
]

FILE_CASES = [
    ("empty.csv", b""), ("junk.csv", bytes([0, 255, 254, 1, 2, 3, 200, 13, 10, 0, 0])),
    ("broken.json", b'{"items": [1,'), ("broken.xml", b"<a><b></a>"),
    ("header.csv", b"request_id,shelter_id,item,quantity,urgency\n"), ("num.json", b"42"),
    ("sheet.xlsx", b"PK\x03\x04\x14\x00\x06\x00\x08\x00\x00\x00!\x00binary\x01\x02\x03"),
]


def snapshot(client):
    s = client.get("/api/summary").json()
    return (s["counts"], [(i["item"], i["total"]) for i in s["stock"]], s["kpis"]["units_allocated"])


@pytest.mark.parametrize("path, body", JSON_CASES)
def test_bad_json_is_rejected_cleanly(client, path, body):
    before = snapshot(client)
    r = client.post(path, json=body)
    assert 400 <= r.status_code < 500, (path, body, r.status_code)
    assert r.json().get("error"), "every rejection explains itself"
    assert snapshot(client) == before, "a rejected request must change nothing"


def test_bad_rules_are_rejected(client):
    for body in ({"reserve_for_critical_pct": 150}, {"max_per_shelter_per_item": -1}, {"low_stock_pct": "abc"}, {"free": 1}):
        r = client.put(RU, json=body)
        assert r.status_code == 400 and r.json()["error"]


def test_broken_json_body(client):
    r = client.post(R, content=b"}{ not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and r.json()["error"]


@pytest.mark.parametrize("name, content", FILE_CASES)
def test_bad_files_are_rejected(client, name, content):
    r = client.post("/api/import/preview", files={"file": (name, content)})
    assert r.status_code == 400 and r.json()["error"]


@pytest.mark.parametrize("method, path", [
    ("post", "/api/requests/REQ-99999/cancel"), ("get", "/api/requests/NOPE/explain"),
    ("get", "/api/reports?format=docx"), ("get", "/api/inventory/restock/preview?quantity=5&warehouse_id=WH-A"),
    ("get", "/api/requests/preview?shelter_id=X&item=Water&quantity=5&urgency=high"),
    ("get", "/api/dispatch?status=lost"),
])
def test_bad_lookups(client, method, path):
    r = getattr(client, method)(path)
    assert 400 <= r.status_code < 500 and r.json()["error"]


def test_integrity_still_holds_after_all_that(client):
    for path, body in JSON_CASES:
        client.post(path, json=body)
    checks = client.get("/api/integrity").json()
    assert checks["passed"] == checks["total"]


def _random_world(n, seed):
    rng = random.Random(seed)
    items = [f"Item {i:02d}" for i in range(12)]
    warehouses = {f"W{i}": (25.0 + rng.random() * 0.3, 55.1 + rng.random() * 0.4) for i in range(3)}
    shelters = [(f"S{i:03d}", rng.randint(1, 3), 25.0 + rng.random() * 0.3, 55.1 + rng.random() * 0.4) for i in range(200)]
    stock = {(w, it): rng.randint(0, n * 3) for w in warehouses for it in items}
    requests = []
    for i in range(n):
        sid, pri, lat, lon = rng.choice(shelters)
        q = rng.randint(1, 300)
        requests.append({"id": f"R{i:05d}", "shelter_id": sid, "item": rng.choice(items), "quantity": q,
                         "allocated": rng.choice([0, 0, 0, rng.randint(0, q)]),
                         "urgency": rng.choice(["critical", "high", "moderate"]),
                         "created_at": f"2026-10-31T{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:00",
                         "shelter_priority": pri, "lat": lat, "lon": lon})
    return items, warehouses, stock, requests


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_ten_thousand_requests_keep_every_rule(seed):
    items, warehouses, stock, requests = _random_world(10_000, seed)
    decisions, after = allocate(requests, stock, warehouses)
    assert all(v >= 0 for v in after.values())
    for it in items:
        start = sum(v for (w, i), v in stock.items() if i == it)
        end = sum(v for (w, i), v in after.items() if i == it)
        given = sum(d.given for d in decisions if d.item == it)
        assert start - given == end, f"stock doesn't add up for {it}"
    assert all(d.total <= d.requested for d in decisions)
    short = set()
    for d in decisions:          # decisions come back in service order
        assert not (d.item in short and d.given > 0), "someone lower in line got stock after someone above went short"
        if d.given < d.eligible:
            short.add(d.item)
    shuffled = requests[:]
    random.Random(seed).shuffle(shuffled)
    again, _ = allocate(shuffled, stock, warehouses)
    assert [(d.request_id, d.given) for d in decisions] == [(d.request_id, d.given) for d in again]
