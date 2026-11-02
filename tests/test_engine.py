"""Unit tests for the allocation engine (pure functions, no database)."""

import pytest

from app.engine import allocate, explain, normalize_urgency
from conftest import make_request as req

WAREHOUSES = {"NEAR": (25.20, 55.30), "FAR": (25.00, 55.00)}


def given(decisions):
    return {d.request_id: d.given for d in decisions}


def test_critical_before_high_before_moderate():
    reqs = [req("M", urgency="moderate"), req("H", urgency="high"), req("C", urgency="critical")]
    decisions, _ = allocate(reqs, {("NEAR", "Water"): 15}, WAREHOUSES)
    assert [d.request_id for d in decisions] == ["C", "H", "M"]
    assert given(decisions) == {"C": 10, "H": 5, "M": 0}


def test_shelter_priority_breaks_urgency_ties():
    reqs = [req("P3", urgency="high", priority=3), req("P1", urgency="high", priority=1)]
    decisions, _ = allocate(reqs, {("NEAR", "Water"): 10}, WAREHOUSES)
    assert given(decisions) == {"P1": 10, "P3": 0}


def test_earlier_request_wins_when_everything_else_ties():
    reqs = [req("LATE", created="2026-10-31T12:00:00"), req("EARLY", created="2026-10-31T08:00:00")]
    decisions, _ = allocate(reqs, {("NEAR", "Water"): 10}, WAREHOUSES)
    assert given(decisions) == {"EARLY": 10, "LATE": 0}


def test_request_id_is_final_tie_break():
    reqs = [req("B"), req("A")]
    decisions, _ = allocate(reqs, {("NEAR", "Water"): 10}, WAREHOUSES)
    assert given(decisions) == {"A": 10, "B": 0}


def test_partial_fill_when_stock_runs_short():
    decisions, after = allocate([req("R", quantity=100)], {("NEAR", "Water"): 40}, WAREHOUSES)
    d = decisions[0]
    assert (d.given, d.remaining, d.status) == (40, 60, "partial")
    assert after[("NEAR", "Water")] == 0


def test_stock_never_goes_negative():
    reqs = [req(f"R{i}", quantity=50) for i in range(10)]
    _, after = allocate(reqs, {("NEAR", "Water"): 120, ("FAR", "Water"): 30}, WAREHOUSES)
    assert all(v >= 0 for v in after.values())
    assert sum(after.values()) == 0


def test_negative_stock_input_is_rejected():
    with pytest.raises(ValueError):
        allocate([req("R")], {("NEAR", "Water"): -5}, WAREHOUSES)


def test_zero_stock_means_unfilled_not_a_crash():
    decisions, _ = allocate([req("R", quantity=5)], {("NEAR", "Water"): 0}, WAREHOUSES)
    assert decisions[0].status == "unfilled"


def test_item_not_stocked_at_all():
    decisions, _ = allocate([req("R", item="Generators")], {("NEAR", "Water"): 100}, WAREHOUSES)
    assert decisions[0].given == 0 and decisions[0].status == "unfilled"


def test_nearest_warehouse_first_then_next_nearest():
    decisions, after = allocate([req("R", quantity=30)], {("NEAR", "Water"): 20, ("FAR", "Water"): 50}, WAREHOUSES)
    takes = [(t.warehouse_id, t.quantity) for t in decisions[0].takes]
    assert takes == [("NEAR", 20), ("FAR", 10)]
    assert after == {("NEAR", "Water"): 0, ("FAR", "Water"): 40}


def test_already_allocated_requests_only_get_the_rest():
    decisions, _ = allocate([req("R", quantity=100, allocated=70)], {("NEAR", "Water"): 500}, WAREHOUSES)
    assert decisions[0].given == 30 and decisions[0].status == "fulfilled"


def test_fully_allocated_requests_are_skipped():
    decisions, _ = allocate([req("R", quantity=10, allocated=10)], {("NEAR", "Water"): 500}, WAREHOUSES)
    assert decisions == []


def test_input_stock_is_not_modified():
    stock = {("NEAR", "Water"): 10}
    allocate([req("R", quantity=10)], stock, WAREHOUSES)
    assert stock == {("NEAR", "Water"): 10}


def test_same_answer_regardless_of_input_order():
    reqs = [req(f"R{i}", quantity=7, urgency=["critical", "high", "moderate"][i % 3], priority=i % 3 + 1)
            for i in range(30)]
    stock = {("NEAR", "Water"): 60, ("FAR", "Water"): 40}
    a, _ = allocate(reqs, stock, WAREHOUSES)
    b, _ = allocate(list(reversed(reqs)), dict(reversed(list(stock.items()))), WAREHOUSES)
    assert given(a) == given(b)


def test_reserve_for_critical_holds_stock_back():
    reqs = [req("M", urgency="moderate", quantity=100), req("C", urgency="critical", quantity=10,
                                                              created="2026-10-31T23:00:00")]
    decisions, _ = allocate(reqs, {("NEAR", "Water"): 100}, WAREHOUSES, {"reserve_for_critical_pct": 20})
    g = given(decisions)
    assert g["C"] == 10          # critical goes first and may use any stock
    assert g["M"] == 70          # 90 left, 20 held back for critical, so moderate gets 70


def test_cap_per_shelter():
    reqs = [req("A", quantity=50, shelter="S1"), req("B", quantity=50, shelter="S1", created="2026-10-31T11:00:00")]
    decisions, _ = allocate(reqs, {("NEAR", "Water"): 500}, WAREHOUSES, {"max_per_shelter_per_item": 60})
    assert given(decisions) == {"A": 50, "B": 10}
    assert decisions[1].capped


def test_items_are_independent():
    reqs = [req("W", item="Water", quantity=10), req("T", item="Tents", quantity=3)]
    decisions, _ = allocate(reqs, {("NEAR", "Water"): 0, ("NEAR", "Tents"): 5}, WAREHOUSES)
    assert given(decisions) == {"W": 0, "T": 3}


@pytest.mark.parametrize("raw, expected", [
    ("Critical", "critical"), ("P1", "critical"), ("urgent", "critical"), ("HIGH", "high"),
    ("p2", "high"), ("Moderate", "moderate"), ("medium", "moderate"), ("3", "moderate"),
])
def test_urgency_aliases(raw, expected):
    assert normalize_urgency(raw) == (expected, True)


def test_unknown_urgency_becomes_moderate_and_is_flagged():
    assert normalize_urgency("ASAP!!") == ("moderate", False)


def test_explanation_mentions_the_reason():
    reqs = [req("A", quantity=60, urgency="critical"), req("B", quantity=100)]
    decisions, _ = allocate(reqs, {("NEAR", "Water"): 100}, WAREHOUSES)
    why = explain(decisions[1], "Test Shelter", {"NEAR": "Warehouse Near"}, "cartons", 2, {})
    text = why["headline"] + " ".join(why["steps"])
    assert "40 of 100 cartons of water" in why["headline"]
    assert "2nd in line" in text and "took 60" in text and "still needs 60" in text
