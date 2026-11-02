"""Import tests: CSV, JSON, XML, unknown column names, and messy rows."""

import json

import pytest

from app.importers.mapper import detect
from app.importers.parse import FileFormatError, parse_file

SAMPLE = "data/sample/"


def upload(client, name, content, endpoint="preview", **form):
    data = {k: (json.dumps(v) if isinstance(v, dict) else v) for k, v in form.items()}
    return client.post(f"/api/import/{endpoint}", files={"file": (name, content)}, data=data)


def test_messy_csv_keeps_good_rows_and_explains_bad_ones(client):
    with open(SAMPLE + "messy_requests.csv", "rb") as f:
        p = upload(client, "messy_requests.csv", f.read()).json()
    assert p["entity"] == "requests"
    assert p["mapping"] == {"req_no": "id", "site": "shelter_id", "supply": "item", "units": "quantity",
                            "level": "urgency"}
    assert p["ready"] == 4
    messages = {i["row"]: i["message"] for i in p["issues"]}
    assert "can't be negative" in messages[3]
    assert "SH-99" in messages[4]
    assert "isn't a number" in messages[5]
    assert "whole number" in messages[6]
    assert "same ID as row 2" in messages[7]
    assert "no item" in messages[8]
    assert any("ASAP" in w["message"] for w in p["warnings"])


def test_messy_csv_commit_then_integrity(client):
    with open(SAMPLE + "messy_requests.csv", "rb") as f:
        r = upload(client, "messy_requests.csv", f.read(), "commit").json()
    assert r["imported"] == 4 and len(r["skipped"]) == 6
    ids = {x["id"] for x in client.get("/api/requests").json()}
    assert {"REQ-101", "REQ-108", "REQ-109"} <= ids
    item = next(x for x in client.get("/api/requests").json() if x["id"] == "REQ-108")["item"]
    assert item == "Ready meals"                     # "ready meals " matched the existing item
    checks = client.get("/api/integrity").json()
    assert checks["passed"] == checks["total"]


def test_xml_with_different_column_names(client):
    with open(SAMPLE + "requests_day2.xml", "rb") as f:
        r = upload(client, "requests_day2.xml", f.read(), "commit").json()
    assert r["entity"] == "requests" and r["imported"] == 4


def test_json_delivery_restocks_inventory(client):
    before = {s["item"]: s["total"] for s in client.get("/api/inventory").json()}
    with open(SAMPLE + "delivery_truck.json", "rb") as f:
        r = upload(client, "delivery_truck.json", f.read(), "commit").json()
    assert r["entity"] == "inventory" and r["imported"] == 2
    assert r["requests_served"] > 0                   # the water went straight to waiting shelters
    after = {s["item"]: s["total"] for s in client.get("/api/inventory").json()}
    assert after["Water"] <= before["Water"] + 380


def test_mapping_can_be_overridden_and_is_remembered(client):
    content = b"code,place,thing,how_many,when\nX-1,SH-01,Water,5,high\n"
    p = upload(client, "odd.csv", content).json()
    assert p["mapping_error"]                         # can't guess these names
    mapping = {"code": "id", "place": "shelter_id", "thing": "item", "how_many": "quantity", "when": "urgency"}
    p = upload(client, "odd.csv", content, entity="requests", mapping=mapping).json()
    assert p["ready"] == 1 and p["mapping_error"] is None
    upload(client, "odd.csv", content, "commit", entity="requests", mapping=mapping)
    p = upload(client, "odd2.csv", b"code,place,thing,how_many,when\nX-2,SH-01,Water,5,high\n").json()
    assert p["remembered"] and p["mapping"] == mapping


def test_tsv_and_semicolon_files(client):
    tsv = b"warehouse\titem\tqty\nWH-A\tTents\t10\n"
    p = upload(client, "stock.tsv", tsv).json()
    assert p["entity"] == "inventory" and p["ready"] == 1
    semi = b"warehouse;item;qty\nWH-B;Tents;4\n"
    assert upload(client, "stock.csv", semi).json()["ready"] == 1


def test_shelters_with_combined_coordinates(client):
    content = b"site_id,site_name,priority,coordinates\nSH-20,Al Nahda Hall,1,\"25.29, 55.37\"\nSH-21,No Coords,2,\n"
    r = upload(client, "shelters.csv", content, "commit").json()
    assert r["entity"] == "shelters" and r["imported"] == 2
    assert any("map" in w["message"] for w in r["warnings"])
    s = next(x for x in client.get("/api/shelters").json()["shelters"] if x["id"] == "SH-20")
    assert (s["lat"], s["lon"], s["priority"]) == (25.29, 55.37, 1)


def test_duplicate_stock_rows_are_merged(client):
    content = b"warehouse_id,item,quantity\nWH-A,Tents,5\nWH-A,tents,7\n"
    p = upload(client, "stock.csv", content).json()
    assert p["ready"] == 1 and p["warnings"]


@pytest.mark.parametrize("name, content, message", [
    ("empty.csv", b"", "empty"),
    ("blank.csv", b"   \n\n", "empty"),
    ("header.csv", b"a,b,c\n", "no data rows"),
    ("broken.json", b"{\"a\": [1,", "JSON is broken"),
    ("wrong.json", b"42", "list of records"),
    ("broken.xml", b"<a><b></a>", "XML is broken"),
    ("junk.csv", bytes([0, 255, 254, 1, 2, 3, 200, 13, 10, 0, 0]), "isn't readable text"),
    ("sheet.xlsx", b"PK\x03\x04\x14\x00\x06\x00\x08\x00\x00\x00!\x00binarystuff\x01\x02\x03\x04", "isn't readable text"),
])
def test_unreadable_files_get_clear_messages(name, content, message):
    with pytest.raises(FileFormatError) as e:
        parse_file(content, name)
    assert message in str(e.value)


def test_unreadable_file_via_api_is_400(client):
    r = upload(client, "broken.json", b"{oops")
    assert r.status_code == 400 and "JSON is broken" in r.json()["error"]


def test_nothing_importable_is_rejected_without_changes(client):
    before = len(client.get("/api/requests").json())
    r = upload(client, "bad.csv", b"request_id,shelter_id,item,quantity,urgency\nX,SH-99,Water,5,high\n", "commit")
    assert r.status_code == 400
    assert len(client.get("/api/requests").json()) == before


def test_detect_prefers_numeric_units_column_for_quantity():
    cols = ["warehouse", "item", "units"]
    rows = [{"warehouse": "WH-A", "item": "Water", "units": "10", "__row": 2}]
    entity, mapping, _ = detect(cols, rows)
    assert entity == "inventory" and mapping["units"] == "quantity"
