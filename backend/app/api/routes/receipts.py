import uuid

from fastapi import APIRouter, Depends, HTTPException, Response

from app import crud
from app.api.deps import CurrentUser, SessionDep, get_current_user
from app.models import ReceiveSerializedRequest, ReceiveSerializedResponse
from app.services.barcode import render_unit_label

router = APIRouter(prefix="/receipts", tags=["receipts"])


@router.post("/serialized", response_model=ReceiveSerializedResponse)
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


@router.get(
    "/serialized/{unit_id}/label.pdf",
    dependencies=[Depends(get_current_user)],
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
