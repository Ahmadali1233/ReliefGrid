"""/api/inventory, /api/warehouses and /api/shelters."""

from fastapi import APIRouter
from pydantic import BaseModel, Field, StrictInt

from ..db.database import rows
from ..services import actions, queries

router = APIRouter(tags=["Inventory and shelters"])


class Restock(BaseModel):
    warehouse_id: str = Field(examples=["WH-A"])
    item: str = Field(examples=["Water"])
    quantity: int = Field(examples=[380], strict=True)
    unit: str | None = Field(default=None, examples=["cartons"])
    source: str | None = Field(default=None, description="Who sent it: donor, supplier or HQ", examples=["UAE Red Crescent"])
    reference: str | None = Field(default=None, description="Delivery note or waybill number", examples=["WB-20431"])


class NewShelter(BaseModel):
    id: str = Field(examples=["SH-15"])
    name: str = Field(examples=["Al Nahda Community Hall"])
    priority: int = Field(default=2, strict=True, description="1 = most vulnerable, served first")
    lat: float | None = None
    lon: float | None = None
    people: int | None = Field(default=None, strict=True, description="Headcount today (optional)", examples=[320])


class ChangeShelter(BaseModel):
    people: int | None = Field(default=None, strict=True, description="New headcount", examples=[340])
    priority: int | None = Field(default=None, strict=True, examples=[1])
    clear_people: bool = Field(default=False, description="Set the headcount back to unknown")


class NewWarehouse(BaseModel):
    id: str = Field(examples=["WH-C"])
    name: str = Field(examples=["Warehouse C · Ras Al Khor"])
    lat: float | None = None
    lon: float | None = None


@router.get("/api/inventory")
def inventory():
    """Stock per item, with the split across warehouses and a status (ok, low, out)."""
    return queries.stock_by_item()


@router.post("/api/inventory/restock")
def restock(body: Restock):
    """Record a delivery that has arrived at a warehouse. Waiting requests are allocated straight away, most urgent first."""
    return actions.restock(body.warehouse_id, body.item, body.quantity, body.unit, body.source, body.reference)


@router.get("/api/inventory/restock/preview")
def restock_preview(item: str, quantity: int, warehouse_id: str):
    """How many waiting requests would this delivery serve? Changes nothing."""
    return queries.restock_preview(item, max(quantity, 0), warehouse_id)


@router.get("/api/warehouses")
def warehouses():
    return rows("SELECT * FROM warehouses ORDER BY id")


@router.post("/api/warehouses", status_code=201)
def add_warehouse(body: NewWarehouse):
    return actions.add_warehouse(body.id, body.name, body.lat, body.lon)


@router.get("/api/shelters")
def shelters():
    """Shelters with their request totals, status and which warehouses supplied them (for the map)."""
    return queries.shelters_view()


@router.post("/api/shelters", status_code=201)
def add_shelter(body: NewShelter):
    return actions.add_shelter(body.id, body.name, body.priority, body.lat, body.lon, body.people)


@router.patch("/api/shelters/{shelter_id}")
def change_shelter(shelter_id: str, body: ChangeShelter):
    """Update a shelter's headcount (it changes daily) or its priority. Allocation re-runs."""
    return actions.update_shelter(shelter_id, body.people, body.priority, body.clear_people)


class Dispatch(BaseModel):
    waybill: str | None = Field(default=None, examples=["WB-1031-007"], description="The waybill that left. "
                                "Or give warehouse_id and shelter_id to send everything reserved on that route.")
    warehouse_id: str | None = Field(default=None, examples=["WH-A"])
    shelter_id: str | None = Field(default=None, examples=["SH-04"])
    driver: str = Field(examples=["Truck 7 · Ahmed"], description="Driver name or vehicle")
    upto_id: int | None = Field(default=None, strict=True, description="Only load allocations up to this ID "
                                "(what the driver was shown). Anything reserved later waits for the next truck.")


