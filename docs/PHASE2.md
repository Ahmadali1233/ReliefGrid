# Phase 2 cookbook

Competition day: 2 hours, surprise requirements, new data formats. Each recipe below says **which file to open**
and **what to change**. Practise each one once at home, with a timer, before the day.

**Golden rule:** for every change, add a test first (copy a similar one in `tests/`), then make it pass, then run
`python -m pytest -q`. Commit when it's green: `feat: …`, `fix: …`, `test: …`.

---

## The 2-hour plan

Three people, three lanes. Each person owns the files they committed in Phase 1, so nobody waits for anyone.

| Person | Owns | First move when the brief lands |
| --- | --- | --- |
| **Engine** | `app/engine/`, `tests/test_engine.py`, `tests/test_people.py` | New rules, urgency levels, tie-breaks, fairness |
| **Data** | `app/db/`, `app/importers/`, `app/services/`, `app/api/` | New data formats and fields, new endpoints |
| **Screens** | `web/`, `README.md`, the video | New screens or columns, then records the video |

| Time | What happens |
| --- | --- |
| **0:00–0:10** | All three read the new requirements together. Write each one as a row in `docs/PHASE2_LOG.md`. For each: which recipe below, who owns it, rough minutes. Drop the new data files on the Import screen straight away: most "new formats" import with no code. |
| **0:10–0:20** | `git pull`, `python -m pytest -q` (all green), start the app. Agree the order: the must-haves from the brief first, then the biggest-scoring extra. |
| **0:20–1:20** | Build in lanes. Every change: test first, make it pass, commit (`feat: …`). Pull and run the full tests every 20 minutes. If something takes more than twice its estimate, stop and ask the team: cut it or simplify it. |
| **1:20–1:35** | **Freeze.** No new features. Full test run, the "Before you record" checklist below, fix only what's broken. Fill in the log: minutes per change, tests before → after. |
| **1:35–1:55** | Record the Phase 2 video (script in the team plan): what was new → how fast we added it (show the log and a diff) → live demo → what we'd improve next. One take, 3 minutes. |
| **1:55–2:00** | Submit. Push, check the repo shows the commits, send. |

**Never:** start a feature in the last 25 minutes, change the database schema without `python run.py --reset`,
or leave a failing test. A smaller app that works beats a bigger one that crashes in the demo.

**Likely surprises and where they go**

| Surprise | Recipe | Owner | Minutes |
| --- | --- | --- | --- |
| New file format or column names | 1 | Data | 5–20 |
| New urgency level or new order | 2 | Engine | 5 |
| "Shelters with children first" / new tie-break | 3 | Engine | 10 |
| New allocation rule (fair share, max per shelter, reserve) | 4 (copy `max_days_per_shelter`) | Engine | 20–30 |
| New field (e.g. population, category, expiry date) | 5 | Data + Screens | 10–25 |
| New number on the dashboard | 6 | Screens | 15 |
| New endpoint | 7 | Data | 10 |
| Transfers between warehouses | 8 | Data | 30–40 |
| Vehicle capacity ("a truck holds 200 cartons") | 9 | Data | 30 |
| Expiry dates, first-expired-first-out | 10 | Data + Engine | 40 |

---

## 1. A new file format (5–20 min)

**Try the app first.** Drop the new file on the Import screen. Most "new formats" are just new column names, and
the column matcher handles them with no code at all. Pick the right field for each column and import.

If the column names will keep coming, teach the matcher once:
`app/importers/mapper.py` → add the name to the right list in `ALIASES`, e.g. `"quantity": [..., "boxes"]`.

If it's a genuinely new file type (say `.yaml`):
`app/importers/parse.py` → write `parse_yaml(text)` that returns `(columns, rows)` like `parse_csv` does
(each row a dict with a `"__row"` number), then register it in `PARSERS = {..., "yaml": parse_yaml}`.

Test: copy `test_xml_with_different_column_names` in `tests/test_import.py`.

## 2. A new urgency level, or a changed order (5 min)

