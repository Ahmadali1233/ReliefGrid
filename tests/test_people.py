"""People, not boxes: headcounts, planning figures, request size checks, fair share and the days-of-supply rule."""

from app.engine import allocate
from conftest import make_request


def checks_pass(client):
    c = client.get("/api/integrity").json()
    assert c["passed"] == c["total"], [x for x in c["checks"] if not x["passed"]]


# ---------- Size check ----------

def test_preview_flags_a_request_too_big_for_the_headcount(client):
    # Moro Rural Health Centre has 60 people; 400 cartons is 27 days of drinking water.
    p = client.get("/api/requests/preview", params={"shelter_id": "SH-08", "item": "Water", "quantity": 400,
                                                    "urgency": "high"}).json()
    assert p["size"]["people"] == 60 and p["size"]["days"] > 14
    assert "Check the number" in p["size"]["warning"]


def test_preview_explains_a_sensible_request_without_warning(client):
    p = client.get("/api/requests/preview", params={"shelter_id": "SH-01", "item": "Water", "quantity": 200,
                                                    "urgency": "high"}).json()
    # 400 people x 0.25 cartons a day = 100 a day, so 200 is 2 days (plus its open 150 = 3.5 days).
    assert p["size"]["days"] == 2.0 and p["size"]["warning"] is None
    assert "2.0 days of water for 400 people" in p["size"]["text"]


def test_stay_items_are_checked_against_people_not_days(client):
    # 40 people would need about 8 tents (1 per 5 people); 50 is far more than twice that.
    client.post("/api/shelters", json={"id": "SH-40", "name": "Test Hall", "priority": 2, "people": 40})
    p = client.get("/api/requests/preview", params={"shelter_id": "SH-40", "item": "Tents", "quantity": 50,
                                                    "urgency": "high"}).json()
    assert p["size"]["need"] == 8 and p["size"]["warning"]


def test_no_size_check_without_a_headcount_or_figure(client):
    client.post("/api/shelters", json={"id": "SH-41", "name": "Unknown Hall", "priority": 2})
    assert client.get("/api/requests/preview", params={"shelter_id": "SH-41", "item": "Water", "quantity": 9999,
                                                       "urgency": "high"}).json()["size"] is None
    assert client.get("/api/requests/preview", params={"shelter_id": "SH-01", "item": "First aid kits",
                                                       "quantity": 9999, "urgency": "high"}).json()["size"] is None


def test_request_list_marks_oversized_requests(client):
    flagged = {r["id"] for r in client.get("/api/requests").json() if r["size_warning"]}
    # Indus Bund Health Post: 50 people, 510 cartons of water across three requests = 41 days.
    assert flagged == {"REQ-001", "REQ-015", "REQ-029"}


# ---------- Fair share ----------

def test_fair_share_spots_the_imbalance_strict_priority_creates(client):
    water = next(f for f in client.get("/api/summary").json()["fairness"] if f["item"] == "Water")
    assert water["above"][0]["shelter_id"] == "SH-14" and water["above"][0]["days"] > 30
    assert {c["shelter_id"] for c in water["short"]} >= {"SH-01", "SH-04"}


def test_days_rule_releases_reserved_stock_and_serves_others(client):
    before = {r["id"]: r for r in client.get("/api/requests").json()}
    r = client.put("/api/rules", json={"max_days_per_shelter": 7}).json()
    assert r["released"] > 400 and r["requests_served"] > 0
    after = {r["id"]: r for r in client.get("/api/requests").json()}
    sh14 = sum(x["allocated"] for x in after.values() if x["shelter_id"] == "SH-14" and x["item"] == "Water")
    assert sh14 == 88                                   # ceil(50 people x 0.25 x 7 days)
    assert after["REQ-048"]["allocated"] > before["REQ-048"]["allocated"]   # Dadu Girls High School (400 people) now gets water
    why = client.get("/api/requests/REQ-029/explain").json()
    assert any("7-day rule" in s for s in why["steps"])
    held = client.get("/api/summary").json()["held_by_rule"]
    assert {h["request_id"] for h in held} >= {"REQ-015", "REQ-029"}
    checks_pass(client)
    assert client.post("/api/undo").status_code == 200
    restored = {r["id"]: r["allocated"] for r in client.get("/api/requests").json()}
    assert restored == {k: v["allocated"] for k, v in before.items()}


def test_days_rule_never_touches_stock_on_a_truck(client):
    loads = client.get("/api/dispatch", params={"status": "allocated"}).json()["loads"]
    sh14 = [l for l in loads if l["shelter_id"] == "SH-14" and any(i["item"] == "Water" for i in l["items"])][0]
    client.post("/api/dispatch/dispatched", json={"warehouse_id": sh14["warehouse_id"], "shelter_id": "SH-14",
                                                  "driver": "Truck 1"})
    r = client.put("/api/rules", json={"max_days_per_shelter": 7}).json()
    assert r["released"] < 100       # only the medical camp's blankets and other shelters can move; its water is on the road
    on_road = [l for l in client.get("/api/dispatch", params={"status": "dispatched"}).json()["loads"]
               if l["shelter_id"] == "SH-14"]
    assert sum(i["quantity"] for l in on_road for i in l["items"] if i["item"] == "Water") == 510
    checks_pass(client)


