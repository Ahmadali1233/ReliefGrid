# ReliefGrid

**Emergency Relief Operations & Dispatch System** — Team FEAST, RIT Dubai Software Engineering Competition 2026.

ReliefGrid tracks every carton from a shelter's request to a signature at the shelter door, like a parcel, and
makes sure supplies reach the people who need them most. It allocates stock in priority order
(**Critical > High > Moderate**) from the nearest warehouse, puts every truckload on a numbered waybill that the
driver and the shelter confirm from their phones, and checks that what's handed out is fair per person, not just
per request.

## Run it (2 minutes)

You need **Python 3.10 or newer** ([python.org](https://www.python.org/downloads/); on Windows tick
"Add Python to PATH" during install).

```bash
pip install -r requirements.txt
python run.py
```

Your browser opens at **http://localhost:8000**. Sample data (a monsoon flood in Dadu district, Sindh: 2 warehouses, 14 shelters, 7 items, 48 requests)
loads on first run. No internet connection is needed after installing.

| Command | Does |
| --- | --- |
| `python run.py` | Start the app and open the browser |
| `python run.py --reset` | Wipe the database and load the sample data (asks you to type RESET) |
| `python run.py --empty` | Wipe the database and start with no data, for real use |
| `python run.py --phones` | Also let phones on the same Wi-Fi scan waybill QR codes (driver pick-up, shelter sign-off) and open the tracking page |
| `python run.py --port 8080` | Use another port |
| `python -m pytest` | Run all automated tests |

Interactive API docs: **http://localhost:8000/docs**

## What it does

| Brief requirement | Where |
| --- | --- |
| Data models: Inventory, Requests, Shelters | `app/db/schema.sql` (plus waybills, losses, planning figures) |
| Priority allocation engine (Critical > High > Moderate) | `app/engine/allocate.py`, rules in `app/engine/rules.py` |
| Inventory tracking: live stock, no negative stock, insufficient-stock handling | `app/services/allocation.py` + database CHECK constraints |
| GUI: enter requests, inspect inventory, view allocation logs | Requests, Inventory, Dispatch and Log screens |
| Export and reporting: JSON, CSV, PDF of fulfilled and unfilled requests | Report button · `GET /api/reports?format=json\|csv\|pdf` |
| Automated tests incl. negative stock and edge cases | `tests/` (181 tests) |
| Database, REST API, GUI | SQLite · FastAPI · HTML/CSS/JavaScript |

### Three things that set it apart

**1. Every carton is tracked, like a parcel.** Each truckload travels on a numbered waybill (`WB-1031-007`).
The QR on the printed waybill opens a page on the driver's phone ("Loaded: truck leaving now") and, at the
other end, on the shelter manager's phone, where they count what actually arrived and sign. If 2 cartons arrived
crushed, that's recorded with a note and those 2 go straight back in the queue for that shelter. Anyone can type a
waybill or request number into the command bar (or open `/track.html` on a phone) and see the truck on its
route with the time to go, and a timeline: Requested → Reserved → On a truck → Delivered. The phone page works in English, Arabic
and Urdu. The coordinator's screen updates by itself within seconds.

**2. People, not boxes.** Shelters have a headcount and items have planning figures (the Sphere humanitarian
standard: 2.5–3 litres of drinking water per person per day). So ReliefGrid can say "400 people at Dadu Girls High
School have no water while a 50-person health post has 41 days". Strict priority order produces exactly that kind of
imbalance, and the brief's rules alone can't see it. The fair-share check finds it, the optional **days of supply per
shelter** rule fixes it (stock that hasn't left the warehouse is released and re-allocated), and the size check
catches typos like "2,000 water for 40 people".

**3. Every decision explained and checked.** "Why?" on any request explains, in plain English, why it got
what it got. Seven integrity checks run against the database on every dashboard load: stock adds up, nothing below
zero, no request over-filled, whole units only, priority order kept, same answer on re-run, and every load that
left a warehouse is on a waybill with a driver and a signature.

The dashboard draws the whole operation as a **relief web**: warehouses in the centre, shelters on rings by
priority (most vulnerable inside), sized by headcount, with a thread for every load (moving = truck on the road,
dotted = waiting for a truck, solid = delivered).

**How it works in a real operation**

1. **A shelter phones or messages in a need.** The coordinator enters it on the Requests screen. The form shows the
   unit, what the request will get from current stock, how many days it covers for the shelter's headcount, and
   warns about duplicates and oversized requests.
2. **Stock is reserved automatically**, most urgent first, from the nearest warehouse that has it.
3. **Not enough?** "Order supplies" sends a numbered supply order (`PO-1101-001`) in one click: straight to the
   supply contact's WhatsApp, or a ready-to-send Gmail, or copied. Only what isn't already on order is suggested,
   so nobody orders the same shortfall twice. The "How much should we ask for?" slider shows what a delivery of
   that size would cover.
4. **The order arrives.** In **Log → Supply orders**, tick it off: "All arrived", or "Part arrived" with the counts
   (the rest stays expected, or "Stop waiting for the rest"). Every tick puts the stock on the shelf and allocates
   it, and can be undone if it was a misclick (stock reserved from it, but not on a truck, is released first).
   Orders can be cancelled and reopened. "Record delivery" can also tick off an order.
   Donations nobody ordered go in through "Record delivery" with who sent them and their delivery note.
5. **Dispatch.** Print the waybill. The driver scans it when the truck leaves (or the coordinator types the
   driver's name). Only what's on the waybill goes; anything reserved later waits for the next truck.
6. **Arrival.** The shelter scans the same QR, counts and signs. Shortfalls are recorded and re-queued.
7. **A shelter calls back.** Change the quantity or urgency in the "Why?" panel. Reducing it puts reserved stock
   back on the shelf for others. Headcounts are updated on the Shelters screen.
8. **Report.** One-click sitrep text, and JSON, CSV or PDF reports of fulfilled and unfilled requests and waybills.

**Ask or do anything (Ctrl+K).** Type in plain words: "Johi Tent City needs 200 water, critical", "How much baby
milk do we have?", "Who is waiting for blankets?", "Received 300 water at Warehouse A", "Where is WB-1102-004?",
"Order 48 baby milk", "Cap at 7 days", "Undo". Questions are answered straight away. Changes are shown first (what
the request would get now, what a delivery would fill) and only happen when you press Enter. It runs inside
ReliefGrid with no AI service and no internet, so it keeps working in a disaster zone (`app/services/assistant.py`).

**The Log.** Every action with who did it. Sublogs on the left (requests, trucks and deliveries, stock arrivals,
supply orders, rule changes, undo history), filters for shelter, item, person and time, five ways to sort (newest,
oldest, by shelter, by item, by person), and search that highlights every match like Ctrl+F. Click any `WB-`,
`REQ-` or `PO-` number to open that thing's own sublog: everything that happened to it, in order. Click an entry
for its details. The latest change shows **Undo** right on its entries (for 10 minutes); what's shown exports to CSV.

**Undo really undoes, and never hides.** Undo reverses the data (stock goes back, the request disappears from the
queue), but the log only ever grows: the original entries stay, struck through and marked "Undone", next to an
"Undid: ..." entry. If the change already left the building, like a supply order sent on WhatsApp or Gmail, undoing
it keeps the order in the log as cancelled and opens a ready-made "please cancel PO-..." message to the same person on
the same channel (cancelling an order does the same, and reopening it offers a "please go ahead after all"). Sending
that message is logged too, so the paper trail shows the supplier was told.

**The sample is a real-looking shift.** Requests came in over the last day, typed in by hub staff (Sana, Usman);
warehouse staff counted stock; trucks left with named drivers and were signed for by shelter leads (Ayesha at Dadu
Girls High School, Dr. Khalid at Moro Rural Health Centre) at times that match the driving distance; one supply
order already arrived and another is on its way. All times are relative to when you first run it.

**Also included**

- **Street map** (OpenStreetMap, Leaflet bundled locally). Without internet the streets don't load, but shelters,
  warehouses and supply routes still show in the right places.
- **Import any CSV, TSV, JSON or XML**, even with unfamiliar column names: columns are matched automatically or by
  you, bad rows are listed with the reason and skipped, good rows go in. Matches are remembered.
- **Search, filters and sortable columns** on every list. Search highlights matches; filters show how many rows
  each choice has.
- **Optional rules**: reserve stock for Critical requests, days of supply per shelter, cap units per shelter,
  low-stock threshold. **Planning figures** are editable under Rules.
- **Night shift mode** (dark theme).
- **Motion with a purpose**: the truck moves along its route on the tracking screens, the fair-share bars move from
  before to after when you apply a days cap, the 7 checks tick in one by one, and a tick appears when an order is
  sent or a delivery is signed. All of it switches off with the operating system's "reduce motion" setting.
- **Works offline** after installing (the street map tiles are the only thing that need internet).

**Phones (`python run.py --phones`).** The terminal prints the address phones use. The phone must be on the same
Wi-Fi as the laptop (or the laptop's hotspot). On Windows, allow Python on private networks when asked. Phone
links are signed: only someone holding the printed QR can confirm a pick-up or delivery; the tracking page is
read-only.

## How allocation works

Requests are served one at a time in this order, so the same data always gives the same answer:

1. **Urgency** — Critical, then High, then Moderate
2. **Shelter priority** — priority 1 (most vulnerable) first
3. **Time submitted** — earlier first
4. **Request ID** — alphabetical, a final guaranteed tie-break

Each request gets `min(what it still needs, what's left)`. Stock comes from the nearest warehouse with the item;
if that runs short, the next nearest tops it up. Allocation runs automatically after every change (new request,
restock, import, cancellation, rule change) and only serves what is still unmet. Stock already allocated counts
as dispatched and is never taken back; the optional **Reserve for Critical** rule keeps a share back for
emergencies that arrive later.

## Project structure

```
run.py                 start the app
app/
  main.py              FastAPI app, error handling, serves the web folder
  api/                 REST endpoints (requests, inventory and shelters, system)
  engine/              allocation engine: pure Python, no database or web code
    rules.py           urgency order, tie-breaks, rule toggles  ← change rules here
    allocate.py        the algorithm
    explain.py         plain-English reasons
    distance.py        nearest-warehouse distance (haversine)
  services/            runs the engine against the database in one transaction; dispatch and waybills;
                       tracking; people and fair share; undo; integrity checks; import
  importers/           file readers (CSV/TSV/JSON/XML) and the column matcher
  reports/             JSON, CSV and PDF reports
  db/                  schema, connection, sample data loader
web/                   the interface (no build step); m.html = phone page, track.html = tracking page
data/sample/           sample data and demo files for the Import screen
tests/                 pytest suite
docs/                  architecture, Phase 2 cookbook
```

## REST API

| Method | Endpoint | Does |
| --- | --- | --- |
| GET | `/api/summary` | Everything the dashboard shows |
| GET / POST | `/api/requests` | List (filters: status, urgency, item, shelter_id, q) / add a request |
| GET | `/api/requests/preview` | What a new request would get, without saving |
| GET | `/api/requests/{id}` · `/explain` | One request, with its explanation |
| POST | `/api/requests/{id}/cancel` | Cancel; stock goes back and is re-allocated |
| GET | `/api/inventory` | Stock per item and warehouse |
| POST | `/api/inventory/restock` | Record a delivery (item, quantity, warehouse, source, waybill); waiting requests are allocated |
| GET | `/api/inventory/restock/preview` | What a delivery would do, without saving |
| GET / POST | `/api/shelters`, `/api/warehouses` | List / add |
| GET | `/api/allocations`, `/api/events` | Allocation records and the activity log (each entry tagged with its sublog, shelters, items and numbers) |
| POST | `/api/import/preview` · `/api/import/commit` | Check a file / import its good rows |
| GET | `/api/reports?format=json\|csv\|pdf` | Fulfilled and unfilled report |
| GET | `/api/integrity` | The seven integrity checks |
| GET | `/api/sitrep` | A shareable situation report |
| GET | `/api/search?q=` | Quick find across shelters, requests, items, warehouses |
| GET | `/api/ask?q=` | The command bar: plain words in, an answer or a previewed action (with the exact API call) out |
| PATCH | `/api/requests/{id}` | Change a request's quantity or urgency |
| GET | `/api/dispatch` | To load (per route), on the way and delivered (per waybill) |
| POST | `/api/dispatch/waybill` | Put everything reserved on a route onto a numbered waybill |
| POST | `/api/dispatch/dispatched` · `/delivered` | Truck left (driver) · delivery counted and signed for; shortfalls re-queued |
| GET | `/api/track/{code}` | Track a waybill or request: status, timeline, arrival estimate |
| GET · POST | `/api/handoff/{waybill}` · `/pickup` · `/receive` | The phone page behind a waybill's QR (needs the code in the QR) |
| PATCH | `/api/shelters/{id}` | Update a shelter's headcount or priority |
| GET / PUT | `/api/figures` | Planning figures (per person, per day or per stay) |
| GET | `/api/network` | The relief web: warehouses, shelters and loads between them |
| GET | `/api/changes` | Change fingerprint; screens poll it to refresh by themselves |
| GET / POST | `/api/supply/orders` | Supply orders with lines and ticks / record one that was just sent |
| POST | `/api/supply/orders/{id}/receive` · `/cancel` · `/reopen` · `/close` | Tick off all or part · cancel · reopen · stop waiting for the rest |
| POST | `/api/supply/receipts/{id}/reverse` | Undo a tick (misclick) |
| GET / PUT | `/api/supply/contact` | Who supply orders go to (name, WhatsApp number, email) |
| GET | `/api/version` | Running version (the interface checks it) |
| GET / PUT | `/api/rules` | Rule toggles |
| GET / POST | `/api/undo` | What can be undone / undo it |
| POST | `/api/reset` | Demo only: `{"confirm": "RESET", "sample": true}` |

Errors always come back as `{"error": "plain-English message"}` with a 400, 404, 409 or 413 status.

## Tests

```bash
python -m pytest -q
```

181 tests cover the priority order and every tie-break, partial fills, negative-stock prevention, zero and
missing stock, nearest-warehouse selection, determinism, the optional rules, undo, cancellation, reports in all
three formats, friendly error messages, importing messy, duplicated, mis-typed and unreadable files, waybills
(only what's on the waybill leaves, numbers never reused, signed phone links, short deliveries re-queued),
tracking, headcounts, planning figures, the fair-share check and the days-of-supply rule, supply orders (part
arrivals, undoing a tick even after the stock was reserved, refusing once it left on a truck), and `tests/test_robustness.py`: 50+ kinds of bad input (negatives, `true` as a quantity,
SQL injection, junk files…) that must each be rejected with a clear message and change nothing, plus 10,000-request
engine runs that check every rule.

## Team FEAST

| Member | Role |
| --- | --- |
| [Name] | Engine, rules and tests |
| [Name] | API, database, import and reports |
| [Name] | Interface, documentation and demo |

Map: Leaflet (BSD-2) with OpenStreetMap tiles (© OpenStreetMap contributors).
Font: Plus Jakarta Sans (SIL Open Font License), bundled in `web/fonts/` so the app works offline.
QR codes: qrcode-generator by Kazuhiko Arase (MIT), bundled in `web/js/vendor/`.
