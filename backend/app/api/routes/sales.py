import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from sqlmodel import select

from app import crud
from app.api.deps import CurrentUser, SessionDep, get_current_user, is_admin
from app.models import (
    Sale,
    SaleCreateRequest,
    SaleLine,
    SaleLinePublic,
    SaleLineStaffPublic,
    SalePublic,
    SaleStaffPublic,
    User,
)
from app.services import notify
from app.services.receipt_pdf import render_sale_receipt

router = APIRouter(prefix="/sales", tags=["sales"])


def _to_public(*, session: SessionDep, sale: Sale, user: User) -> SalePublic | SaleStaffPublic:
    lines = session.exec(select(SaleLine).where(SaleLine.sale_id == sale.id)).all()
    if is_admin(user):
        return SalePublic(
            id=sale.id,
            customer_id=sale.customer_id,
            total_thb=sale.total_thb,
            total_cogs_thb=sale.total_cogs_thb,
            sold_at=sale.sold_at,
            lines=[SaleLinePublic.model_validate(line) for line in lines],
        )
    return SaleStaffPublic(
        id=sale.id,
        customer_id=sale.customer_id,
        total_thb=sale.total_thb,
        sold_at=sale.sold_at,
        lines=[SaleLineStaffPublic.model_validate(line) for line in lines],
    )


@router.post("", response_model=SalePublic | SaleStaffPublic)
def create_sale(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
    payload: SaleCreateRequest,
) -> SalePublic | SaleStaffPublic:
    sale = crud.create_sale(
        session=session,
        customer_id=payload.customer_id,
        lines=payload.lines,
        idempotency_key=payload.idempotency_key,
        created_by_user_id=current_user.id,
    )
    # FR-016: alert when consumption dropped a SKU below its low-stock threshold.
    crossed = crud.pop_low_stock_crossed(session)
    if crossed:
        background_tasks.add_task(notify.notify_low_stock_bg, product_ids=list(crossed))
    return _to_public(session=session, sale=sale, user=current_user)


# Shared-team access (recorded decision D3, hardening spec 2026-06-11): any
# authenticated staff/admin may act on any sale receipt — the ~5-person
# warehouse team works shifts over shared objects (PRD §5). Ownership scoping
# was considered and rejected. No derived financials are exposed on this
# surface.
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