`app/engine/rules.py` → edit `URGENCY_LEVELS` (served in list order) and add any new spellings to
`URGENCY_ALIASES`. Then update the CHECK constraint on `urgency` in `app/db/schema.sql`
(delete `reliefgrid.db` or run `python run.py --reset` to rebuild) and the three urgency buttons in
`web/js/views/requests.js` (search for `"critical", "high", "moderate"`).

Test: copy `test_critical_before_high_before_moderate` in `tests/test_engine.py`.

## 3. A new tie-break or ordering rule (10 min)

Example: "families with children first". `app/engine/rules.py` → `sort_key()` returns a tuple; add the new value
in the right position. If it needs a new field, add it in the query inside `load_state()` in
`app/services/allocation.py`.

## 4. A new allocation rule (20–30 min)

Example: "no shelter gets more than 50% of any item". Rules have three parts:

1. `app/engine/rules.py` → add the toggle to `DEFAULT_RULES`, e.g. `"max_share_pct": 0`.
2. `app/engine/allocate.py` → inside the main loop, after `need` is worked out, limit it
   (see how `cap` and `capped` work for `max_per_shelter_per_item` and copy that pattern).
3. `web/js/views/rules.js` → copy one `<div class="rule">…</div>` block for the new control.

Also add one sentence to `app/engine/explain.py` so "Why?" mentions it.

## 5. A new field on requests, shelters or stock (10–15 min)

Example: requests get a `category`.

1. `app/db/schema.sql` → add the column (then `python run.py --reset`).
2. `app/importers/mapper.py` → add it to `ENTITIES[...]["optional"]`, `FIELD_LABELS` and `ALIASES`;
   read it in `validate()`.
3. `app/services/importing.py` and `app/services/actions.py` → include it in the INSERT.
4. Show it: add a column in `web/js/views/requests.js` (search for `<th`).

## 6. A new dashboard number or chart (15 min)

`app/services/queries.py` → `summary()` returns a dict; add your number there.
`web/js/views/dashboard.js` → copy one `<div class="card kpi">` block and read your new value.

## 7. A new endpoint (10 min)

Copy any function in `app/api/*.py`. Put the logic in `app/services/` (changes go through `transaction()` and
start with `snapshot(conn, "label")` so Undo works). It appears in `/docs` automatically.

## 8. More warehouses, or warehouse-to-warehouse transfers (30–40 min)

More warehouses already work: add them on the Inventory screen or import a warehouses file. For transfers,
add an action in `app/services/actions.py` that moves stock with two `movements` rows (−q at one, +q at the other)
so the "Stock adds up" check stays green, then run allocation.

---

## 9. Vehicle capacity (30 min)

"A truck carries at most N units." In `app/services/dispatch.py` → `print_waybill()` and `mark_dispatched()`:
take rows in order (most urgent first, `sort_key`) until the next one would go over capacity; the rest stay
reserved without a waybill and wait for the next truck (that path already exists: see `later` in
`mark_dispatched`). Add `truck_capacity` to `DEFAULT_RULES` in `app/engine/rules.py`.
Test: copy `test_truck_takes_only_whats_on_its_waybill` in `tests/test_waybills.py`.

## 10. Expiry dates, first-expired-first-out (40 min)

Add `expires` to stock deliveries (`movements`) and a `lots` table (warehouse, item, quantity, expires). When
allocating, take from the lot that expires first. Show "expires in 3 days" on Inventory. Keep the "Stock adds up"
check green: lot quantities per warehouse and item must add up to `inventory.quantity`.

---

## Before you record the Phase 2 video

- `python -m pytest -q` is green
- Dashboard shows **All 7 integrity checks passed**
- `python -m pytest -q tests/test_robustness.py` (bad input + 10,000-request runs) is green
- Click through: import the new data → dashboard → Why? on a waiting request → print a waybill → scan it with a
  phone (`python run.py --phones`) → track it → report PDF

---

## 11. Extra features if you finish early

See the **Phase 2 feature bank** in the team plan: 14 small features with time estimates and the files to touch
(drive times on slips, truck planner, per-person view, fair share, deadlines, delivery status, family kits…).
Only start one when every surprise works and the tests are green.

Log every change in `docs/PHASE2_LOG.md` as you go, with minutes taken. It goes straight into the Phase 2 video.
