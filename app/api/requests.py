"""/api/requests — list, add, preview, explain and cancel shelter requests."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field  # strict=True: no true/false or 2.5 as a quantity

from ..services import actions, queries

router = APIRouter(prefix="/api/requests", tags=["Requests"])


class NewRequest(BaseModel):
    shelter_id: str = Field(examples=["SH-04"])
    item: str = Field(examples=["Water"])
    quantity: int = Field(examples=[100], strict=True)
    urgency: str = Field(examples=["critical"], description="critical, high or moderate")


class ChangeRequest(BaseModel):
    quantity: int | None = Field(default=None, strict=True, examples=[80])
    urgency: str | None = Field(default=None, examples=["critical"])


@router.get("")
def list_requests(status: str | None = None, urgency: str | None = None, item: str | None = None,
                  shelter_id: str | None = None, q: str | None = None):
    """All requests, waiting first. Filter with status (waiting, fulfilled, partial, unfilled, cancelled),
    urgency, item, shelter_id, or a search term q."""
    return queries.requests_list(status, urgency, item, shelter_id, q)


@router.post("", status_code=201)
def add_request(body: NewRequest):
    """Add a request. It is allocated immediately, in priority order with everything else waiting."""
    return actions.create_request(body.shelter_id, body.item, body.quantity, body.urgency)


@router.get("/preview")
def preview_request(shelter_id: str, item: str, quantity: int, urgency: str):
    """What would this request get if it were added now? Changes nothing."""
    from ..engine import normalize_urgency
    level, _ = normalize_urgency(urgency)
    result = queries.request_preview(shelter_id, item, max(quantity, 0), level)
    if result is None:
        raise HTTPException(404, f"Shelter {shelter_id} doesn't exist.")
    return result


@router.get("/{request_id}")
def get_request(request_id: str):
    r = queries.request_detail(request_id)
    if r is None:
        raise HTTPException(404, f"Request {request_id} doesn't exist.")
    return r


@router.get("/{request_id}/explain")
def explain_request(request_id: str):
    """The plain-English reason this request got what it got."""
    r = queries.request_detail(request_id)
    if r is None:
        raise HTTPException(404, f"Request {request_id} doesn't exist.")
    return r["explanation"] or {"headline": "Not allocated yet.", "steps": []}


@router.post("/{request_id}/cancel")
def cancel(request_id: str):
    """Cancel a request. Any stock it received goes back and is re-allocated."""
    return actions.cancel_request(request_id)


@router.patch("/{request_id}")
def change(request_id: str, body: ChangeRequest):
    """Change a request's quantity or urgency (a shelter called back). Allocation re-runs."""
    return actions.update_request(request_id, body.quantity, body.urgency)
