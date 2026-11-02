"""Priority rules for ReliefGrid.

Everything about *who goes first* lives in this file. To change the order or add
a rule on competition day, start here — the API and the screens don't need to change.
"""

# Served in this order: index 0 goes first. (Brief: Critical > High > Moderate)
URGENCY_LEVELS = ["critical", "high", "moderate"]
URGENCY_RANK = {name: rank for rank, name in enumerate(URGENCY_LEVELS)}

# Anything people might type for urgency, mapped to our three levels.
URGENCY_ALIASES = {
    "critical": "critical", "crit": "critical", "urgent": "critical", "emergency": "critical",
    "p1": "critical", "1": "critical", "c": "critical", "red": "critical",
    "high": "high", "hi": "high", "p2": "high", "2": "high", "h": "high", "orange": "high",
    "moderate": "moderate", "medium": "moderate", "med": "moderate", "normal": "moderate",
    "low": "moderate", "p3": "moderate", "3": "moderate", "m": "moderate", "routine": "moderate",
}

# Rule toggles. All are "off" by default; the Rules screen and PUT /api/rules change them.
DEFAULT_RULES = {
    # Percent of each item's stock that only Critical requests may use (0 = off).
    "reserve_for_critical_pct": 0,
    # Most units of one item a single shelter can receive in total (0 = no cap).
    "max_per_shelter_per_item": 0,
    # Most days of a daily item (water, meals) a shelter can receive for its headcount (0 = off).
    # Stops one small shelter taking weeks of water while a big one has none. Needs headcounts.
    "max_days_per_shelter": 0,
    # An item is "low" when its stock falls below this percent of the most it has held.
    "low_stock_pct": 15,
}


def normalize_urgency(value):
    """Return (urgency, recognised). Unknown values become 'moderate' with recognised=False."""
    key = str(value or "").strip().lower().replace(" ", "")
    if key in URGENCY_ALIASES:
        return URGENCY_ALIASES[key], True
    return "moderate", False


def sort_key(request):
    """The order requests are served in. Ties are always broken, so results never change between runs.

    1. Urgency (Critical first)
    2. Shelter priority (1 = most vulnerable, served first)
    3. Time the request was submitted (earlier first)
    4. Request ID (alphabetical) — a final, guaranteed tie-break
    """
    return (
        URGENCY_RANK.get(request["urgency"], len(URGENCY_LEVELS)),
        request.get("shelter_priority") or 99,
        request.get("created_at") or "",
        request["id"],
    )


def clean_rules(raw):
    """Merge user-supplied rule values over the defaults, rejecting nonsense."""
    rules = dict(DEFAULT_RULES)
    for key, value in (raw or {}).items():
        if key not in DEFAULT_RULES:
            raise ValueError(f"Unknown rule '{key}'.")
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"Rule '{key}' must be a whole number.")
        if number < 0:
            raise ValueError(f"Rule '{key}' can't be negative.")
        if key == "max_days_per_shelter" and number > 365:
            raise ValueError("Days per shelter must be 365 or less.")
        if key.endswith("_pct") and number > 100:
            raise ValueError(f"Rule '{key}' is a percentage, so it must be 100 or less.")
        rules[key] = number
    return rules
