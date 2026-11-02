"""Tests for the plain-English command bar, the sitrep and the forecast."""

import pytest


@pytest.mark.parametrize("text, action, params", [
    ("Al Qusais needs 50 tents urgently", "request",
     {"shelter_id": "SH-04", "item": "Tents", "quantity": 50, "urgency": "critical"}),
    ("Karama hall wants 40 hygiene kits soon", "request",
     {"shelter_id": "SH-03", "item": "Hygiene kits", "quantity": 40, "urgency": "high"}),
    ("deira 30 meals p1", "request", {"shelter_id": "SH-01", "item": "Ready meals", "quantity": 30, "urgency": "critical"}),
    ("500 water arrived at warehouse A", "restock", {"warehouse_id": "WH-A", "item": "Water", "quantity": 500}),
    ("300 blankets delivered to Jebel Ali", "restock", {"warehouse_id": "WH-B", "item": "Blankets", "quantity": 300}),
    ("1,200 water came in", "restock", {"warehouse_id": "WH-A", "item": "Water", "quantity": 1200}),
    ("cancel req-012", "cancel", {"id": "REQ-012"}),
    ("why REQ-039", "why", {"id": "REQ-039"}),
    ("show waiting", "goto", {"route": "requests?status=waiting"}),
])
def test_commands_understood(client, text, action, params):
    r = client.get("/api/command", params={"text": text}).json()
    assert r["action"] == action, r
    assert r.get("params") == params


def test_request_without_urgency_defaults_to_moderate_and_says_so(client):
    r = client.get("/api/command", params={"text": "Jebel Ali Camp needs 20 first aid kits"}).json()
    assert r["params"]["urgency"] == "moderate" and "urgent" in r["summary"]


@pytest.mark.parametrize("text", ["", "banana", "hatta needs water", "cancel REQ-999"])
def test_unclear_commands_get_help_not_errors(client, text):
    r = client.get("/api/command", params={"text": text})
    assert r.status_code == 200
    assert r.json()["action"] is None and r.json()["message"]


def test_parsed_command_can_be_executed(client):
    p = client.get("/api/command", params={"text": "Al Qusais needs 10 tents urgently"}).json()
    r = client.post("/api/requests", json=p["params"])
    assert r.status_code == 201 and r.json()["given"] == 10


def test_sitrep_is_shareable_text(client):
    text = client.get("/api/sitrep").json()["text"]
    assert "Critical: 19 of 20 covered." in text
    assert "540 cartons of water" in text
    assert "6/6 integrity checks passed" in text


def test_forecast_and_what_if(client):
    items = {i["item"]: i for i in client.get("/api/inventory").json()}
    assert items["Hygiene kits"]["hours_of_cover"] > 0
    p = client.get("/api/inventory/restock/preview", params={"item": "Water", "quantity": 540, "warehouse_id": "WH-A"}).json()
    assert p["critical_covered_after"] == p["critical_total"] == 20
    assert p["left_over"] == 0
