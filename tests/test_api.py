"""End-to-end tests through the REST API, with a real (temporary) database."""


def integrity_ok(client):
    data = client.get("/api/integrity").json()
    assert data["passed"] == data["total"], data
    return data


def test_sample_data_loads_and_all_checks_pass(client):
    s = client.get("/api/summary").json()
    assert s["counts"] == {"shelters": 14, "warehouses": 2, "requests": 48, "items": 7}
    assert s["headline"] == "19 of 20 critical requests covered."
    assert s["subline"].startswith("Water ran out first.")
    integrity_ok(client)


def test_add_request_allocates_immediately(client):
    r = client.post("/api/requests", json={"shelter_id": "SH-04", "item": "ready meals", "quantity": 150,
                                           "urgency": "Critical"})
    assert r.status_code == 201
    body = r.json()
    assert body["item"] == "Ready meals"          # matched the existing item name
    assert body["given"] == 150 and body["status"] == "fulfilled"
    integrity_ok(client)


def test_request_larger_than_stock_is_partial(client):
    body = client.post("/api/requests", json={"shelter_id": "SH-04", "item": "Tents", "quantity": 500,
                                              "urgency": "critical"}).json()
    assert body["status"] == "partial" and body["given"] == 22
    integrity_ok(client)


def test_bad_input_gets_a_clear_message(client):
    cases = [
        ({"shelter_id": "SH-04", "item": "Water", "quantity": -5, "urgency": "high"}, "1 or more"),
        ({"shelter_id": "SH-04", "item": "Water", "quantity": 2.5, "urgency": "high"}, "whole number"),
        ({"shelter_id": "SH-04", "item": "Water", "quantity": "ten", "urgency": "high"}, "whole number"),
        ({"shelter_id": "SH-99", "item": "Water", "quantity": 5, "urgency": "high"}, "doesn't exist"),
        ({"shelter_id": "SH-04", "item": "  ", "quantity": 5, "urgency": "high"}, "Choose an item"),
        ({"shelter_id": "SH-04", "item": "Water", "quantity": 5, "urgency": "whenever"}, "Urgency must be"),
        ({"shelter_id": "SH-04", "item": "Water", "urgency": "high"}, "required"),
    ]
    for payload, expected in cases:
        r = client.post("/api/requests", json=payload)
        assert r.status_code == 400, payload
        assert expected in r.json()["error"], (payload, r.json())
    integrity_ok(client)


def test_restock_serves_waiting_requests_most_urgent_first(client):
    preview = client.get("/api/inventory/restock/preview",
                         params={"item": "Water", "quantity": 60, "warehouse_id": "WH-A"}).json()
    assert preview["critical"] == 1
    r = client.post("/api/inventory/restock", json={"warehouse_id": "WH-A", "item": "Water", "quantity": 60}).json()
    assert r["requests_served"] == preview["requests"]
    s = client.get("/api/summary").json()
    assert s["headline"] == "All 20 critical requests covered."
    integrity_ok(client)


def test_undo_puts_everything_back(client):
    before = client.get("/api/summary").json()
    client.post("/api/inventory/restock", json={"warehouse_id": "WH-A", "item": "Water", "quantity": 900})
    assert client.get("/api/summary").json()["headline"] != before["headline"]
    assert client.post("/api/undo").json()["undone"].startswith("delivery")
    after = client.get("/api/summary").json()
    assert after["headline"] == before["headline"]
    assert after["stock"] == before["stock"]
    integrity_ok(client)


def test_nothing_to_undo_is_a_clear_error(client):
    while client.get("/api/undo").json()["label"]:
        client.post("/api/undo")
    r = client.post("/api/undo")
    assert r.status_code == 409 and "nothing to undo" in r.json()["error"]


def test_cancel_returns_stock_and_reallocates(client):
    fulfilled_water = [r for r in client.get("/api/requests", params={"status": "fulfilled", "item": "Water"}).json()
                       if r["dispatched"] == 0]          # still in the warehouse, so it can be cancelled
    target = fulfilled_water[0]
    r = client.post(f"/api/requests/{target['id']}/cancel").json()
    assert r["returned"] == target["quantity"]
    assert r["requests_served"] >= 1               # the returned water went to someone waiting
    assert client.post(f"/api/requests/{target['id']}/cancel").status_code == 400
    integrity_ok(client)


def test_explain_endpoint(client):
    waiting = client.get("/api/requests", params={"status": "waiting"}).json()
    why = client.get(f"/api/requests/{waiting[0]['id']}/explain").json()
    assert why["headline"] and len(why["steps"]) >= 2
    assert client.get("/api/requests/NOPE/explain").status_code == 404


def test_rules_reserve_and_validation(client):
    assert client.put("/api/rules", json={"reserve_for_critical_pct": 150}).status_code == 400
    assert client.put("/api/rules", json={"made_up_rule": 1}).status_code == 400
    r = client.put("/api/rules", json={"reserve_for_critical_pct": 25}).json()
    assert r["rules"]["reserve_for_critical_pct"] == 25
    integrity_ok(client)


def test_reports_in_all_three_formats(client):
    j = client.get("/api/reports?format=json")
    assert j.status_code == 200
    data = j.json()
    assert data["totals"]["requests"] == 48
    assert len(data["unfilled_or_partial"]) + len(data["fulfilled"]) == 48
    c = client.get("/api/reports?format=csv")
    assert c.text.splitlines()[0].startswith("id,shelter_id")
    assert len(c.text.strip().splitlines()) == 49
    p = client.get("/api/reports?format=pdf")
    assert p.content[:4] == b"%PDF"
    assert client.get("/api/reports?format=docx").status_code == 400


def test_add_shelter_and_warehouse(client):
    assert client.post("/api/shelters", json={"id": "SH-15", "name": "Al Nahda Hall", "priority": 1,
                                              "lat": 25.29, "lon": 55.37}).status_code == 201
    assert client.post("/api/shelters", json={"id": "SH-15", "name": "Dup"}).status_code == 400
    assert client.post("/api/shelters", json={"id": "SH-16", "name": "Bad", "lat": 120}).status_code == 400
    assert client.post("/api/warehouses", json={"id": "WH-C", "name": "Warehouse C"}).status_code == 201
    body = client.post("/api/requests", json={"shelter_id": "SH-15", "item": "Tents", "quantity": 5,
                                              "urgency": "critical"}).json()
    assert body["given"] == 5


def test_api_docs_and_web_page_are_served(client):
    assert client.get("/docs").status_code == 200
    assert client.get("/").status_code == 200
