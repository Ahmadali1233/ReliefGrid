-- ReliefGrid database schema (SQLite).
-- The CHECK constraints are a second safety net: even if the code had a bug,
-- the database refuses negative stock or an over-filled request.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS warehouses (
    id    TEXT PRIMARY KEY,
    name  TEXT NOT NULL,
    lat   REAL,
    lon   REAL
);

-- Brief: Inventory (item, quantity, warehouse ID)
CREATE TABLE IF NOT EXISTS inventory (
    warehouse_id  TEXT NOT NULL REFERENCES warehouses(id),
    item          TEXT NOT NULL,
    quantity      INTEGER NOT NULL CHECK (quantity >= 0),
    unit          TEXT NOT NULL DEFAULT 'units',
    PRIMARY KEY (warehouse_id, item)
);

-- Brief: Shelters (shelter ID, name, priority, location coordinates)
-- priority 1 = most vulnerable, served first among equal urgency.
CREATE TABLE IF NOT EXISTS shelters (
    id        TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    priority  INTEGER NOT NULL DEFAULT 2 CHECK (priority >= 1),
    lat       REAL,
    lon       REAL,
    people    INTEGER CHECK (people IS NULL OR people >= 0)   -- headcount today (optional)
);

-- Planning figures: how much one person needs, so quantities can be read as people and days.
-- per = 'day' (used up daily, e.g. water) or 'stay' (needed once, e.g. blankets).
CREATE TABLE IF NOT EXISTS items (
    item        TEXT PRIMARY KEY COLLATE NOCASE,
    per_person  REAL NOT NULL CHECK (per_person > 0),
    per         TEXT NOT NULL CHECK (per IN ('day', 'stay')),
    basis       TEXT
);

-- Brief: Requests (request ID, shelter ID, item, quantity, urgency)
CREATE TABLE IF NOT EXISTS requests (
    id           TEXT PRIMARY KEY,
    shelter_id   TEXT NOT NULL REFERENCES shelters(id),
    item         TEXT NOT NULL,
    quantity     INTEGER NOT NULL CHECK (quantity > 0),
    urgency      TEXT NOT NULL CHECK (urgency IN ('critical', 'high', 'moderate')),
    created_at   TEXT NOT NULL,
    allocated    INTEGER NOT NULL DEFAULT 0 CHECK (allocated >= 0 AND allocated <= quantity),
    status       TEXT NOT NULL DEFAULT 'unfilled',
    cancelled    INTEGER NOT NULL DEFAULT 0,
    explanation  TEXT
);

-- One row per allocation run (triggered by a new request, a restock, an import...).
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    trigger     TEXT NOT NULL,
    rules       TEXT NOT NULL
);

-- What each request was given, from which warehouse, in which run.
CREATE TABLE IF NOT EXISTS allocations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER NOT NULL REFERENCES runs(id),
    request_id   TEXT NOT NULL REFERENCES requests(id),
    warehouse_id TEXT NOT NULL,
    item         TEXT NOT NULL,
    quantity     INTEGER NOT NULL CHECK (quantity > 0),
    distance_km  REAL,
    created_at   TEXT NOT NULL,
    -- Lifecycle: allocated (reserved in the warehouse) -> dispatched (on a truck) -> delivered (signed for)
    status        TEXT NOT NULL DEFAULT 'allocated',
    dispatched_at TEXT,
    dispatched_by TEXT,
    delivered_at  TEXT,
    received_by   TEXT,
    note          TEXT,
    shipment_id   TEXT            -- the waybill it travels on (NULL while reserved and not yet on one)
);

-- Waybills: one truckload from one warehouse to one shelter. The number (WB-1031-007) is the tracking number.
CREATE TABLE IF NOT EXISTS shipments (
    id             TEXT PRIMARY KEY,
    warehouse_id   TEXT NOT NULL,
    shelter_id     TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'loading' CHECK (status IN ('loading', 'on_the_way', 'delivered')),
    created_at     TEXT NOT NULL,
    dispatched_at  TEXT,
    driver         TEXT,
    delivered_at   TEXT,
    received_by    TEXT,
    note           TEXT
);

