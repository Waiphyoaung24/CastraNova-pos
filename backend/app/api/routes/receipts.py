import uuid

from fastapi import APIRouter, Depends, HTTPException, Response

from app import crud
from app.api.deps import CurrentUser, SessionDep, get_admin
from app.models import (
    PartBatchPublic,
    ReceiveQuantityRequest,
    ReceiveSerializedRequest,
    ReceiveSerializedResponse,
)
from app.services.barcode import render_unit_label

router = APIRouter(prefix="/receipts", tags=["receipts"])


@router.post("/serialized", response_model=ReceiveSerializedResponse, dependencies=[Depends(get_admin)])
def receive_serialized(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    payload: ReceiveSerializedRequest,
) -> ReceiveSerializedResponse:
    units = crud.receive_serialized(
        session=session,
        product_id=payload.product_id,
        supplier_id=payload.supplier_id,
        pieces=payload.pieces,
        idempotency_key=payload.idempotency_key,
        received_by_user_id=current_user.id,
    )
    return ReceiveSerializedResponse(units=units)


@router.post("/quantity", response_model=PartBatchPublic, dependencies=[Depends(get_admin)])
def receive_quantity(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    payload: ReceiveQuantityRequest,
) -> PartBatchPublic:
    batch = crud.receive_quantity(
        session=session,
        product_id=payload.product_id,
        supplier_id=payload.supplier_id,
        received_qty=payload.received_qty,
        purchase_cost_thb=payload.purchase_cost_thb,
        idempotency_key=payload.idempotency_key,
        received_by_user_id=current_user.id,
        supplier_batch_ref=payload.supplier_batch_ref,
        expected_qty=payload.expected_qty,
        note=payload.note,
    )
    return PartBatchPublic.model_validate(batch)


@router.get(
    "/serialized/{unit_id}/label.pdf",
    dependencies=[Depends(get_admin)],
)
def read_unit_label(*, session: SessionDep, unit_id: uuid.UUID) -> Response:
    unit = crud.get_unit(session=session, unit_id=unit_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    pdf = render_unit_label(
        castranova_barcode=unit.castranova_barcode,
        caption=f"{unit.supplier_serial}",
    )
    return Response(content=pdf, media_type="application/pdf")
