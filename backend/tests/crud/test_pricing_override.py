import uuid
from decimal import Decimal

from sqlmodel import Session, select

from app import crud
from app.models import (
    OverrideState,
    OverrideTargetKind,
    PricingOverrideRequest,
    ProductCreate,
    TrackingMode,
    UserCreate,
    UserRole,
)


def _admin(db: Session) -> uuid.UUID:
    user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=f"ovr-{uuid.uuid4()}@example.com",
            password="changethis123",
            role=UserRole.BKK_ADMIN,
        ),
    )
    return user.id


def _product(db: Session, *, retail: str = "1000.00", repair: str = "300.00") -> uuid.UUID:
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"OVR-{uuid.uuid4().hex[:8]}",
            model_name="Override Test",
            brand="Acme",
            category="compressor",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb=Decimal(retail),
            repair_price_thb=Decimal(repair),
        ),
    )
    return product.id


def test_pricing_override_request_persists(db: Session) -> None:
    actor = _admin(db)
    row = PricingOverrideRequest(
        target_kind=OverrideTargetKind.SALE_LINE,
        product_id=_product(db),
        default_price_thb=Decimal("1000.00"),
        requested_price_thb=Decimal("900.00"),
        deviation_pct=Decimal("10.0000"),
        reason="loyal customer",
        state=OverrideState.PENDING,
        created_by_user_id=actor,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    fetched = db.exec(
        select(PricingOverrideRequest).where(
            PricingOverrideRequest.id == row.id
        )
    ).first()
    assert fetched is not None
    assert fetched.target_kind == OverrideTargetKind.SALE_LINE
    assert fetched.requested_price_thb == Decimal("900.00")
    assert fetched.state == OverrideState.PENDING
    assert fetched.created_at is not None
    assert fetched.decided_at is None
