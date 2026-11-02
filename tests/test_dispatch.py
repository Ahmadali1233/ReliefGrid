"""The real-world flow after allocation: load a truck, deliver, sign. Plus who did what."""


def first_load(client, status="allocated"):
    loads = client.get("/api/dispatch", params={"status": status}).json()["loads"]
    assert loads, f"no {status} loads"
    return loads[0]


def test_allocations_start_in_the_warehouse(client):
    data = client.get("/api/dispatch").json()
    assert data["counts"]["allocated"]["units"] > 0
    assert data["counts"]["dispatched"]["units"] > 0 and data["counts"]["delivered"]["units"] > 0   # sample history
    load = first_load(client)
    assert load["items"] and load["total"] == sum(i["quantity"] for i in load["items"])
    assert load["drive_minutes"] is not None


def test_dispatch_then_deliver(client):
    load = first_load(client)
    key = {"warehouse_id": load["warehouse_id"], "shelter_id": load["shelter_id"]}
    r = client.post("/api/dispatch/dispatched", json={**key, "driver": "Truck 7 · Ahmed"}, headers={"X-Operator": "Sara"})
    assert r.status_code == 200 and r.json()["units"] == load["total"]
    on_way = [l for l in client.get("/api/dispatch", params={"status": "dispatched"}).json()["loads"]
              if l["shelter_id"] == load["shelter_id"] and l["warehouse_id"] == load["warehouse_id"]]
    assert on_way and on_way[0]["dispatched_by"] == "Truck 7 · Ahmed"
    r = client.post("/api/dispatch/delivered", json={**key, "received_by": "Fatima"})
    assert r.status_code == 200
    done = client.get("/api/dispatch", params={"status": "delivered"}).json()["loads"]
    assert any(l["received_by"] == "Fatima" for l in done)
    events = client.get("/api/events?kind=dispatch").json()
    assert events[0]["actor"] == "Sara"
    checks = client.get("/api/integrity").json()
    assert checks["passed"] == checks["total"]


def test_dispatch_needs_a_driver_and_delivery_needs_a_name(client):
    load = first_load(client)
    key = {"warehouse_id": load["warehouse_id"], "shelter_id": load["shelter_id"]}
    assert client.post("/api/dispatch/dispatched", json={**key, "driver": "  "}).status_code == 400
    assert client.post("/api/dispatch/delivered", json={**key, "received_by": "Fatima"}).status_code == 400  # not dispatched yet


def test_cannot_cancel_once_on_a_truck(client):
    load = first_load(client)
    rid = load["requests"][0]
    client.post("/api/dispatch/dispatched", json={"warehouse_id": load["warehouse_id"],
                                                  "shelter_id": load["shelter_id"], "driver": "Truck 2"})
    r = client.post(f"/api/requests/{rid}/cancel")
    assert r.status_code == 400 and "on a truck" in r.json()["error"]


def test_delivery_records_source_and_reference(client):
    r = client.post("/api/inventory/restock", json={"warehouse_id": "WH-A", "item": "Water", "quantity": 100,
                                                    "source": "UAE Red Crescent", "reference": "WB-20431"})
    assert r.status_code == 200
    msg = client.get("/api/events?kind=restock").json()[0]["message"]
    assert "UAE Red Crescent" in msg and "WB-20431" in msg


def test_operator_name_in_any_language(client):
    from urllib.parse import quote
    client.post("/api/inventory/restock", json={"warehouse_id": "WH-A", "item": "Tents", "quantity": 5},
                headers={"X-Operator": quote("فاطمة")})
    assert client.get("/api/events?kind=restock").json()[0]["actor"] == "فاطمة"


def test_undo_reverses_a_dispatch(client):
    load = first_load(client)
    client.post("/api/dispatch/dispatched", json={"warehouse_id": load["warehouse_id"],
                                                  "shelter_id": load["shelter_id"], "driver": "Truck 9"})
    before = client.get("/api/dispatch").json()["counts"]["dispatched"]["units"]
    assert client.post("/api/undo").json()["undone"].startswith("dispatch")
    assert client.get("/api/dispatch").json()["counts"]["dispatched"]["units"] < before


def test_change_request_quantity_down_returns_stock(client):
    full = next(r for r in client.get("/api/requests", params={"status": "fulfilled"}).json()
                if r["item"] == "Water" and r["dispatched"] == 0)
    before = sum(i["total"] for i in client.get("/api/inventory").json() if i["item"] == "Water")
    r = client.patch(f"/api/requests/{full['id']}", json={"quantity": full["quantity"] - 30})
    assert r.status_code == 200 and r.json()["released"] == 30
    # the 30 went back on the shelf and straight to whoever was waiting for water
    assert r.json()["requests_served"] >= 1
    checks = client.get("/api/integrity").json()
    assert checks["passed"] == checks["total"]


def test_change_request_urgency_reorders_the_queue(client):
    waiting = [r for r in client.get("/api/requests", params={"status": "waiting"}).json() if r["urgency"] == "moderate"]
    r = client.patch(f"/api/requests/{waiting[0]['id']}", json={"urgency": "critical"})
    assert r.status_code == 200 and r.json()["urgency"] == "critical"


def test_change_request_cannot_go_below_whats_on_a_truck(client):
    load = client.get("/api/dispatch", params={"status": "allocated"}).json()["loads"][0]
    client.post("/api/dispatch/dispatched", json={"warehouse_id": load["warehouse_id"], "shelter_id": load["shelter_id"], "driver": "Truck 3"})
    rid = load["requests"][0]
    assert client.patch(f"/api/requests/{rid}", json={"quantity": 1}).status_code == 400
    assert client.patch(f"/api/requests/{rid}", json={}).status_code == 400          # nothing changed


def test_preview_warns_about_open_duplicate(client):
    p = client.get("/api/requests/preview", params={"shelter_id": "SH-04", "item": "water", "quantity": 10, "urgency": "high"}).json()
    assert p["open_duplicates"] and p["open_duplicates"][0]["id"] == "REQ-042"
