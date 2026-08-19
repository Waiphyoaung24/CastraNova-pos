"""Returns racing sales on the same product (plan Task 8).

Both paths take PartBatch row locks. consume_quantity_fifo locks in
(received_at, id) order (crud.py); _return_part_line MUST use the same order or
the two can deadlock. A divergence shows up here as an "error:" result
(DeadlockDetected), never a silent pass.
"""

import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.core.db import engine
from app.models import (
    CustomerCreate,
    Location,
    MovementType,
    PartBatch,
    PartMovement,
    Product,
    ProductCreate,
    SaleLine,
    SaleLineInput,
    SaleLineKind,
    SaleReturnCreateRequest,
    SaleReturnLineInput,
    SupplierCreate,
    TrackingMode,
)

# Two batches, 20 units. Four seed sales of 3 consume 12 across the batch
# boundary (b1 8 -> 0, b2 12 -> 8), so the returns below have to credit BOTH
# batches while the concurrent sales are draining them.
SEED_SALES = 4
SALE_QTY = 3
RECEIVED_TOTAL = 20
SEEDED_CONSUMED = SEED_SALES * SALE_QTY  # 12


@pytest.fixture
def sold_product(
    db: Session,
) -> Iterator[tuple[uuid.UUID, uuid.UUID, uuid.UUID, list[uuid.UUID]]]:
    """A QUANTITY product with two batches and SEED_SALES committed sales.
    Yields (product_id, customer_id, actor_user_id, [sale_id...])."""
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"RET-{uuid.uuid4().hex[:8]}",
            model_name="Bearing",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="50.00",
            repair_price_thb="10.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name="Acme Parts")
    )
    for qty, cost in ((8, "10.00"), (12, "12.00")):
        crud.receive_quantity(
            session=db,
            product_id=product.id,
            supplier_id=supplier.id,
            received_qty=qty,
            purchase_cost_thb=Decimal(cost),
            idempotency_key=uuid.uuid4(),
            received_by_user_id=user.id,
        )
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Conc Returns")
    )
    sale_ids = [
        crud.create_sale(
            session=db,
            customer_id=customer.id,
            created_by_user_id=user.id,
            idempotency_key=uuid.uuid4(),
            lines=[
                SaleLineInput(
                    line_kind=SaleLineKind.PART,
                    sku=product.sku,
                    quantity=SALE_QTY,
                )
            ],
        ).id
        for _ in range(SEED_SALES)
    ]
    db.commit()  # visible to the worker sessions (separate connections)
    yield product.id, customer.id, user.id, sale_ids


def _line_id(db: Session, sale_id: uuid.UUID) -> uuid.UUID:
    return db.exec(select(SaleLine).where(SaleLine.sale_id == sale_id)).one().id


def _return_once(
    sale_id: uuid.UUID, sale_line_id: uuid.UUID, qty: int, actor_user_id: uuid.UUID
) -> str:
    with Session(engine) as session:
        try:
            crud.create_sale_return(
                session=session,
                sale_id=sale_id,
                payload=SaleReturnCreateRequest(
                    idempotency_key=uuid.uuid4(),
                    reason="concurrent return",
                    lines=[
                        SaleReturnLineInput(sale_line_id=sale_line_id, quantity=qty)
                    ],
                ),
                created_by_user_id=actor_user_id,
            )
            return "ok"
        except HTTPException as exc:
            session.rollback()
            return "conflict" if exc.status_code == 409 else f"error:{exc.detail}"
        except Exception as exc:  # deadlock / 500 / anything unexpected
            session.rollback()
            return f"error:{exc!r}"


def _sell_once(customer_id: uuid.UUID, sku: str, actor_user_id: uuid.UUID) -> str:
    with Session(engine) as session:
        try:
            crud.create_sale(
                session=session,
                customer_id=customer_id,
                created_by_user_id=actor_user_id,
                idempotency_key=uuid.uuid4(),
                lines=[
                    SaleLineInput(
                        line_kind=SaleLineKind.PART, sku=sku, quantity=SALE_QTY
                    )
                ],
            )
            return "ok"
        except HTTPException as exc:
            session.rollback()
            return "conflict" if exc.status_code == 409 else f"error:{exc.detail}"
        except Exception as exc:
            session.rollback()
            return f"error:{exc!r}"


