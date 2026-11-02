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


def test_undo_of_a_sent_order_cancels_it_and_offers_a_cancellation_message(client):
    before = water(client)["on_order"]
    oid = order(client, 50)
    r = client.post("/api/undo").json()
    # The WhatsApp already went out: the order stays visible as cancelled, and a message to send is ready.
    assert get(client, oid)["status"] == "cancelled" and water(client)["on_order"] == before
    n = r["notify"]
    assert n["kind"] == "cancel" and n["via"] == "whatsapp" and n["contact"]["whatsapp"]
    assert oid in n["text"] and "50 cartons of water" in n["text"]
    assert client.post(f"/api/supply/orders/{oid}/notice", json={"kind": "cancel", "via": "whatsapp"}).status_code == 200
    log = client.get("/api/events", params={"kind": "order"}).json()
    assert log[0]["message"].startswith(f"Cancellation for {oid} sent to")
    assert any(e["message"].startswith(f"{oid} ordered") for e in log)          # the original order is still in the log
    assert client.post(f"/api/supply/orders/{oid}/notice", json={"kind": "oops", "via": "whatsapp"}).status_code == 400


def test_cancel_then_undo_offers_a_go_ahead_message(client):
    oid = order(client, 50, via="email")
    c = client.post(f"/api/supply/orders/{oid}/cancel").json()
    assert c["notify"]["kind"] == "cancel" and c["notify"]["via"] == "email"
    r = client.post("/api/undo").json()
    assert get(client, oid)["status"] == "ordered" and r["notify"]["kind"] == "reinstate"
    assert "go ahead" in r["notify"]["text"]


def test_undo_keeps_the_log_and_marks_what_was_undone(client):
    client.post("/api/requests", json={"shelter_id": "SH-07", "item": "Tents", "quantity": 4, "urgency": "high"})
    client.post("/api/undo")
    ev = client.get("/api/events").json()
    assert ev[0]["kind"] == "undo" and not ev[0]["undone"]
    marked = [e for e in ev if e["undone"]]
    assert marked and any("Johi Tent City" in e["message"] for e in marked)
    assert all(r["id"] != "REQ-049" for r in client.get("/api/requests").json())     # the data really was reversed
