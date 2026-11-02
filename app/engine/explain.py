"""Turns a Decision into plain English for the "Why?" panel."""


def _ordinal(n):
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _n(x):
    return f"{x:,}"


def explain(d, shelter_name, warehouse_names, unit, shelter_priority, rules):
    """Return {"headline": str, "steps": [str, ...]} explaining one decision."""
    what = d.item.lower()
    unit = (unit or "").strip().lower()
    if not unit or unit == "units":
        noun = what                       # "40 of 100 tents"
    elif unit in what:
        noun = what                       # unit "blankets", item "Blankets" -> "blankets"
    else:
        noun = f"{unit} of {what}"        # "40 of 100 cartons of water"
    headline = f"{shelter_name} has {_n(d.total)} of {_n(d.requested)} {noun} reserved."
    if d.status == "fulfilled":
        headline = f"All {_n(d.requested)} {noun} for {shelter_name} are reserved."

    steps = []
    if d.already:
        steps.append(f"It already had {_n(d.already)} reserved from an earlier allocation.")

    order = f"{d.urgency.title()} urgency, shelter priority {shelter_priority}"
    if d.ahead_count == 0:
        steps.append(f"It was first in line for {what} ({order}), with {_n(d.stock_at_turn)} in stock.")
    else:
        plural = "request" if d.ahead_count == 1 else "requests"
        steps.append(
            f"It was {_ordinal(d.rank_in_item)} in line for {what} ({order}). "
            f"The {d.ahead_count} {plural} ahead of it took {_n(d.used_ahead)}, "
            f"leaving {_n(d.stock_at_turn)} at its turn."
        )

    if d.reserve_held:
        steps.append(
            f"{_n(d.reserve_held)} were held back for Critical requests "
            f"(reserve rule: {rules.get('reserve_for_critical_pct', 0)}%)."
        )
    if d.capped and d.cap_kind == "days":
        steps.append(
            f"The {rules.get('max_days_per_shelter', 0)}-day rule caps each shelter at "
            f"{rules.get('max_days_per_shelter', 0)} days of {what} for its headcount ({_n(d.cap_limit)} here), "
            f"so it could take {_n(d.eligible)} more at most."
        )
    elif d.capped:
        steps.append(
            f"The rules cap each shelter at {_n(rules.get('max_per_shelter_per_item', 0))} "
            f"{what}, so it could take {_n(d.eligible)} more at most."
        )

    if d.takes:
        parts = []
        for t in d.takes:
            name = warehouse_names.get(t.warehouse_id, t.warehouse_id)
            dist = f", {t.distance_km:g} km away" if t.distance_km is not None else ""
            parts.append(f"{_n(t.quantity)} from {name}{dist}")
        steps.append("Reserved " + " and ".join(parts) + ".")
        if len(d.takes) > 1:
            steps.append("The nearest warehouse ran short, so the next nearest topped it up.")
    elif d.given == 0 and d.remaining > 0:
        steps.append("There was nothing left it was allowed to use.")

    if d.remaining > 0 and not d.capped:
        steps.append(
            f"It still needs {_n(d.remaining)}. When more {what} arrives it is served "
            f"before anything less urgent."
        )
    elif d.remaining > 0 and d.capped:
        steps.append(f"It still lists {_n(d.remaining)} unmet, but it has reached the shelter cap.")
    else:
        steps.append("Fully reserved. Next step: load it on a truck from the Dispatch screen.")

    return {"headline": headline, "steps": steps}