class Delivered(BaseModel):
    waybill: str | None = Field(default=None, examples=["WB-1031-007"])
    warehouse_id: str | None = Field(default=None, examples=["WH-A"])
    shelter_id: str | None = Field(default=None, examples=["SH-04"])
    received_by: str = Field(examples=["Fatima, shelter manager"])
    received: dict[str, StrictInt] | None = Field(default=None, description="Units that actually arrived, per item. "
                                            "Leave out if everything arrived.", examples=[{"Water": 98}])
    note: str | None = Field(default=None, description="What happened to anything missing", examples=["2 cartons crushed"])


class Route(BaseModel):
    warehouse_id: str = Field(examples=["WH-A"])
    shelter_id: str = Field(examples=["SH-04"])


@router.get("/api/dispatch", tags=["Dispatch and tracking"])
def dispatch_loads(status: str | None = None):
    """To load (per route), on the way and delivered (per waybill)."""
    from ..services import dispatch
    if status and status not in ("allocated", "dispatched", "delivered"):
        raise ValueError("Status must be allocated, dispatched or delivered.")
    return {"loads": dispatch.loads(status), "counts": dispatch.counts()}


@router.post("/api/dispatch/waybill", tags=["Dispatch and tracking"])
def print_waybill(body: Route):
    """Put everything reserved on a route onto a numbered waybill (the tracking number on the printed slip)."""
    from ..services import dispatch
    return dispatch.print_waybill(body.warehouse_id, body.shelter_id)


@router.post("/api/dispatch/dispatched", tags=["Dispatch and tracking"])
def mark_dispatched(body: Dispatch):
    """A truck has left with a waybill (one is made if the route doesn't have one yet)."""
    from ..services import dispatch
    if not body.waybill and not (body.warehouse_id and body.shelter_id):
        raise ValueError("Give the waybill number, or the warehouse and shelter.")
    return dispatch.mark_dispatched(body.warehouse_id, body.shelter_id, body.driver, body.upto_id, body.waybill)


@router.post("/api/dispatch/delivered", tags=["Dispatch and tracking"])
def mark_delivered(body: Delivered):
    """The shelter counted the load and signed. Missing or damaged units go back in the queue."""
    from ..services import dispatch
    if not body.waybill and not (body.warehouse_id and body.shelter_id):
        raise ValueError("Give the waybill number, or the warehouse and shelter.")
    return dispatch.confirm_delivered(body.waybill, body.received_by, body.received, body.note,
                                      body.warehouse_id, body.shelter_id)


@router.get("/api/track/{code}", tags=["Dispatch and tracking"])
def track(code: str):
    """Track a waybill (WB-1031-007) or a request (REQ-012) like a parcel: status, timeline and arrival time."""
    from ..services import tracking
    return tracking.track(code)


# ---------- Phone handoff: the QR on a printed waybill opens these on a driver's or shelter's phone ----------

class PhonePickup(BaseModel):
    t: str = Field(description="The code from the waybill's QR")
    driver: str = Field(examples=["Truck 7 · Ahmed"])
    upto_id: int | None = Field(default=None, strict=True)


class PhoneReceive(BaseModel):
    t: str
    received_by: str = Field(examples=["Fatima, shelter manager"])
    received: dict[str, StrictInt] | None = None
    note: str | None = None


@router.get("/api/handoff/{waybill}", tags=["Phone handoff"])
def handoff(waybill: str, t: str = ""):
    """What the phone shows after scanning a waybill. Needs the code from the QR."""
    from ..services import dispatch
    return dispatch.handoff(waybill, t)


@router.post("/api/handoff/{waybill}/pickup", tags=["Phone handoff"])
def handoff_pickup(waybill: str, body: PhonePickup):
    """The driver confirms the truck is loaded and leaving."""
    from ..services import dispatch
    dispatch.check_token(waybill, body.t)
    return dispatch.mark_dispatched(driver=body.driver, upto_id=body.upto_id, waybill=waybill)


@router.post("/api/handoff/{waybill}/receive", tags=["Phone handoff"])
def handoff_receive(waybill: str, body: PhoneReceive):
    """The shelter counts what arrived and signs for it."""
    from ..services import dispatch
    dispatch.check_token(waybill, body.t)
    return dispatch.confirm_delivered(waybill, body.received_by, body.received, body.note)
