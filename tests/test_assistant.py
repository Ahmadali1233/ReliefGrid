"""The command bar: plain words in, an answer or a previewed action out. Nothing changes until the action is run."""


def ask(client, q):
    r = client.get("/api/ask", params={"q": q})
    assert r.status_code == 200, r.text
    return r.json()


def run(client, a):
    c = a["call"]
    return client.request(c["method"], c["path"], json=c.get("body"))


def test_a_shelter_needs_something(client):
    before = len(client.get("/api/requests").json())
    a = ask(client, "Johi Tent City needs 200 water, critical")
    assert a["type"] == "action"
    assert a["call"]["body"] == {"shelter_id": "SH-07", "item": "Water", "quantity": 200, "urgency": "critical"}
    assert len(client.get("/api/requests").json()) == before          # asking changed nothing
    assert run(client, a).status_code == 201
    assert len(client.get("/api/requests").json()) == before + 1


def test_shelter_words_are_not_mistaken_for_items(client):
    # "Tent" is part of the shelter's name, not the item asked for.
    a = ask(client, "johi tent city 50 blankets")
    assert a["call"]["body"]["item"] == "Blankets" and a["call"]["body"]["shelter_id"] == "SH-07"
    assert a["call"]["body"]["urgency"] == "high" and any("Urgency" in l for l in a["lines"])
    a = ask(client, "SH-8 needs 3 tents urgent")
    assert a["call"]["body"] == {"shelter_id": "SH-08", "item": "Tents", "quantity": 3, "urgency": "critical"}


def test_synonyms_and_numbers_with_commas(client):
    a = ask(client, "Dadu Girls High School needs 1,200 food")
    assert a["call"]["body"]["item"] == "Ready meals" and a["call"]["body"]["quantity"] == 1200
    assert ask(client, "dadu girls school 40 formula moderate")["call"]["body"]["item"] == "Baby milk"


def test_stock_questions(client):
    a = ask(client, "How much baby milk do we have?")
    assert a["type"] == "answer" and a["title"].startswith("Baby milk")
    assert any("Warehouse A" in l for l in a["lines"])
    a = ask(client, "who is waiting for water")
    assert a["type"] == "answer" and "waiting for water" in a["title"] and a["lines"]


def test_restock_needs_a_warehouse_then_previews(client):
    assert ask(client, "received 300 water")["title"] == "Which warehouse?"
    a = ask(client, "received 300 water at warehouse A")
    assert a["call"]["body"] == {"warehouse_id": "WH-A", "item": "Water", "quantity": 300}
    assert a["lines"][0].startswith("Fills")
    assert run(client, a).status_code in (200, 201)


def test_track_and_cancel_by_number(client):
    wb = client.get("/api/dispatch", params={"status": "dispatched"}).json()["loads"][0]["waybill"]
    a = ask(client, f"where is {wb.lower()}?")
    assert a["type"] == "answer" and a["title"].startswith(wb) and a["links"][0]["track"] == wb
    a = ask(client, "cancel req-3")
    assert a["type"] == "action" and a["call"]["path"] == "/api/requests/REQ-003/cancel"


def test_cap_order_undo_and_pages(client):
    a = ask(client, "cap at 7 days")
    assert a["call"]["body"] == {"max_days_per_shelter": 7}
    assert run(client, a).json()["released"] > 0
    u = ask(client, "undo")
    assert u["type"] == "action" and u["call"]["path"] == "/api/undo"
    assert run(client, u).status_code == 200
    o = ask(client, "order 48 baby milk and 200 water")
    assert o["type"] == "open" and o["prefill"] == [{"item": "Baby milk", "quantity": 48}, {"item": "Water", "quantity": 200}]
    o = ask(client, "reorder")
    assert {"item": "Water", "quantity": 540} in o["prefill"]
    assert ask(client, "go to dispatch") == {"type": "navigate", "title": "Open Dispatch", "route": "dispatch"}
    assert ask(client, "log")["route"] == "log"


def test_unclear_input_falls_back_to_search(client):
    a = ask(client, "johi")
    assert a["type"] in ("answer", "results")
    a = ask(client, "zzzz qqqq")
    assert a["type"] == "results" and a["examples"]
    assert ask(client, "")["type"] == "help"
