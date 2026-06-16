from fastapi import APIRouter, Depends

from app import crud
from app.api.deps import CurrentUser, SessionDep, get_current_user, is_admin
from app.models import (
    SerialSearchResult,
    SkuSearchAdminResult,
    SkuSearchResult,
)

router = APIRouter(
    prefix="/search",
    tags=["search"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/serial/{barcode}", response_model=SerialSearchResult)
def search_serial(*, session: SessionDep, barcode: str) -> SerialSearchResult:
    """Full lifecycle of a serialized unit by barcode, chronological (FR-015).
    Available to both roles; carries no cost fields."""
    return crud.search_serial(session=session, barcode=barcode)


@router.get(
    "/sku/{sku}", response_model=SkuSearchAdminResult | SkuSearchResult
)
def search_sku(
    *, session: SessionDep, current_user: CurrentUser, sku: str
) -> SkuSearchAdminResult | SkuSearchResult:
    """Batch attribution + QOH + consumption history for a SKU (FR-015). Admins
    see FIFO cost; staff see attribution without cost (spec §6.5)."""
    return crud.search_sku(
        session=session, sku=sku, is_admin=is_admin(current_user)
    )
