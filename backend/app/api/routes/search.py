from fastapi import APIRouter, Depends

from app import crud
from app.api.deps import SessionDep, get_current_user
from app.models import SerialSearchResult, SkuSearchResult

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


@router.get("/sku/{sku}", response_model=SkuSearchResult)
def search_sku(*, session: SessionDep, sku: str) -> SkuSearchResult:
    """Batch attribution + quantity-on-hand for a SKU (FR-015). Available to both
    roles; carries no cost fields."""
    return crud.search_sku(session=session, sku=sku)
