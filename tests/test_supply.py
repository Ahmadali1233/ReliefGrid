"""Supply orders: order, tick off (all or part), undo a tick, cancel, close, and the contact."""


def checks_pass(client):
    c = client.get("/api/integrity").json()
    assert c["passed"] == c["total"], [x for x in c["checks"] if not x["passed"]]


def order(client, qty=540, via="whatsapp", item="Water"):
    r = client.post("/api/supply/orders", json={"lines": [{"item": item, "quantity": qty}], "warehouse_id": "WH-A",
                                                "sent_via": via})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def get(client, oid):
    return next(o for o in client.get("/api/supply/orders").json()["orders"] if o["id"] == oid)


def water(client):
    return next(i for i in client.get("/api/inventory").json() if i["item"] == "Water")


def test_order_counts_as_on_order_and_is_logged(client):
    assert water(client)["to_order"] == 540
    oid = order(client, 300)
    assert oid.startswith("PO-") and get(client, oid)["status"] == "ordered"
    w = water(client)
    assert w["on_order"] == 300 and w["to_order"] == 240
    assert "300 already ordered" in client.get("/api/summary").json()["subline"]
    assert client.get("/api/events", params={"kind": "order"}).json()[0]["message"].startswith(f"{oid} ordered")


def test_full_arrival_stocks_the_warehouse_and_allocates(client):
    oid = order(client, 540)
    r = client.post(f"/api/supply/orders/{oid}/receive").json()
    assert r["status"] == "arrived" and r["units"] == 540 and r["requests_served"] > 0
    assert water(client)["on_order"] == 0
    assert client.get("/api/summary").json()["kpis"]["critical_fulfilled"] == 20
    checks_pass(client)


def test_part_arrival_then_the_rest(client):
    oid = order(client, 540)
    r = client.post(f"/api/supply/orders/{oid}/receive", json={"lines": {"water": 200}}).json()
    assert r["status"] == "part"
    o = get(client, oid)
    assert o["received_units"] == 200 and o["outstanding_units"] == 340 and len(o["receipts"]) == 1
    assert client.post(f"/api/supply/orders/{oid}/receive", json={"lines": {"Water": 341}}).status_code == 400
    assert client.post(f"/api/supply/orders/{oid}/receive", json={"lines": {"Tents": 1}}).status_code == 400
    assert client.post(f"/api/supply/orders/{oid}/receive", json={"lines": {"Water": True}}).status_code == 400
    assert client.post(f"/api/supply/orders/{oid}/receive", json={"lines": {"Water": 0}}).status_code == 400
    assert client.post(f"/api/supply/orders/{oid}/receive").json()["status"] == "arrived"
    assert client.post(f"/api/supply/orders/{oid}/receive").status_code == 400
    checks_pass(client)


def test_undo_a_tick_takes_stock_back_even_if_it_was_reserved(client):
    before = water(client)["total"]
    oid = order(client, 540)
    client.post(f"/api/supply/orders/{oid}/receive")
    receipt = get(client, oid)["receipts"][0]["id"]
    # The 540 were reserved for waiting requests straight away; undoing releases those reservations first.
    r = client.post(f"/api/supply/receipts/{receipt}/reverse")
    assert r.status_code == 200, r.text
    o = get(client, oid)
    assert o["status"] == "ordered" and o["receipts"][0]["reversed_at"]
    assert water(client)["total"] == before
    assert client.post(f"/api/supply/receipts/{receipt}/reverse").status_code == 400
    checks_pass(client)


def test_undo_is_refused_once_the_stock_left_on_a_truck(client):
    oid = order(client, 540)
    client.post(f"/api/supply/orders/{oid}/receive")
    receipt = get(client, oid)["receipts"][0]["id"]
    for load in client.get("/api/dispatch", params={"status": "allocated"}).json()["loads"]:
        if any(i["item"] == "Water" for i in load["items"]) and load["warehouse_id"] == "WH-A":
            client.post("/api/dispatch/dispatched", json={"warehouse_id": "WH-A", "shelter_id": load["shelter_id"],
                                                          "driver": "Truck 1"})
    r = client.post(f"/api/supply/receipts/{receipt}/reverse")
    assert r.status_code == 400 and "left on trucks" in r.json()["error"]
    checks_pass(client)


def test_cancel_reopen_and_close(client):
    oid = order(client, 100)
    assert client.post(f"/api/supply/orders/{oid}/cancel").json()["status"] == "cancelled"
    assert water(client)["on_order"] == 0
    assert client.post(f"/api/supply/orders/{oid}/receive").status_code == 400
    client.post(f"/api/supply/orders/{oid}/reopen")
    client.post(f"/api/supply/orders/{oid}/receive", json={"lines": {"Water": 40}})
    assert client.post(f"/api/supply/orders/{oid}/cancel").status_code == 400      # part already arrived
    assert client.post(f"/api/supply/orders/{oid}/close").json()["status"] == "closed"
    assert get(client, oid)["outstanding_units"] == 0 and water(client)["on_order"] == 0


def test_bad_orders_are_refused(client):
    bad = [
        {"lines": [], "warehouse_id": "WH-A"},
        {"lines": [{"item": "Water", "quantity": 0}], "warehouse_id": "WH-A"},
        {"lines": [{"item": "Water", "quantity": True}], "warehouse_id": "WH-A"},
        {"lines": [{"item": "Water", "quantity": 5}], "warehouse_id": "WH-Z"},
        {"lines": [{"item": "Water", "quantity": 5}, {"item": "water", "quantity": 5}], "warehouse_id": "WH-A"},
        {"lines": [{"item": "Water", "quantity": 5}], "warehouse_id": "WH-A", "sent_via": "pigeon"},
    ]
    for body in bad:
        assert client.post("/api/supply/orders", json=body).status_code == 400, body
    assert client.post("/api/supply/orders/PO-0000-000/cancel").status_code == 404


def test_contact_defaults_and_validation(client):
    c = client.get("/api/supply/contact").json()
    assert c["whatsapp"] == "+971554992348" and c["email"] == "watchingyoutub998@gmail.com"
    assert client.put("/api/supply/contact", json={"name": "Red Crescent", "whatsapp": "12", "email": ""}).status_code == 400
    assert client.put("/api/supply/contact", json={"name": "Red Crescent", "whatsapp": "+971 50 123 4567",
                                                   "email": "a@b.org"}).json()["whatsapp"] == "+971501234567"


def test_undo_button_reverts_an_order(client):
    oid = order(client, 50)
    assert client.post("/api/undo").status_code == 200
    assert all(o["id"] != oid for o in client.get("/api/supply/orders").json()["orders"])
