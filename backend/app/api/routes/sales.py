import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from sqlmodel import select

from app import crud
from app.api.deps import (
    AdminUser,
    CurrentUser,
    SessionDep,
    get_admin,
    get_current_user,
    is_admin,
)
from app.models import (
    ReturnableSalesPublic,
    Sale,
    SaleCreateRequest,
    SaleLine,
    SaleLinePublic,
    SaleLineStaffPublic,
    SalePublic,
    SaleReturn,
    SaleReturnCreateRequest,
    SaleReturnLine,
    SaleReturnLinePublic,
    SaleReturnPublic,
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


def _return_to_public(*, session: SessionDep, ret: SaleReturn) -> SaleReturnPublic:
    lines = session.exec(
        select(SaleReturnLine).where(SaleReturnLine.sale_return_id == ret.id)
    ).all()
    return SaleReturnPublic(
        id=ret.id,
        sale_id=ret.sale_id,
        reason=ret.reason,
        returned_at=ret.returned_at,
        total_refund_thb=ret.total_refund_thb,
        total_cogs_restored_thb=ret.total_cogs_restored_thb,
        created_by_user_id=ret.created_by_user_id,
        lines=[SaleReturnLinePublic.model_validate(line) for line in lines],
    )


@router.post("/{sale_id}/returns", response_model=SaleReturnPublic)
def create_sale_return(
    *,
    session: SessionDep,
    admin: AdminUser,
    sale_id: uuid.UUID,
    payload: SaleReturnCreateRequest,
) -> SaleReturnPublic:
    """Record a customer return against a sale (admin-only, design 2026-07-25).

    Restores stock at the original FIFO cost and reverses the sale's margin
    contribution in the RETURN month. Refund is fixed at the original line price.
    """
    ret = crud.create_sale_return(
        session=session,
        sale_id=sale_id,
        payload=payload,
        created_by_user_id=admin.id,
    )
    return _return_to_public(session=session, ret=ret)


# Declared before the /{sale_id} routes: a literal path segment must win over the
# parameterized one, or "returnable" is parsed as a sale id.
@router.get(
    "/returnable",
    response_model=ReturnableSalesPublic,
    dependencies=[Depends(get_admin)],
)
def read_returnable_sales(
    *,
    session: SessionDep,
    castranova_barcode: str | None = None,
    sku: str | None = None,
) -> ReturnableSalesPublic:
    """Recent sales with still-returnable lines for one unit or one SKU.
    Admin-only — it feeds the return flow and exposes line prices."""
    return crud.list_returnable_sales(
        session=session, castranova_barcode=castranova_barcode, sku=sku
    )


# Shared-team access (recorded decision D3, hardening spec 2026-06-11): any
# authenticated staff/admin may act on any sale receipt — the ~5-person
# warehouse team works shifts over shared objects (PRD §5). Ownership scoping
# was considered and rejected. No derived financials are exposed on this
# surface.
@router.get("/{sale_id}/receipt.pdf", dependencies=[Depends(get_current_user)])
def read_sale_receipt(*, session: SessionDep, sale_id: uuid.UUID) -> Response:
    data = crud.get_sale_receipt_data(session=session, sale_id=sale_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Sale not found")
    pdf = render_sale_receipt(
        sale_id=str(data.sale_id),
        sold_at=data.sold_at.isoformat(timespec="seconds"),
        customer_name=data.customer_name,
        sold_by=data.sold_by,
        lines=data.lines,
        total_thb=data.total_thb,
    )
    return Response(content=pdf, media_type="application/pdf")
