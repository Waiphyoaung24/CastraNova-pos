import uuid
from datetime import date

import pytest
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.models import (
    PartBatch,
    Product,
    ProductCreate,
    Supplier,
    SupplierCreate,
    TrackingMode,
    User,
)


@pytest.fixture
def quantity_setup(db: Session) -> tuple[Product, Supplier, User]:
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"QTY-{uuid.uuid4().hex[:8]}",
            model_name="Bearing",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="50.00",
            repair_price_thb="10.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name="Acme Parts")
    )
    return product, supplier, user


def _persist_batch(
    db: Session,
    product: Product,
    supplier: Supplier,
    user: User,
    batch_no: str,
) -> None:
    db.add(
        PartBatch(
            product_id=product.id,
            batch_no=batch_no,
            supplier_id=supplier.id,
            received_qty=10,
            remaining_qty=10,
            purchase_cost_thb="5.00",
            received_by_user_id=user.id,
        )
    )
    db.commit()


def test_next_batch_no_sequential_same_sku_same_day(
    db: Session, quantity_setup: tuple[Product, Supplier, User]
) -> None:
    product, supplier, user = quantity_setup
    sku = product.sku
    today = date(2026, 6, 4)

    a = crud.next_batch_no(session=db, sku=sku, today=today)
    assert a == f"20260604-{sku}-001"
    _persist_batch(db, product, supplier, user, a)

    b = crud.next_batch_no(session=db, sku=sku, today=today)
    assert b == f"20260604-{sku}-002"


def test_next_batch_no_resets_next_day(
    db: Session, quantity_setup: tuple[Product, Supplier, User]
) -> None:
    product, supplier, user = quantity_setup
    sku = product.sku

    a = crud.next_batch_no(session=db, sku=sku, today=date(2026, 6, 4))
    _persist_batch(db, product, supplier, user, a)

    b = crud.next_batch_no(session=db, sku=sku, today=date(2026, 6, 5))
    assert b == f"20260605-{sku}-001"


def test_next_batch_no_adj_sequence_is_independent(
    db: Session, quantity_setup: tuple[Product, Supplier, User]
) -> None:
    product, supplier, user = quantity_setup
    sku = product.sku
    today = date(2026, 6, 4)

    plain = crud.next_batch_no(session=db, sku=sku, today=today)
    _persist_batch(db, product, supplier, user, plain)

    adj = crud.next_batch_no(session=db, sku=sku, today=today, adj=True)
    assert adj == f"20260604-{sku}-ADJ-001"
