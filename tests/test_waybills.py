"""Waybills, phone hand-off and tracking: every truckload has a number, a driver and a signature."""

import re
from urllib.parse import quote

WB = re.compile(r"^WB-\d{4}-\d{3}$")


def checks_pass(client):
    c = client.get("/api/integrity").json()
    assert c["passed"] == c["total"] == 7, [x for x in c["checks"] if not x["passed"]]


def route(client, shelter=None, warehouse=None):
    loads = client.get("/api/dispatch", params={"status": "allocated"}).json()["loads"]
    return next(l for l in loads if (shelter is None or l["shelter_id"] == shelter)
                and (warehouse is None or l["warehouse_id"] == warehouse))


def test_sample_loads_travel_on_numbered_waybills(client):
    data = client.get("/api/dispatch").json()
    moved = [l for l in data["loads"] if l["status"] != "allocated"]
    assert moved and all(WB.match(l["waybill"]) for l in moved)
    assert all(l["received_by"] for l in moved if l["status"] == "delivered")
    assert all(l["dispatched_by"] for l in moved)
    checks_pass(client)


def test_print_waybill_is_stable_and_picks_up_new_stock(client):
    r = route(client, "SH-14")
    a = client.post("/api/dispatch/waybill", json={"warehouse_id": r["warehouse_id"], "shelter_id": "SH-14"}).json()
    assert WB.match(a["waybill"]) and a["added"] > 0
    again = client.post("/api/dispatch/waybill", json={"warehouse_id": r["warehouse_id"], "shelter_id": "SH-14"}).json()
    assert again["waybill"] == a["waybill"] and again["added"] == 0
    assert route(client, "SH-14", r["warehouse_id"])["off_waybill"] == 0


def test_truck_takes_only_whats_on_its_waybill(client):
    # Malir Mosque Hall (SH-13) has stock reserved; print its waybill, then a new request reserves more on the same route.
    r = route(client, "SH-13")
    wb = client.post("/api/dispatch/waybill", json={"warehouse_id": r["warehouse_id"], "shelter_id": "SH-13"}).json()["waybill"]
    on_bill = route(client, "SH-13", r["warehouse_id"])["total"]
    client.post("/api/inventory/restock", json={"warehouse_id": r["warehouse_id"], "item": "Hygiene kits", "quantity": 500})
    client.post("/api/requests", json={"shelter_id": "SH-13", "item": "Hygiene kits", "quantity": 20, "urgency": "critical"})
    later = [l for l in client.get("/api/dispatch", params={"status": "allocated"}).json()["loads"]
             if l["shelter_id"] == "SH-13" and l["warehouse_id"] == r["warehouse_id"]][0]
    assert later["off_waybill"] == 20 and later["waybill"] == wb
    sent = client.post("/api/dispatch/dispatched", json={"waybill": wb, "driver": "Truck 2"}).json()
    assert sent["waybill"] == wb and sent["units"] == on_bill
    left = [l for l in client.get("/api/dispatch", params={"status": "allocated"}).json()["loads"]
            if l["shelter_id"] == "SH-13" and l["warehouse_id"] == r["warehouse_id"]]
    assert left and left[0]["waybill"] is None and left[0]["total"] == 20      # waits for the next truck
    checks_pass(client)


def test_phone_pickup_only_ships_what_the_driver_saw(client):
    r = route(client, "SH-10")
    wb = client.post("/api/dispatch/waybill", json={"warehouse_id": r["warehouse_id"], "shelter_id": "SH-10"}).json()
    seen = client.get(f"/api/handoff/{wb['waybill']}", params={"t": wb["token"]}).json()
    assert seen["stage"] == "to_load" and seen["load"]["total"] > 0
    client.post("/api/inventory/restock", json={"warehouse_id": r["warehouse_id"], "item": "Tents", "quantity": 100})
    client.post("/api/dispatch/waybill", json={"warehouse_id": r["warehouse_id"], "shelter_id": "SH-10"})  # reprint adds more
    out = client.post(f"/api/handoff/{wb['waybill']}/pickup",
                      json={"t": wb["token"], "driver": "Van 4 · Saima", "upto_id": seen["load"]["max_id"]},
                      headers={"X-Operator": quote("Van 4 · Saima")}).json()
    assert out["units"] == seen["load"]["total"]
    assert client.get("/api/events", params={"kind": "dispatch"}).json()[0]["actor"] == "Van 4 · Saima"
    checks_pass(client)


def test_phone_links_need_the_code_from_the_qr(client):
    r = route(client)
    wb = client.post("/api/dispatch/waybill", json={"warehouse_id": r["warehouse_id"], "shelter_id": r["shelter_id"]}).json()
    assert client.get(f"/api/handoff/{wb['waybill']}", params={"t": "guess"}).status_code == 403
    assert client.post(f"/api/handoff/{wb['waybill']}/pickup", json={"t": "guess", "driver": "X"}).status_code == 403
    other = client.get("/api/dispatch", params={"status": "dispatched"}).json()["loads"][0]
    # A real code for one waybill doesn't work on another.
    assert client.get(f"/api/handoff/{other['waybill']}", params={"t": wb["token"]}).status_code == 403