def test_concurrent_returns_and_sales_neither_deadlock_nor_corrupt_stock(
    db: Session,
    sold_product: tuple[uuid.UUID, uuid.UUID, uuid.UUID, list[uuid.UUID]],
) -> None:
    product_id, customer_id, actor_user_id, sale_ids = sold_product
    product = db.get(Product, product_id)
    assert product is not None
    sku = product.sku
    line_ids = [_line_id(db, sid) for sid in sale_ids]

    # SEED_SALES returns (each on its own sale line, so all should win) racing
    # SEED_SALES fresh sales on the same two batches.
    jobs = [
        (lambda sid=sid, lid=lid: _return_once(sid, lid, SALE_QTY, actor_user_id))
        for sid, lid in zip(sale_ids, line_ids, strict=True)
    ] + [
        (lambda: _sell_once(customer_id, sku, actor_user_id))
        for _ in range(SEED_SALES)
    ]
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        results = list(pool.map(lambda job: job(), jobs))

    return_results, sale_results = results[:SEED_SALES], results[SEED_SALES:]

    # No deadlock, no 500, from either side.
    errors = [r for r in results if r.startswith("error:")]
    assert not errors, errors
    # Every return targets a distinct line with nothing returned yet — all win.
    assert return_results == ["ok"] * SEED_SALES
    # Sales either win or take a clean 409; never anything else.
    assert all(r in ("ok", "conflict") for r in sale_results)

    db.expire_all()
    batches = db.exec(
        select(PartBatch).where(PartBatch.product_id == product_id)
    ).all()
    # Bounds hold on every batch (the ck_part_batch_qty_bounds invariant).
    assert all(0 <= b.remaining_qty <= b.received_qty for b in batches)

    # Stock is conserved exactly against the LEDGER, not against thread results:
    # remaining == received - sold + returned. This is the invariant that would
    # break if a racing return and sale double-counted a batch.
    def _moved(event: MovementType) -> int:
        return sum(
            m.quantity
            for m in db.exec(
                select(PartMovement).where(
                    PartMovement.product_id == product_id,
                    PartMovement.event_type == event,
                )
            ).all()
        )

    sold = _moved(MovementType.SOLD)
    returned = _moved(MovementType.RETURNED)
    received = sum(b.received_qty for b in batches)
    assert received == RECEIVED_TOTAL
    assert returned == SEED_SALES * SALE_QTY
    assert sum(b.remaining_qty for b in batches) == received - sold + returned
    # And the ledger agrees with what the threads reported.
    assert sold == SEEDED_CONSUMED + sale_results.count("ok") * SALE_QTY


def test_two_concurrent_returns_of_the_same_line_cannot_over_return(
    db: Session,
    sold_product: tuple[uuid.UUID, uuid.UUID, uuid.UUID, list[uuid.UUID]],
) -> None:
    """The FOR UPDATE lock on the sale line is the ONLY serialization point for
    two returns of the same line — SaleReturnLine rows do not exist yet, so
    locking those would lock nothing. Exactly one thread may win."""
    product_id, _customer_id, actor_user_id, sale_ids = sold_product
    sale_id = sale_ids[0]
    line_id = _line_id(db, sale_id)

    before = sum(
        b.remaining_qty
        for b in db.exec(
            select(PartBatch).where(PartBatch.product_id == product_id)
        ).all()
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: _return_once(sale_id, line_id, SALE_QTY, actor_user_id),
                range(2),
            )
        )

    assert not [r for r in results if r.startswith("error:")], results
    assert results.count("ok") == 1
    assert results.count("conflict") == 1

    db.expire_all()
    after = sum(
        b.remaining_qty
        for b in db.exec(
            select(PartBatch).where(PartBatch.product_id == product_id)
        ).all()
    )
    assert after - before == SALE_QTY  # restocked once, not twice
