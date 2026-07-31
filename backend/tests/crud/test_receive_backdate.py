"""Explicit received_at on serialized receives (design 2026-07-25).

One receipt is one delivery, so every piece in a call shares the timestamp."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    Location,
    Product,
    ProductCreate,
    ReceivePiece,
    Supplier,
    SupplierCreate,
    TrackingMode,
    UnitMovement,
    User,
)


@pytest.fixture
def serialized_setup(db: Session) -> tuple[Product, Supplier, User]:
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"SER-{uuid.uuid4().hex[:8]}",
            model_name="Compressor",
            tracking_mode=TrackingMode.SERIALIZED,
            retail_price_thb="1000.00",
            repair_price_thb="200.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"Sup-{uuid.uuid4().hex[:6]}")
    )
    return product, supplier, user


def test_receive_serialized_backdates_all_pieces(
    db: Session, serialized_setup: tuple[Product, Supplier, User]
) -> None:
    product, supplier, user = serialized_setup
    backdated = datetime(2026, 7, 10, 14, 32, tzinfo=timezone.utc)

    units = crud.receive_serialized(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        pieces=[
            ReceivePiece(supplier_serial="SN-B1", purchase_cost_thb=Decimal("900.00")),
            ReceivePiece(supplier_serial="SN-B2", purchase_cost_thb=Decimal("900.00")),
        ],
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user.id,
        received_at=backdated,
    )

    assert len(units) == 2
    assert all(u.received_at == backdated for u in units)


def test_receive_serialized_without_received_at_uses_now(
    db: Session, serialized_setup: tuple[Product, Supplier, User]
) -> None:
    product, supplier, user = serialized_setup
    before = datetime.now(timezone.utc)

    units = crud.receive_serialized(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        pieces=[
            ReceivePiece(supplier_serial="SN-N1", purchase_cost_thb=Decimal("900.00"))
        ],
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user.id,
    )

    assert before - timedelta(seconds=5) <= units[0].received_at
    assert units[0].received_at <= datetime.now(timezone.utc) + timedelta(seconds=5)


def test_receive_serialized_movement_occurred_at_is_not_backdated(
    db: Session, serialized_setup: tuple[Product, Supplier, User]
) -> None:
    """The ledger records WHEN WE RECORDED IT, never the arrival date — the gap
    between the two is itself the audit signal."""
    product, supplier, user = serialized_setup
    backdated = datetime(2026, 7, 10, 14, 32, tzinfo=timezone.utc)

    units = crud.receive_serialized(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        pieces=[
            ReceivePiece(supplier_serial="SN-M1", purchase_cost_thb=Decimal("900.00"))
        ],
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user.id,
        received_at=backdated,
    )

    movement = db.exec(
        select(UnitMovement).where(UnitMovement.unit_id == units[0].id)
    ).one()
    assert movement.occurred_at > backdated + timedelta(days=1)