def test_short_delivery_is_recorded_and_requeued(client):
    load = client.get("/api/dispatch", params={"status": "dispatched"}).json()["loads"][0]
    item = load["items"][0]
    r = client.post(f"/api/handoff/{load['waybill']}/receive",
                    json={"t": load["token"], "received_by": "Fatima", "received": {item["item"]: item["quantity"] - 2},
                          "note": "2 crushed"}).json()
    assert r["lost"] == 2 and r["units"] == load["total"] - 2 and r["requeued"]
    t = client.get(f"/api/track/{load['waybill']}").json()
    assert t["status"] == "delivered" and t["lost"][0]["quantity"] == 2 and "Missing" in t["steps"][-1]["detail"]
    req = client.get(f"/api/requests/{r['requeued'][0]['request_id']}").json()
    assert req["losses"][0]["note"] == "2 crushed"
    checks_pass(client)
    assert client.post("/api/undo").status_code == 200
    assert client.get(f"/api/track/{load['waybill']}").json()["status"] == "on_the_way"
    checks_pass(client)


def test_bad_receipts_are_refused(client):
    load = client.get("/api/dispatch", params={"status": "dispatched"}).json()["loads"][0]
    item = load["items"][0]["item"]
    base = {"waybill": load["waybill"], "received_by": "Fatima"}
    bad = [
        {**base, "received": {item: load["items"][0]["quantity"] + 1}, "note": "x"},     # more than was sent
        {**base, "received": {"Rocket fuel": 1}, "note": "x"},                            # not on this truck
        {**base, "received": {item: -1}, "note": "x"},
        {**base, "received": {item: 0}},                                                   # missing units need a note
        {**base, "received_by": "  "},
    ]
    for body in bad:
        assert client.post("/api/dispatch/delivered", json=body).status_code == 400, body
    assert client.post("/api/dispatch/delivered", json={**base, "received": {item: True}, "note": "x"}).status_code == 400
    assert client.post("/api/dispatch/delivered", json=base).status_code == 200
    assert client.post("/api/dispatch/delivered", json=base).status_code == 400       # can't sign twice
    assert client.post("/api/dispatch/delivered", json={"received_by": "x"}).status_code == 400


def test_track_a_request_like_a_parcel(client):
    waiting = next(r for r in client.get("/api/requests", params={"status": "waiting"}).json() if r["allocated"] == 0)
    t = client.get(f"/api/track/{waiting['id'].lower()}").json()            # case doesn't matter
    assert t["type"] == "request" and t["headline"].startswith("Waiting for stock")
    assert t["queue"]["position"] >= 1 and not t["steps"][1]["done"]
    delivered = next(r for r in client.get("/api/requests").json() if r["delivered"] == r["quantity"])
    t = client.get(f"/api/track/{delivered['id']}").json()
    assert t["headline"].startswith("Delivered") and all(s["done"] for s in t["steps"])
    assert t["shipments"] and WB.match(t["shipments"][0]["waybill"])
    on_way = client.get("/api/dispatch", params={"status": "dispatched"}).json()["loads"][0]
    t = client.get(f"/api/track/{on_way['waybill']}").json()
    assert t["eta"] and "arriving around" in t["headline"]
    assert client.get("/api/track/WB-0000-000").status_code == 404
    assert client.get("/api/track/%20").status_code in (400, 404)


def test_cancelling_empties_and_removes_a_loading_waybill(client):
    r = route(client, "SH-06")
    wb = client.post("/api/dispatch/waybill", json={"warehouse_id": r["warehouse_id"], "shelter_id": "SH-06"}).json()["waybill"]
    for rid in r["requests"]:
        client.post(f"/api/requests/{rid}/cancel")
    assert client.get(f"/api/track/{wb}").status_code == 404
    checks_pass(client)


def test_waybill_numbers_are_never_reused(client):
    r = route(client)
    first = client.post("/api/dispatch/waybill", json={"warehouse_id": r["warehouse_id"], "shelter_id": r["shelter_id"]}).json()
    client.post("/api/undo")
    second = client.post("/api/dispatch/waybill", json={"warehouse_id": r["warehouse_id"], "shelter_id": r["shelter_id"]}).json()
    assert first["waybill"] != second["waybill"]


def test_quick_find_finds_waybills(client):
    wb = client.get("/api/dispatch", params={"status": "delivered"}).json()["loads"][0]["waybill"]
    hits = client.get("/api/search", params={"q": wb}).json()["results"]
    assert hits[0]["type"] == "waybill" and hits[0]["track"] == wb
