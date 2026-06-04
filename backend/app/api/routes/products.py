import uuid

from fastapi import APIRouter, Depends, HTTPException

from app import crud
from app.api.deps import AdminUser, SessionDep, get_admin, get_current_user
from app.models import (
    MinStockLevelUpdate,
    PriceChangePublic,
    ProductCreate,
    ProductPublic,
    ProductUpdate,
)

router = APIRouter(prefix="/products", tags=["products"])


@router.get(
    "/", response_model=list[ProductPublic], dependencies=[Depends(get_current_user)]
)
def read_products(
    session: SessionDep, skip: int = 0, limit: int = 100
) -> list[ProductPublic]:
    return crud.list_products(session=session, skip=skip, limit=limit)  # type: ignore[return-value]


@router.post("/", response_model=ProductPublic, dependencies=[Depends(get_admin)])
def create_product(*, session: SessionDep, product_in: ProductCreate) -> ProductPublic:
    return crud.create_product(session=session, product_in=product_in)  # type: ignore[return-value]


@router.patch("/{product_id}", response_model=ProductPublic)
def update_product(
    *,
    session: SessionDep,
    current_user: AdminUser,
    product_id: uuid.UUID,
    product_in: ProductUpdate,
) -> ProductPublic:
    db_product = crud.get_product(session=session, product_id=product_id)
    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")
    return crud.update_product(  # type: ignore[return-value]
        session=session,
        db_product=db_product,
        product_in=product_in,
        changed_by_user_id=current_user.id,
    )


@router.patch(
    "/{product_id}/min-stock-level",
    response_model=ProductPublic,
    dependencies=[Depends(get_admin)],
)
def set_min_stock_level(
    *,
    session: SessionDep,
    product_id: uuid.UUID,
    payload: MinStockLevelUpdate,
) -> ProductPublic:
    return crud.set_min_stock_level(  # type: ignore[return-value]
        session=session,
        product_id=product_id,
        min_stock_level=payload.min_stock_level,
    )


@router.get(
    "/{product_id}/price-history",
    response_model=list[PriceChangePublic],
    dependencies=[Depends(get_admin)],
)
def read_price_history(
    *, session: SessionDep, product_id: uuid.UUID
) -> list[PriceChangePublic]:
    if not crud.get_product(session=session, product_id=product_id):
        raise HTTPException(status_code=404, detail="Product not found")
    return crud.list_price_history(session=session, product_id=product_id)  # type: ignore[return-value]