def test_engine_days_cap():
    reqs = [make_request("A", quantity=100, urgency="critical", shelter="S1", priority=1),
            make_request("B", quantity=100, urgency="high", shelter="S2")]
    reqs[0]["daily_need"] = 5        # e.g. 20 people x 0.25 cartons
    decisions, _ = allocate(reqs, {("W", "Water"): 120}, {"W": (26.74, 67.79)}, {"max_days_per_shelter": 3})
    a, b = decisions
    assert a.given == 15 and a.capped and a.cap_kind == "days" and a.cap_limit == 15
    assert b.given == 100
    # Off by default: strict priority.
    decisions, _ = allocate(reqs, {("W", "Water"): 120}, {"W": (26.74, 67.79)})
    assert decisions[0].given == 100 and decisions[1].given == 20


def test_days_rule_validation(client):
    assert client.put("/api/rules", json={"max_days_per_shelter": -1}).status_code == 400
    assert client.put("/api/rules", json={"max_days_per_shelter": 400}).status_code == 400


# ---------- Headcounts ----------

def test_update_headcount(client):
    r = client.patch("/api/shelters/SH-01", json={"people": 520})
    assert r.status_code == 200 and r.json()["people"] == 520
    s = next(x for x in client.get("/api/shelters").json()["shelters"] if x["id"] == "SH-01")
    assert s["people"] == 520
    assert client.patch("/api/shelters/SH-01", json={"clear_people": True}).json()["people"] is None
    log = client.get("/api/events?kind=shelter").json()
    assert "headcount 520 → unknown" in log[0]["message"]


def test_bad_headcounts_are_refused(client):
    assert client.patch("/api/shelters/SH-01", json={"people": -5}).status_code == 400
    assert client.patch("/api/shelters/SH-01", json={"people": True}).status_code == 400
    assert client.patch("/api/shelters/SH-01", json={"people": "lots"}).status_code == 400
    assert client.patch("/api/shelters/SH-99", json={"people": 10}).status_code == 404
    assert client.patch("/api/shelters/SH-01", json={"people": 400}).status_code == 400    # nothing changed
    assert client.post("/api/shelters", json={"id": "SH-50", "name": "X", "people": 2.5}).status_code == 400


def test_import_shelters_with_a_population_column(client):
    csv = b"code,shelter_name,Population,lat,lon\nSH-60,North Hall,220,25.3,55.4\nSH-61,South Hall,many,25.1,55.2\n"
    r = client.post("/api/import/commit", files={"file": ("sites.csv", csv, "text/csv")},
                    data={"entity": "shelters"}).json()
    assert r["imported"] == 2
    assert any("headcount" in w["message"] for w in r["warnings"])
    people = {s["id"]: s["people"] for s in client.get("/api/shelters").json()["shelters"]}
    assert people["SH-60"] == 220 and people["SH-61"] is None


# ---------- Planning figures ----------

def test_planning_figures_round_trip_and_validation(client):
    figs = client.get("/api/figures").json()
    assert {f["item"] for f in figs["items"]} >= {"Water", "Ready meals", "Blankets"}
    assert figs["people"]["people"] == 3430
    bad = [
        {"items": [{"item": "Water", "per_person": 0, "per": "day"}]},
        {"items": [{"item": "Water", "per_person": "lots", "per": "day"}]},
        {"items": [{"item": "Water", "per_person": 1, "per": "weekly"}]},
        {"items": [{"item": "Water", "per_person": 1, "per": "day"}, {"item": "water", "per_person": 2, "per": "day"}]},
        {"nope": []},
    ]
    for body in bad:
        assert client.put("/api/figures", json=body).status_code == 400, body
    ok = client.put("/api/figures", json={"items": [{"item": "First aid kits", "per_person": 0.02, "per": "stay",
                                                     "basis": "1 kit per 50 people"}]})
    assert ok.status_code == 200
    assert [f["item"] for f in client.get("/api/figures").json()["items"]] == ["First aid kits"]
    # Water has no figure now, so no size warnings for it.
    assert not any(r["size_warning"] for r in client.get("/api/requests").json() if r["item"] == "Water")


def test_network_for_the_relief_web(client):
    net = client.get("/api/network").json()
    assert len(net["shelters"]) == 14 and len(net["warehouses"]) == 2
    assert {s["state"] for s in net["shelters"]} <= {"waiting", "to_load", "on_the_way", "delivered", "none"}
    assert all(l["allocated"] + l["dispatched"] + l["delivered"] > 0 for l in net["links"])
    assert net["people"]["people"] == 3430
