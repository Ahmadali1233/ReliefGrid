"""Quick find, the sitrep, the supply forecast and the what-if preview."""


def test_search_finds_shelters_requests_items(client):
    r = client.get("/api/search", params={"q": "bund"}).json()["results"]
    types = {x["type"] for x in r}
    assert "shelter" in types and "request" in types
    assert client.get("/api/search", params={"q": "REQ-039"}).json()["results"][0]["id"] == "REQ-039"
    assert any(x["type"] == "item" for x in client.get("/api/search", params={"q": "water"}).json()["results"])
    assert client.get("/api/search", params={"q": ""}).json()["results"] == []
    assert client.get("/api/search", params={"q": "zzzz-nothing"}).json()["results"] == []


def test_search_is_safe_with_odd_characters(client):
    for q in ["%", "_", "'", "\"; DROP TABLE requests;--", "<script>"]:
        assert client.get("/api/search", params={"q": q}).status_code == 200
    assert len(client.get("/api/requests").json()) == 48


def test_sitrep_is_shareable_text(client):
    text = client.get("/api/sitrep").json()["text"]
    assert "Critical: 19 of 20 covered." in text
    assert "540 cartons of water" in text
    assert "7/7 integrity checks passed" in text


def test_forecast_and_what_if(client):
    items = {i["item"]: i for i in client.get("/api/inventory").json()}
    assert items["Hygiene kits"]["hours_of_cover"] > 0
    assert items["Water"]["waiting_requests"] == 6
    p = client.get("/api/inventory/restock/preview", params={"item": "Water", "quantity": 540, "warehouse_id": "WH-A"}).json()
    assert p["critical_covered_after"] == p["critical_total"] == 20
    assert p["left_over"] == 0
    assert len(client.get("/api/requests").json()) == 48     # preview changed nothing
