import uuid

from fastapi import APIRouter, Depends

from app import crud
from app.api.deps import SessionDep, get_current_user
from app.models import BatchDrillRow, StockOnHandResponse, UnitDrillRow

router = APIRouter(prefix="/dashboards", tags=["dashboards"])


@router.get(
    "/stock-on-hand",
    response_model=StockOnHandResponse,
    dependencies=[Depends(get_current_user)],
)
def get_stock_on_hand(
    session: SessionDep,
    category: str | None = None,
    supplier: uuid.UUID | None = None,
    customer: uuid.UUID | None = None,
) -> StockOnHandResponse:
    return crud.stock_on_hand(
        session=session,
        category=category,
        supplier_id=supplier,
        customer_id=customer,
    )


@router.get(
    "/stock-on-hand/{product_id}/batches",
    response_model=list[BatchDrillRow],
    dependencies=[Depends(get_current_user)],
)
def get_stock_on_hand_batches(
    session: SessionDep, product_id: uuid.UUID
) -> list[BatchDrillRow]:
    return crud.stock_on_hand_batches(session=session, product_id=product_id)


@router.get(
    "/stock-on-hand/{product_id}/units",
    response_model=list[UnitDrillRow],
    dependencies=[Depends(get_current_user)],
)
def get_stock_on_hand_units(
    session: SessionDep, product_id: uuid.UUID
) -> list[UnitDrillRow]:
    return crud.stock_on_hand_units(session=session, product_id=product_id)
