"""/api/supply: supply orders to HQ, donors or suppliers, and ticking them off as they arrive."""

from fastapi import APIRouter
from pydantic import BaseModel, Field, StrictInt

from ..services import supply

router = APIRouter(prefix="/api/supply", tags=["Supply orders"])


class Line(BaseModel):
    item: str = Field(examples=["Water"])
    quantity: StrictInt = Field(examples=[540])
    unit: str | None = Field(default=None, examples=["cartons"])


class NewOrder(BaseModel):
    lines: list[Line]
    warehouse_id: str = Field(examples=["WH-A"], description="Where it should be delivered")
    sent_via: str = Field(default="copy", description="whatsapp, email or copy")
    supplier: str | None = Field(default=None, description="Defaults to the saved supply contact")


class Receive(BaseModel):
    lines: dict[str, StrictInt] | None = Field(default=None, description="Units that arrived per item. "
                                               "Leave out when everything still expected arrived.",
                                               examples=[{"Water": 300}])
    warehouse_id: str | None = Field(default=None, description="Defaults to the order's warehouse")


class Contact(BaseModel):
    name: str = Field(examples=["HQ supply desk"])
    whatsapp: str | None = Field(default=None, examples=["+971554992348"])
    email: str | None = Field(default=None, examples=["supply@example.org"])


@router.get("/orders")
def list_orders():
    """Every supply order, newest first, with its lines, what has arrived and every tick."""
    return {"orders": supply.orders(), "contact": supply.contact()}


@router.post("/orders", status_code=201)
def create_order(body: NewOrder):
    """Record a supply request that was just sent (by WhatsApp, email or copied)."""
    return supply.create_order([l.model_dump() for l in body.lines], body.warehouse_id, body.sent_via, body.supplier)


@router.post("/orders/{order_id}/receive")
def receive(order_id: str, body: Receive | None = None):
    """Tick off what arrived (all of it, or part). Stock goes into the warehouse and is allocated."""
    body = body or Receive()
    return supply.receive(order_id, body.lines, body.warehouse_id)


@router.post("/orders/{order_id}/cancel")
def cancel(order_id: str):
    """Call off an order nothing has arrived for yet."""
    return supply.cancel_order(order_id)


@router.post("/orders/{order_id}/reopen")
def reopen(order_id: str):
    """Undo a cancel or a close."""
    return supply.reopen_order(order_id)


@router.post("/orders/{order_id}/close")
def close(order_id: str):
    """Part arrived and the rest isn't coming: stop waiting for it."""
    return supply.close_order(order_id)


@router.post("/receipts/{receipt_id}/reverse")
def reverse(receipt_id: int):
    """Undo a tick: the units come off the shelf again (reserved stock not yet on a truck is released first)."""
    return supply.reverse_receipt(receipt_id)


@router.get("/contact")
def get_contact():
    return supply.contact()


@router.put("/contact")
def put_contact(body: Contact):
    """Who supply requests go to: a name, a WhatsApp number and an email address."""
    return supply.save_contact(body.model_dump())


@router.post("/orders/{order_id}/notice")
def notice_sent(order_id: str, body: dict):
    """Record that the cancellation (or go-ahead) message for an order was sent to the supplier."""
    return supply.record_notice(order_id, (body or {}).get("kind"), (body or {}).get("via"))
