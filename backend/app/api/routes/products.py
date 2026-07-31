import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app import crud
from app.api.deps import AdminUser, SessionDep, get_admin, get_current_user
from app.models import (
    MinStockLevelUpdate,
    PriceChangePublic,
    ProductCreate,
    ProductOption,
    ProductPublic,
    ProductPurchaseCost,
    ProductsPublic,
    ProductUpdate,
    TrackingMode,
)
from app.services.barcode import render_label_sheet

router = APIRouter(prefix="/products", tags=["products"])


def _public(product: object, *, is_fresh: bool) -> ProductPublic:
    """Serialize a Product ORM row to ProductPublic, stamping the computed
    is_fresh flag (whether the SKU is still editable)."""
    data = ProductPublic.model_validate(product, from_attributes=True)
    data.is_fresh = is_fresh
    return data


@router.get(
    "/", response_model=ProductsPublic, dependencies=[Depends(get_current_user)]
)
def read_products(
    session: SessionDep,
    q: Annotated[
        str | None,
        Query(
            max_length=255,
            description="Case-insensitive substring match on SKU or model name",
        ),
    ] = None,
    brand: Annotated[
        str | None,
        Query(max_length=255, description="Case-insensitive substring match on brand"),
    ] = None,
    category: Annotated[
        str | None,
        Query(
            max_length=128, description="Case-insensitive substring match on category"
        ),
    ] = None,
    tracking_mode: TrackingMode | None = None,
    is_active: Annotated[
        bool | None, Query(description="Filter by active/inactive status")
    ] = None,
    skip: Annotated[int, Query(ge=0, le=10_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> ProductsPublic:
    products = crud.list_products(
        session=session,
        q=q,
        brand=brand,
        category=category,
        tracking_mode=tracking_mode,
        is_active=is_active,
        skip=skip,
        limit=limit,
    )
    fresh = crud.products_fresh_ids(
        session=session, product_ids=[p.id for p in products]
    )
    return ProductsPublic(
        data=[_public(p, is_fresh=p.id in fresh) for p in products],
        count=crud.count_products(
            session=session,
            q=q,
            brand=brand,
            category=category,
            tracking_mode=tracking_mode,
            is_active=is_active,
        ),
    )


@router.get(
    "/purchase-costs",
    response_model=list[ProductPurchaseCost],
    dependencies=[Depends(get_admin)],
)
def read_purchase_costs(session: SessionDep) -> list[ProductPurchaseCost]:
    """Latest purchase cost per product (admin-only COGS). One entry per product
    that has at least one receipt."""
    costs = crud.latest_purchase_costs(session=session)
    return [
        ProductPurchaseCost(product_id=pid, latest_purchase_cost_thb=cost)
        for pid, cost in costs.items()
    ]


@router.get(
    "/options",
    response_model=list[ProductOption],
    dependencies=[Depends(get_current_user)],
)
def read_options(session: SessionDep, active_only: bool = False) -> list[ProductOption]:
    """Every product as a lightweight picker/lookup projection, ordered by SKU
    (FR-019 audit filter; sale/receive/tickets/pulls/pricing-overrides product
    selection). Deliberately unpaginated: no client parameter can amplify the
    response size, and it is far lighter than the full ProductPublic (no specs
    JSONB, no brand/category/timestamps)."""
    return crud.list_product_options(session=session, active_only=active_only)


# Shared-team access (mirrors the serialized unit-label endpoint): any
# authenticated staff/admin may print SKU labels. The QR encodes the raw
# product.sku, which resolves via GET /search/sku/{sku}. No financials exposed.
@router.get("/{product_id}/label.pdf", dependencies=[Depends(get_current_user)])
def read_sku_label(
    *,
    session: SessionDep,
    product_id: uuid.UUID,
    qty: Annotated[int, Query(ge=1, le=1000)] = 1,
) -> Response:
    """Print N identical SKU/bin QR labels for a QUANTITY product."""
    product = crud.get_product(session=session, product_id=product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if product.tracking_mode == TrackingMode.SERIALIZED:
        raise HTTPException(
            status_code=400,
            detail="SKU labels are only for quantity-tracked products",
        )
    pdf = render_label_sheet(
        qr_value=product.sku,
        line1=product.sku,
        line2=product.model_name,
        qty=qty,
    )
    return Response(content=pdf, media_type="application/pdf")


@router.post("/", response_model=ProductPublic, dependencies=[Depends(get_admin)])
def create_product(*, session: SessionDep, product_in: ProductCreate) -> ProductPublic:
    product = crud.create_product(session=session, product_in=product_in)
    # A brand-new product has no stock/transactions, so it is always fresh.
    return _public(product, is_fresh=True)


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
    product = crud.update_product(
        session=session,
        db_product=db_product,
        product_in=product_in,
        changed_by_user_id=current_user.id,
    )
    return _public(
        product,
        is_fresh=crud.is_product_fresh(session=session, product_id=product.id),
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
    product = crud.set_min_stock_level(
        session=session,
        product_id=product_id,
        min_stock_level=payload.min_stock_level,
    )
    return _public(
        product,
        is_fresh=crud.is_product_fresh(session=session, product_id=product.id),
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
    return crud.list_price_history(session=session, product_id=product_id)
