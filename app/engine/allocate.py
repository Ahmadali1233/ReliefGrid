"""The allocation engine.

Pure functions only: no database, no web code. Give it requests, stock and warehouses;
it hands back one Decision per waiting request and the stock left afterwards.
That makes it easy to test, and safe to run "what if" previews without changing anything.
"""

from dataclasses import dataclass, field

from .distance import km_between
from .rules import DEFAULT_RULES, sort_key


@dataclass
class Take:
    """Units taken from one warehouse for one request."""
    warehouse_id: str
    quantity: int
    distance_km: float | None


@dataclass
class Decision:
    """What happened to one request in one run, plus everything needed to explain it."""
    request_id: str
    shelter_id: str
    item: str
    urgency: str
    rank: int                 # position in this run across all items (1 = first)
    rank_in_item: int         # position among requests for the same item
    requested: int            # total units the request asked for
    already: int              # units it had received in earlier runs
    eligible: int             # units it could receive this run after caps
    given: int                # units given in this run
    stock_at_turn: int        # units of the item in stock when its turn came
    usable_at_turn: int       # of those, units it was allowed to use (reserve rule)
    ahead_count: int          # requests for the same item served before it in this run
    used_ahead: int           # units those requests took
    takes: list = field(default_factory=list)
    capped: bool = False
    reserve_held: int = 0
    cap_kind: str = ""        # "units" (max per shelter) or "days" (days of need for its headcount)
    cap_limit: int = 0        # the shelter's limit for this item under that rule

    @property
    def total(self):
        return self.already + self.given

    @property
    def remaining(self):
        return self.requested - self.total

    @property
    def status(self):
        if self.total >= self.requested:
            return "fulfilled"
        return "partial" if self.total > 0 else "unfilled"


def allocate(requests, stock, warehouses, rules=None):
    """Allocate stock to requests in priority order.

    requests:   list of dicts with id, shelter_id, item, quantity, allocated, urgency,
                created_at, shelter_priority, lat, lon. Cancelled requests must be left out.
                Optional daily_need: units per day this shelter needs of this item (headcount x
                planning figure), used by the max_days_per_shelter rule.
    stock:      {(warehouse_id, item): units}
    warehouses: {warehouse_id: (lat, lon)}
    rules:      see rules.DEFAULT_RULES

    Returns (decisions, stock_after). The input stock dict is never modified.
    """
    rules = {**DEFAULT_RULES, **(rules or {})}
    stock = {key: int(units) for key, units in stock.items()}

    for key, units in stock.items():
        if units < 0:
            raise ValueError(f"Stock for {key[1]} at {key[0]} is negative ({units}).")

    # Units each shelter has already received of each item (for the per-shelter cap).
    received = {}
    for r in requests:
        k = (r["shelter_id"], r["item"])
        received[k] = received.get(k, 0) + int(r.get("allocated") or 0)

    # Reserve for Critical: a share of each item's stock at the start of the run.
    item_totals = {}
    for (_, item), units in stock.items():
        item_totals[item] = item_totals.get(item, 0) + units
    pct = rules["reserve_for_critical_pct"]
    reserve = {item: (total * pct) // 100 for item, total in item_totals.items()}

    cap = rules["max_per_shelter_per_item"]
    max_days = rules.get("max_days_per_shelter", 0)
    waiting = [r for r in requests if int(r["quantity"]) - int(r.get("allocated") or 0) > 0]
    ordered = sorted(waiting, key=sort_key)

    decisions = []
    ahead = {}       # item -> (count, units)
    for rank, r in enumerate(ordered, start=1):
        item = r["item"]
        requested = int(r["quantity"])
        already = int(r.get("allocated") or 0)
        need = requested - already

        capped, cap_kind, cap_limit = False, "", 0
        limits = []
        if cap > 0:
            limits.append(("units", cap))
        daily = r.get("daily_need")
        if max_days > 0 and daily:
            limits.append(("days", -(-int(round(daily * max_days * 1000)) // 1000)))   # round up, whole units
        for kind, limit in limits:
            allowance = max(limit - received.get((r["shelter_id"], item), 0), 0)
            if allowance < need:
                need, capped, cap_kind, cap_limit = allowance, True, kind, limit

        in_stock = sum(units for (_, it), units in stock.items() if it == item)
        held = 0
        if r["urgency"] != "critical":
            held = min(reserve.get(item, 0), in_stock)
        usable = in_stock - held
        give = min(need, usable)

        # Take from the nearest warehouse first; ties go to the warehouse ID, alphabetically.
        sources = []
        for (wh, it), units in stock.items():
            if it == item and units > 0:
                lat, lon = warehouses.get(wh, (None, None))
                km = km_between(r.get("lat"), r.get("lon"), lat, lon)
                sources.append((km if km is not None else float("inf"), wh, km))
        sources.sort(key=lambda s: (s[0], s[1]))

        takes, left = [], give
        for _, wh, km in sources:
            if left == 0:
                break
            q = min(left, stock[(wh, item)])
            stock[(wh, item)] -= q
            left -= q
            takes.append(Take(wh, q, round(km, 1) if km is not None else None))

        count, units = ahead.get(item, (0, 0))
        decisions.append(Decision(
            request_id=r["id"], shelter_id=r["shelter_id"], item=item, urgency=r["urgency"],
            rank=rank, rank_in_item=count + 1, requested=requested, already=already,
            eligible=need, given=give, stock_at_turn=in_stock, usable_at_turn=usable,
            ahead_count=count, used_ahead=units, takes=takes, capped=capped, reserve_held=held,
            cap_kind=cap_kind, cap_limit=cap_limit,
        ))
        ahead[item] = (count + 1, units + give)
        received[(r["shelter_id"], item)] = received.get((r["shelter_id"], item), 0) + give

    return decisions, stock