-- Units that left a warehouse but never reached the shelter (damaged, missing). The request goes back in the queue.
CREATE TABLE IF NOT EXISTS losses (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id    TEXT NOT NULL,
    warehouse_id  TEXT NOT NULL,
    shelter_id    TEXT NOT NULL,
    item          TEXT NOT NULL,
    quantity      INTEGER NOT NULL CHECK (quantity > 0),
    note          TEXT,
    reported_by   TEXT,
    created_at    TEXT NOT NULL,
    shipment_id   TEXT
);

-- Supply orders: what the hub asked HQ, a donor or a supplier for, and what has arrived against each.
CREATE TABLE IF NOT EXISTS supply_orders (
    id            TEXT PRIMARY KEY,            -- PO-1101-001
    created_at    TEXT NOT NULL,
    supplier      TEXT NOT NULL,
    sent_via      TEXT NOT NULL DEFAULT 'copy' CHECK (sent_via IN ('whatsapp', 'email', 'copy')),
    warehouse_id  TEXT NOT NULL,               -- deliver to
    cancelled_at  TEXT,
    closed_at     TEXT                         -- "stop waiting for the rest"
);
CREATE TABLE IF NOT EXISTS supply_lines (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id  TEXT NOT NULL REFERENCES supply_orders(id),
    item      TEXT NOT NULL,
    unit      TEXT,
    quantity  INTEGER NOT NULL CHECK (quantity > 0),
    received  INTEGER NOT NULL DEFAULT 0 CHECK (received >= 0)
);
-- Every time something arrived against an order (one row per tick). Reversible.
CREATE TABLE IF NOT EXISTS supply_receipts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id      TEXT NOT NULL REFERENCES supply_orders(id),
    created_at    TEXT NOT NULL,
    warehouse_id  TEXT NOT NULL,
    lines         TEXT NOT NULL,               -- JSON {item: units}
    reversed_at   TEXT
);

-- Secrets that must survive Undo and resets (e.g. the key that signs phone links on delivery slips).
CREATE TABLE IF NOT EXISTS keys (
    name   TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

-- The order requests were served in each run (used by the priority integrity check).
CREATE TABLE IF NOT EXISTS run_entries (
    run_id      INTEGER NOT NULL,
    request_id  TEXT NOT NULL,
    item        TEXT NOT NULL,
    rank        INTEGER NOT NULL,
    eligible    INTEGER NOT NULL,
    given       INTEGER NOT NULL,
    PRIMARY KEY (run_id, request_id)
);

-- Every change to stock, ever. Current stock must always equal the sum of these.
CREATE TABLE IF NOT EXISTS movements (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    warehouse_id  TEXT NOT NULL,
    item          TEXT NOT NULL,
    delta         INTEGER NOT NULL,
    reason        TEXT NOT NULL,
    ref           TEXT,
    created_at    TEXT NOT NULL
);

-- The human-readable activity log shown on the Log screen.
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    kind        TEXT NOT NULL,
    message     TEXT NOT NULL,
    data        TEXT,
    actor       TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

-- Copies of the data taken before each change, so Undo can put things back.
CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    label       TEXT NOT NULL,
    data        TEXT NOT NULL
);

-- Remembered column matches for imported files.
CREATE TABLE IF NOT EXISTS column_mappings (
    signature  TEXT PRIMARY KEY,
    entity     TEXT NOT NULL,
    mapping    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_requests_item ON requests(item);
CREATE INDEX IF NOT EXISTS idx_allocations_request ON allocations(request_id);

-- Who did it: every log entry records the operator on shift (sent by the interface).
CREATE TRIGGER IF NOT EXISTS events_actor AFTER INSERT ON events
WHEN NEW.actor IS NULL
BEGIN
    UPDATE events SET actor = current_actor() WHERE id = NEW.id;
END;

CREATE INDEX IF NOT EXISTS idx_allocations_shipment ON allocations(shipment_id);
