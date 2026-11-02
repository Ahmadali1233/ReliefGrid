"""The log: newest first, every entry tied to its shelter, item and numbers; a believable sample day; clear undo."""
from datetime import datetime


def test_log_entries_are_sorted_grouped_and_linked(client):
    ev = client.get("/api/events").json()
    times = [e["created_at"] for e in ev]
    assert times == sorted(times, reverse=True)
    trucks = [e for e in ev if e["group"] == "trucks"]
    assert trucks and all(e["refs"][0].startswith("WB-") and e["shelters"] and e["items"] for e in trucks)
    req = next(e for e in ev if e["kind"] == "allocation")
    assert req["refs"][0].startswith("REQ-") and req["items"] and req["shelters"] and req["actor"]
    orders = [e for e in ev if e["group"] == "orders"]
    assert len(orders) == 3 and all(e["refs"][0].startswith("PO-") for e in orders)
    assert {e["actor"] for e in ev} >= {"Sana (hub)", "Usman (hub)", "Ayesha (head teacher)"}


def test_sample_day_happens_in_a_believable_order(client):
    now = datetime.now().isoformat(timespec="seconds")
    ev = client.get("/api/events").json()
    assert all(e["created_at"] <= now for e in ev)
    steps = {}
    for e in ev:
        if e["group"] == "trucks":
            steps.setdefault(e["refs"][0], {})[e["kind"]] = e["created_at"]
    for wb, s in steps.items():
        assert s["waybill"] <= s["dispatch"], wb
        if "delivered" in s:
            assert s["dispatch"] < s["delivered"], wb
    for l in client.get("/api/dispatch", params={"status": "dispatched"}).json()["loads"]:
        assert client.get(f"/api/track/{l['waybill']}").json()["eta"] > now[:16]     # still on the road


def test_undo_says_what_and_for_how_long(client):
    assert client.get("/api/undo").json()["label"] is None
    client.post("/api/requests", json={"shelter_id": "SH-07", "item": "Water", "quantity": 20, "urgency": "high"})
    u = client.get("/api/undo").json()
    assert u["label"].startswith("new request") and 0 < u["seconds_left"] <= 600 and u["at"]
    assert client.post("/api/undo").status_code == 200
    assert client.get("/api/events", params={"kind": "undo"}).json()[0]["group"] == "undo"
