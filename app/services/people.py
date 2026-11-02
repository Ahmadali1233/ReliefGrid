"""People, not boxes: turns units into "days of water for 320 people".

Each item can have a planning figure: how much one person needs, either per day (water, meals)
or once for their stay (a blanket, a share of a family tent). With a shelter's headcount that gives:

  - a size check on new requests ("50 days of water for 40 people: check the number?")
  - coverage per shelter ("water for 1.6 days"), and who got the least per person (a fairness check)
  - days of supply on the shelf for everyone sheltered
  - the optional "max days per shelter" allocation rule

Figures are editable on the Rules screen. The defaults below are starting points, not law.
"""

from ..db.database import get_conn, now

# item -> (per person, 'day' or 'stay', where the figure comes from)
DEFAULT_FIGURES = {
    "Water": (0.25, "day", "Sphere standard: 2.5–3 litres of drinking water per person per day. "
                           "A 12-litre carton covers 4 people."),
    "Ready meals": (3, "day", "Planning figure: 3 meals per person per day."),
    "Blankets": (1, "stay", "Planning figure: 1 blanket per person. Sphere asks for 'sufficient' bedding; "
                            "add more in cold weather."),
    "Tents": (0.2, "stay", "Planning figure: 1 family tent per 5 people (one household)."),
    "Hygiene kits": (0.2, "stay", "Planning figure: 1 family hygiene kit per 5 people (one household)."),
}

LARGE_REQUEST_DAYS = 14      # a daily item asked for beyond this many days gets a "check the number?"
LARGE_REQUEST_TIMES = 2      # a once-per-stay item asked for at more than twice the need gets one too


def seed_defaults(conn):
    for item, (per_person, per, basis) in DEFAULT_FIGURES.items():
        conn.execute("INSERT OR IGNORE INTO items (item, per_person, per, basis) VALUES (?, ?, ?, ?)",
                     (item, per_person, per, basis))


def figures(conn=None):
    """{item name (lower case): {item, per_person, per, basis}}"""
    conn = conn or get_conn()
    return {r["item"].lower(): dict(r) for r in conn.execute("SELECT * FROM items ORDER BY item")}


def figure_for(figs, item):
    return figs.get((item or "").lower())


def daily_need(people, fig):
    """Units per day a shelter of this size needs, or None if it can't be worked out."""
    if not people or not fig or fig["per"] != "day":
        return None
    return people * fig["per_person"]


def describe(units, people, fig, unit, item):
    """Plain words for how far some units go: '1.6 days for 320 people' or 'enough for 80 of 120 people'."""
    if not people or not fig:
        return None
    if fig["per"] == "day":
        days = units / (people * fig["per_person"])
        return f"{_days(days)} for {people:,} people"
    covered = min(int(units / fig["per_person"]), people) if fig["per_person"] else 0
    return f"enough for {covered:,} of {people:,} people"


def _days(d):
    if d < 1:
        hours = round(d * 24)
        return "less than an hour" if hours < 1 else f"{hours} hour{'s' if hours != 1 else ''}"
    return f"{d:.1f} days" if d < 10 else f"{round(d)} days"


def size_check(conn, shelter, item, quantity, exclude_request=None):
    """Is this request a sensible size for the shelter's headcount? Returns None when nothing can be said."""
    fig = figure_for(figures(conn), item)
    people = shelter["people"] if shelter else None
    if not fig or not people:
        return None
    others = conn.execute(
        "SELECT COALESCE(SUM(quantity), 0) AS n FROM requests WHERE shelter_id = ? AND lower(item) = lower(?) "
        "AND cancelled = 0 AND id != ?", (shelter["id"], item, exclude_request or "")).fetchone()["n"]
    unit = _unit(conn, item)
    out = {"people": people, "per": fig["per"], "basis": fig["basis"], "warning": None}
    if fig["per"] == "day":
        need = people * fig["per_person"]
        out["days"] = round(quantity / need, 1)
        out["days_with_others"] = round((quantity + others) / need, 1)
        out["text"] = f"{_days(quantity / need)} of {item.lower()} for {people:,} people"
        if out["days_with_others"] > LARGE_REQUEST_DAYS:
            extra = (f" Together with its other open {item.lower()} requests that's {_days(out['days_with_others'])}."
                     if others else "")
            out["warning"] = (f"That's {_days(quantity / need)} of {item.lower()} for {people:,} people.{extra} "
                              f"Requests usually cover a few days. Check the number?")
    else:
        need = max(round(people * fig["per_person"]), 1)
        out["need"] = need
        out["text"] = f"{quantity:,} {unit} for {people:,} people (planning figure: about {need:,})"
        if quantity + others > need * LARGE_REQUEST_TIMES:
            extra = f" ({quantity + others:,} with its other open requests)" if others else ""
            out["warning"] = (f"{quantity:,} {unit}{extra} for {people:,} people is more than twice the planning "
                              f"figure of about {need:,}. Check the number?")
    return out


def _unit(conn, item):
    r = conn.execute("SELECT unit FROM inventory WHERE lower(item) = lower(?) LIMIT 1", (item,)).fetchone()
    unit = (r["unit"] if r else "") or ""
    return item.lower() if not unit or unit == "units" or unit.lower() in item.lower() else unit


