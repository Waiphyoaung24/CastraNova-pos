import uuid
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app import crud
from app.api.deps import AdminUser, SessionDep, get_current_user
from app.models import (
    PartBatchPublic,
    ReceiveQuantityRequest,
    ReceiveSerializedRequest,
    ReceiveSerializedResponse,
    get_datetime_utc,
)
from app.services.barcode import render_label_sheet

router = APIRouter(prefix="/receipts", tags=["receipts"])


def _resolve_received_at(received_date: date | None) -> datetime | None:
    """Compose the stored ``received_at`` from an operator-picked calendar date
    and the server's *current clock time* (design 2026-07-25).

    Returning None when no date was picked lets crud fall through to its own
    default, so an omitted date behaves exactly as it did before this field
    existed.

    Composing with the clock time rather than collapsing to midnight keeps every
    receive distinct: ``received_at`` is the FIFO sort key and its tiebreaker is
    a random uuid4 primary key, so same-day midnight ties would make the choice
    of which batch a sale draws its cost from non-deterministic.

    The one-day tolerance on the future check absorbs timezone skew — the client
    sends its LOCAL date, and the local operating zones (Yangon UTC+6:30,
    Bangkok UTC+7) run ahead of UTC, so between local midnight and ~06:30 the
    picked 'today' is one day past the server's UTC today."""
    if received_date is None:
        return None
    if received_date > date.today() + timedelta(days=1):
        raise HTTPException(
            status_code=422, detail="received_date cannot be in the future"
        )
    return datetime.combine(received_date, get_datetime_utc().timetz())


@router.post("/serialized", response_model=ReceiveSerializedResponse)
def receive_serialized(
    *,
    session: SessionDep,
    admin: AdminUser,
    payload: ReceiveSerializedRequest,
) -> ReceiveSerializedResponse:
    units = crud.receive_serialized(
        session=session,
        product_id=payload.product_id,
        supplier_id=payload.supplier_id,
        pieces=payload.pieces,
        idempotency_key=payload.idempotency_key,
        received_by_user_id=admin.id,
        received_at=_resolve_received_at(payload.received_date),
    )
    return ReceiveSerializedResponse(units=units)


@router.post("/quantity", response_model=PartBatchPublic)
def receive_quantity(
    *,
    session: SessionDep,
    admin: AdminUser,
    payload: ReceiveQuantityRequest,
) -> PartBatchPublic:
    batch = crud.receive_quantity(
        session=session,
        product_id=payload.product_id,
        supplier_id=payload.supplier_id,
        received_qty=payload.received_qty,
        purchase_cost_thb=payload.purchase_cost_thb,
        idempotency_key=payload.idempotency_key,
        received_by_user_id=admin.id,
        supplier_batch_ref=payload.supplier_batch_ref,
        expected_qty=payload.expected_qty,
        note=payload.note,
        received_at=_resolve_received_at(payload.received_date),
    )
    return PartBatchPublic.model_validate(batch)


# Shared-team access (recorded decision D3, hardening spec 2026-06-11): any
# authenticated staff/admin may act on any unit label — the ~5-person
# warehouse team works shifts over shared objects (PRD §5). Ownership scoping
# was considered and rejected. No derived financials are exposed on this
# surface.
@router.get(
    "/serialized/{unit_id}/label.pdf",
    dependencies=[Depends(get_current_user)],
)
def read_unit_label(
    *,
    session: SessionDep,
    unit_id: uuid.UUID,
    qty: Annotated[int, Query(ge=1, le=1000)] = 1,
) -> Response:
    unit = crud.get_unit(session=session, unit_id=unit_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    pdf = render_label_sheet(
        qr_value=unit.castranova_barcode,
        line1=unit.castranova_barcode,
        line2=unit.supplier_serial,
        qty=qty,
    )
    return Response(content=pdf, media_type="application/pdf")
