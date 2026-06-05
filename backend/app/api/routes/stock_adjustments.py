from fastapi import APIRouter

from app import crud
from app.api.deps import AdminUser, SessionDep
from app.models import StockAdjustmentCreate, StockAdjustmentPublic

router = APIRouter(prefix="/stock-adjustments", tags=["stock-adjustments"])


@router.post("", response_model=StockAdjustmentPublic)
def create_stock_adjustment(
    *,
    session: SessionDep,
    admin: AdminUser,
    payload: StockAdjustmentCreate,
) -> StockAdjustmentPublic:
    """Admin stock write-off / recount (FR-011). SERIALIZED units move to the
    terminal ADJUSTED_OUT state; QUANTITY deltas FIFO-consume (negative) or
    create an ADJ batch (positive). Admin-only; no notifications."""
    adj = crud.create_stock_adjustment(
        session=session, adj_in=payload, created_by_user_id=admin.id
    )
    return StockAdjustmentPublic.model_validate(adj)
