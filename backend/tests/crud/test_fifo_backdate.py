"""A backdated receipt must reorder FIFO consumption and correct the
holding-period figure — the two behaviours the receive date picker exists for
(design 2026-07-25). received_at is BOTH the FIFO sort key and the
holding-period basis, so these move together by design."""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    Location,
    PartBatch,
    Product,
    ProductCreate,
    ReceivePiece,
    Supplier,
    SupplierCreate,
    TrackingMode,
    User,
    get_datetime_utc,
)


@pytest.fixture
def qty_setup(db: Session) -> tuple[Product, Supplier, User]:
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"FIFOBD-{uuid.uuid4().hex[:8]}",
            model_name="Bearing",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="50.00",
            repair_price_thb="10.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"Sup-{uuid.uuid4().hex[:6]}")
    )
    return product, supplier, user


def test_backdated_batch_is_consumed_before_existing_newer_stock(
    db: Session, qty_setup: tuple[Product, Supplier, User]
) -> None:
    """THE core behavioural claim of this feature. Stock already on the shelf is
    received today at 100; a delivery that physically arrived 15 days ago is then
    keyed in at 80. The next sale must draw from the 80 batch, because it arrived
    first."""
    product, supplier, user = qty_setup

    newer = crud.receive_quantity(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        received_qty=5,
        purchase_cost_thb=Decimal("100.00"),
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user.id,
    )
    older = crud.receive_quantity(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        received_qty=5,
        purchase_cost_thb=Decimal("80.00"),
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user.id,
        received_at=get_datetime_utc() - timedelta(days=15),
    )

    crud.consume_quantity_fifo(session=db, product_id=product.id, quantity_needed=5)
    # consume_quantity_fifo leaves the decrement pending for its caller to commit
    # (see its docstring). expire_all() here would DISCARD that pending change.
    db.commit()

    drained = db.get(PartBatch, older.id)
    untouched = db.get(PartBatch, newer.id)
    assert drained is not None and untouched is not None
    assert drained.remaining_qty == 0, "the backdated batch must be consumed first"
    assert untouched.remaining_qty == 5, "today's batch must be left alone"


def test_backdated_batch_reports_its_real_holding_age(
    db: Session, qty_setup: tuple[Product, Supplier, User]
) -> None:
    """The bug this feature fixes: a delivery entered late used to report ~0
    holding days instead of its true age."""
    product, supplier, user = qty_setup
    crud.receive_quantity(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        received_qty=5,
        purchase_cost_thb=Decimal("80.00"),
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user.id,
        received_at=get_datetime_utc() - timedelta(days=120),
    )

    report = crud.holding_period_report(session=db)
    rows = [r for r in report.rows if r.sku == product.sku]
    assert len(rows) == 1
    assert rows[0].holding_days >= 119
    assert rows[0].over_threshold is True


def test_backdated_serialized_unit_reports_its_real_holding_age(
    db: Session, qty_setup: tuple[Product, Supplier, User]
) -> None:
    _product, supplier, user = qty_setup
    sproduct = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"SERBD-{uuid.uuid4().hex[:8]}",
            model_name="Machine",
            tracking_mode=TrackingMode.SERIALIZED,
            retail_price_thb="1000.00",
            repair_price_thb="300.00",
        ),
    )
    units = crud.receive_serialized(
        session=db,
        product_id=sproduct.id,
        supplier_id=supplier.id,
        pieces=[
            ReceivePiece(supplier_serial="SN-BD1", purchase_cost_thb=Decimal("600.00"))
        ],
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user.id,
        received_at=get_datetime_utc() - timedelta(days=120),
    )

    report = crud.holding_period_report(session=db)
    rows = [r for r in report.rows if r.reference == units[0].castranova_barcode]
    assert len(rows) == 1
    assert rows[0].holding_days >= 119
    assert rows[0].over_threshold is True


def test_replay_of_a_backdated_receive_does_not_redate_it(
    db: Session, qty_setup: tuple[Product, Supplier, User]
) -> None:
    """Idempotent replay returns the stored row untouched — a retry days later
    must not shift the arrival date it already recorded."""
    product, supplier, user = qty_setup
    key = uuid.uuid4()
    backdated = get_datetime_utc() - timedelta(days=30)

    first = crud.receive_quantity(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        received_qty=5,
        purchase_cost_thb=Decimal("80.00"),
        idempotency_key=key,
        received_by_user_id=user.id,
        received_at=backdated,
    )
    replay = crud.receive_quantity(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        received_qty=5,
        purchase_cost_thb=Decimal("80.00"),
        idempotency_key=key,
        received_by_user_id=user.id,
        received_at=get_datetime_utc(),
    )

    assert replay.id == first.id
    assert replay.received_at == first.received_at
