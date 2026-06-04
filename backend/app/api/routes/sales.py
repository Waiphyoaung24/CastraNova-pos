import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import select

from app import crud
from app.api.deps import CurrentUser, SessionDep, get_current_user
from app.models import (
    Sale,
    SaleCreateRequest,
    SaleLine,
    SaleLinePublic,
    SalePublic,
)
from app.services.receipt_pdf import render_sale_receipt

router = APIRouter(prefix="/sales", tags=["sales"])


def _to_public(*, session: SessionDep, sale: Sale) -> SalePublic:
    lines = session.exec(select(SaleLine).where(SaleLine.sale_id == sale.id)).all()
    return SalePublic(
        id=sale.id,
        customer_id=sale.customer_id,
        total_thb=sale.total_thb,
        total_cogs_thb=sale.total_cogs_thb,
        sold_at=sale.sold_at,
        lines=[SaleLinePublic.model_validate(line) for line in lines],
    )


@router.post("", response_model=SalePublic)
def create_sale(
    *, session: SessionDep, current_user: CurrentUser, payload: SaleCreateRequest
) -> SalePublic:
    sale = crud.create_sale(
        session=session,
        customer_id=payload.customer_id,
        lines=payload.lines,
        idempotency_key=payload.idempotency_key,
        created_by_user_id=current_user.id,
    )
    return _to_public(session=session, sale=sale)


@router.get("/{sale_id}/receipt.pdf", dependencies=[Depends(get_current_user)])
def read_sale_receipt(*, session: SessionDep, sale_id: uuid.UUID) -> Response:
    sale = crud.get_sale(session=session, sale_id=sale_id)
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    lines = session.exec(select(SaleLine).where(SaleLine.sale_id == sale.id)).all()
    pdf = render_sale_receipt(
        sale_id=str(sale.id),
        sold_at=sale.sold_at.isoformat(timespec="seconds"),
        lines=[
            (line.line_kind.value, line.quantity, line.unit_price_thb)
            for line in lines
        ],
        total_thb=sale.total_thb,
    )
    return Response(content=pdf, media_type="application/pdf")
