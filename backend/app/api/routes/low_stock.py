from fastapi import APIRouter, Depends

from app import crud
from app.api.deps import SessionDep, get_admin, get_current_user
from app.models import (
    BulkMinStockUpdate,
    LowStockItemPublic,
    ProductPublic,
)

router = APIRouter(prefix="/low-stock", tags=["low-stock"])


@router.get(
    "", response_model=list[LowStockItemPublic], dependencies=[Depends(get_current_user)]
)
def read_low_stock(*, session: SessionDep) -> list[LowStockItemPublic]:
    return crud.list_low_stock(session)


@router.patch(
    "/bulk", response_model=list[ProductPublic], dependencies=[Depends(get_admin)]
)
def bulk_set_min_stock_level(
    *, session: SessionDep, payload: BulkMinStockUpdate
) -> list[ProductPublic]:
    products = crud.bulk_set_min_stock_level(
        session=session,
        items=[(item.product_id, item.min_stock_level) for item in payload.items],
    )
    return products  # type: ignore[return-value]
