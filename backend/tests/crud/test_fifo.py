import uuid
from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    Location,
    PartBatch,
    ProductCreate,
    SupplierCreate,
    TrackingMode,
)


@pytest.fixture
def quantity_product(db: Session) -> Iterator[tuple[uuid.UUID, uuid.UUID]]:
    """A QUANTITY product + supplier + YGN_WH location. Yields (product_id,
    supplier_id)."""
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"FIFO-{uuid.uuid4().hex[:8]}",
            model_name="Bearing",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="50.00",
            repair_price_thb="10.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name="Acme Parts")
    )
    yield product.id, supplier.id


def _receive(
    db: Session,
    product_id: uuid.UUID,
    supplier_id: uuid.UUID,
    qty: int,
    cost: str,
) -> None:
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    crud.receive_quantity(
        session=db,
        product_id=product_id,
        supplier_id=supplier_id,
        received_qty=qty,
        purchase_cost_thb=Decimal(cost),
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user.id,
    )


def _remaining(db: Session, product_id: uuid.UUID) -> int:
    db.expire_all()
    return sum(
        b.remaining_qty
        for b in db.exec(
            select(PartBatch).where(PartBatch.product_id == product_id)
        ).all()
    )


def test_fifo_single_batch_partial(
    db: Session, quantity_product: tuple[uuid.UUID, uuid.UUID]
) -> None:
    pid, sid = quantity_product
    _receive(db, pid, sid, qty=10, cost="5.00")

    lines = crud.consume_quantity_fifo(
        session=db, product_id=pid, quantity_needed=4
    )
    db.commit()

    assert len(lines) == 1
    assert lines[0].quantity == 4
    assert lines[0].unit_cost_thb == Decimal("5.00")
    assert _remaining(db, pid) == 6


def test_fifo_exact_match_drains_batch(
    db: Session, quantity_product: tuple[uuid.UUID, uuid.UUID]
) -> None:
    pid, sid = quantity_product
    _receive(db, pid, sid, qty=10, cost="5.00")

    lines = crud.consume_quantity_fifo(
        session=db, product_id=pid, quantity_needed=10
    )
    db.commit()

    assert sum(line.quantity for line in lines) == 10
    assert _remaining(db, pid) == 0


def test_fifo_spans_two_batches_oldest_first(
    db: Session, quantity_product: tuple[uuid.UUID, uuid.UUID]
) -> None:
    pid, sid = quantity_product
    _receive(db, pid, sid, qty=3, cost="10.00")  # older
    _receive(db, pid, sid, qty=4, cost="12.00")  # newer

    lines = crud.consume_quantity_fifo(
        session=db, product_id=pid, quantity_needed=5
    )
    db.commit()

    assert [(line.quantity, str(line.unit_cost_thb)) for line in lines] == [
        (3, "10.00"),
        (2, "12.00"),
    ]
    assert sum(line.quantity for line in lines) == 5
    assert _remaining(db, pid) == 2  # 7 received, 5 consumed


def test_fifo_oversell_raises_409_with_available(
    db: Session, quantity_product: tuple[uuid.UUID, uuid.UUID]
) -> None:
    pid, sid = quantity_product
    _receive(db, pid, sid, qty=3, cost="10.00")
    _receive(db, pid, sid, qty=4, cost="12.00")  # total 7

    with pytest.raises(HTTPException) as exc:
        crud.consume_quantity_fifo(session=db, product_id=pid, quantity_needed=8)
    db.rollback()

    assert exc.value.status_code == 409
    assert "7" in str(exc.value.detail)  # real available total surfaced
    # The sale screen keys its dedicated "Insufficient Stock" toast title on
    # this exact prefix (INSUFFICIENT_STOCK_PREFIX in
    # frontend/src/routes/_layout/sale.tsx). Reword the message and that screen
    # silently degrades to a generic error, so pin the prefix here rather than
    # letting the UI regression escape unnoticed.
    assert str(exc.value.detail).startswith("Insufficient stock")
    # No stock consumed on the failed call.
    assert _remaining(db, pid) == 7


def test_fifo_cost_line_total_invariant(
    db: Session, quantity_product: tuple[uuid.UUID, uuid.UUID]
) -> None:
    pid, sid = quantity_product
    _receive(db, pid, sid, qty=3, cost="10.00")
    _receive(db, pid, sid, qty=4, cost="12.00")

    lines = crud.consume_quantity_fifo(
        session=db, product_id=pid, quantity_needed=5
    )
    db.commit()

    for line in lines:
        assert line.total_cost_thb == line.quantity * line.unit_cost_thb


@pytest.mark.parametrize("bad", [0, -3])
def test_fifo_rejects_nonpositive_quantity(
    db: Session, quantity_product: tuple[uuid.UUID, uuid.UUID], bad: int
) -> None:
    pid, sid = quantity_product
    _receive(db, pid, sid, qty=5, cost="10.00")

    with pytest.raises(HTTPException) as exc:
        crud.consume_quantity_fifo(session=db, product_id=pid, quantity_needed=bad)
    db.rollback()

    assert exc.value.status_code == 400
    assert _remaining(db, pid) == 5  # no stock touched
