import uuid

from fastapi import APIRouter, HTTPException, Query

from app import crud
from app.api.deps import CurrentUser, SessionDep, is_admin
from app.models import BatchDrillRow, StockOnHandResponse, UnitDrillRow

router = APIRouter(prefix="/dashboards", tags=["dashboards"])


@router.get("/stock-on-hand", response_model=StockOnHandResponse)
def get_stock_on_hand(
    session: SessionDep,
    current_user: CurrentUser,
    q: str | None = None,
    brand: str | None = None,
    category: str | None = None,
    supplier: uuid.UUID | None = None,
    skip: int = Query(default=0, ge=0, le=10_000),
    limit: int = Query(default=100, ge=1, le=500),
) -> StockOnHandResponse:
    if supplier is not None and not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Supplier filter is admin-only")
    return crud.stock_on_hand(
        session=session,
        q=q,
        brand=brand,
        category=category,
        supplier_id=supplier,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/stock-on-hand/{product_id}/batches",
    response_model=list[BatchDrillRow],
)
def get_stock_on_hand_batches(
    session: SessionDep, current_user: CurrentUser, product_id: uuid.UUID
) -> list[BatchDrillRow]:
    return crud.stock_on_hand_batches(
        session=session,
        product_id=product_id,
        include_supplier=is_admin(current_user),
    )


@router.get(
    "/stock-on-hand/{product_id}/units",
    response_model=list[UnitDrillRow],
)
def get_stock_on_hand_units(
    session: SessionDep, current_user: CurrentUser, product_id: uuid.UUID
) -> list[UnitDrillRow]:
    return crud.stock_on_hand_units(
        session=session,
        product_id=product_id,
        include_supplier=is_admin(current_user),
    )