def coverage(conn=None):
    """Per shelter and item: what it was given, as days (daily items) or share of people covered (stay items).

    Only items the shelter asked for are included. 'given' counts everything allocated to it, whether
    still in the warehouse, on a truck or delivered.
    """
    conn = conn or get_conn()
    figs = figures(conn)
    rows = conn.execute(
        """SELECT r.shelter_id, s.name AS shelter_name, s.people, r.item,
                  SUM(CASE WHEN r.cancelled = 0 THEN r.quantity ELSE 0 END) AS requested,
                  SUM(CASE WHEN r.cancelled = 0 THEN r.allocated ELSE 0 END) AS given
           FROM requests r JOIN shelters s ON s.id = r.shelter_id
           GROUP BY r.shelter_id, r.item HAVING requested > 0""").fetchall()
    out = []
    for r in rows:
        fig = figure_for(figs, r["item"])
        rec = {"shelter_id": r["shelter_id"], "shelter_name": r["shelter_name"], "people": r["people"],
               "item": r["item"], "requested": r["requested"], "given": r["given"],
               "per": fig["per"] if fig else None, "days": None, "share": None}
        if fig and r["people"]:
            if fig["per"] == "day":
                rec["days"] = round(r["given"] / (r["people"] * fig["per_person"]), 2)
            else:
                need = r["people"] * fig["per_person"]
                rec["share"] = round(min(r["given"] / need, 1) * 100) if need else None
        out.append(rec)
    return out


def fairness(conn=None):
    """For each daily item: is it shared fairly per person among the shelters that asked for it?

    Fair share = everything given out / the daily need of all those shelters, in days. A shelter is flagged
    "short" when it is still waiting and has under half the fair share, and "well above" when it has more
    than three times the fair share and at least a week. Strict priority order can do this: a small
    critical shelter can take weeks of water while a big high-priority one gets none. The
    max_days_per_shelter rule fixes it.
    """
    from .allocation import load_rules
    conn = conn or get_conn()
    rule_days = load_rules(conn).get("max_days_per_shelter", 0)
    cov = [c for c in coverage(conn) if c["days"] is not None]
    figs = figures(conn)
    by_item = {}
    for c in cov:
        by_item.setdefault(c["item"], []).append(c)
    result = []
    for item, group in sorted(by_item.items()):
        if len(group) < 2:
            continue
        fig = figure_for(figs, item)
        need = sum(c["people"] * fig["per_person"] for c in group)
        given = sum(c["given"] for c in group)
        fair = round(given / need, 2) if need else 0
        group.sort(key=lambda c: c["days"])
        short = [c for c in group if c["given"] < c["requested"] and c["days"] < fair / 2]
        above = [c for c in reversed(group) if c["days"] > max(fair * 3, 7, rule_days + 0.5)]
        result.append({"item": item, "fair_days": fair, "lowest": group[0], "highest": group[-1],
                       "short": short, "above": above, "shelters": group, "rule_days": rule_days})
    return result


def totals(conn=None):
    conn = conn or get_conn()
    r = conn.execute("SELECT COALESCE(SUM(people), 0) AS people, SUM(people IS NULL) AS unknown, "
                     "COUNT(*) AS shelters FROM shelters").fetchone()
    return {"people": r["people"], "shelters_without_headcount": r["unknown"] or 0, "shelters": r["shelters"]}


def days_on_shelf(conn, item, units):
    """How many days the units on the shelf would last everyone sheltered (for daily items)."""
    fig = figure_for(figures(conn), item)
    if not fig or fig["per"] != "day":
        return None
    people = totals(conn)["people"]
    if not people:
        return None
    return round(units / (people * fig["per_person"]), 2)


def save_figures(items):
    """Replace the planning figures. items: [{item, per_person, per, basis}]"""
    from ..db.database import transaction
    from .history import snapshot
    from .allocation import run_allocation

    clean = []
    seen = set()
    for raw in items or []:
        name = " ".join(str(raw.get("item") or "").split())
        if not name:
            continue
        if name.lower() in seen:
            raise ValueError(f"{name} is listed twice.")
        seen.add(name.lower())
        try:
            per_person = float(raw.get("per_person"))
        except (TypeError, ValueError):
            raise ValueError(f"{name}: 'per person' must be a number, like 0.25 or 3.")
        if not 0 < per_person <= 1000:
            raise ValueError(f"{name}: 'per person' must be more than 0 and at most 1,000.")
        per = raw.get("per")
        if per not in ("day", "stay"):
            raise ValueError(f"{name}: choose 'per day' or 'once per stay'.")
        basis = " ".join(str(raw.get("basis") or "").split())[:200] or None
        clean.append((name, per_person, per, basis))
    with transaction() as conn:
        snapshot(conn, "change planning figures")
        conn.execute("DELETE FROM items")
        for row in clean:
            conn.execute("INSERT INTO items (item, per_person, per, basis) VALUES (?, ?, ?, ?)", row)
        conn.execute("INSERT INTO events (created_at, kind, message, data) VALUES (?, 'rules', ?, NULL)",
                     (now(), f"Planning figures updated ({len(clean)} items)"))
        run_allocation(conn, "planning figures changed")
    return {"items": [dict(zip(("item", "per_person", "per", "basis"), c)) for c in clean]}
