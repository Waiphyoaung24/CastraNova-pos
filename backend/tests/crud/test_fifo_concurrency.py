"""FIFO consumption under concurrency (plan Task 2.3 — the highest-value test).

Fires many consumers at one SKU with limited stock, each on its own Session
against the real Postgres test DB (not SQLite — row locks are the thing under
test). Asserts the §4.6 invariants hold under races: no oversell, no negative
remaining_qty, balanced cost_lines for every winner, and a clean 409 for losers
(never a deadlock or 500)."""

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
    CostLine,
    Location,
    MovementType,
    PartBatch,
    PartMovement,
    ProductCreate,
    SupplierCreate,
    TrackingMode,
)

WORKERS = 8
NEEDED = 3
STOCK = 20  # two batches: 8 + 12
EXPECTED_WINNERS = STOCK // NEEDED  # 6 — each winner takes exactly NEEDED
EXPECTED_CONSUMED = EXPECTED_WINNERS * NEEDED  # 18
EXPECTED_REMAINING = STOCK - EXPECTED_CONSUMED  # 2


@pytest.fixture
def stocked_product(db: Session) -> Iterator[tuple[uuid.UUID, uuid.UUID]]:
    """A QUANTITY product with STOCK units across two batches. Yields
    (product_id, actor_user_id)."""
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"CONC-{uuid.uuid4().hex[:8]}",
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
    yield product.id, user.id


def _consume_once(product_id: uuid.UUID, actor_user_id: uuid.UUID) -> str:
    """One isolated consumer: consume NEEDED, persist a SOLD movement + its
    cost_lines, commit. Returns 'ok', 'conflict', or 'error:<repr>'."""
    with Session(engine) as session:
        try:
            lines = crud.consume_quantity_fifo(
                session=session, product_id=product_id, quantity_needed=NEEDED
            )
            # balanced split: the winner's lines must sum to exactly NEEDED
            assert sum(line.quantity for line in lines) == NEEDED
            movement = PartMovement(
                product_id=product_id,
                event_type=MovementType.SOLD,
                quantity=NEEDED,
                actor_user_id=actor_user_id,
                idempotency_key=uuid.uuid4(),
            )
            session.add(movement)
            session.flush()
            for line in lines:
                line.part_movement_id = movement.id
                session.add(line)
            session.commit()
            return "ok"
        except HTTPException as exc:
            session.rollback()
            return "conflict" if exc.status_code == 409 else f"error:{exc.detail}"
        except Exception as exc:  # deadlock / 500 / anything unexpected
            session.rollback()
            return f"error:{exc!r}"


def test_concurrent_fifo_no_oversell_no_deadlock(
    db: Session, stocked_product: tuple[uuid.UUID, uuid.UUID]
) -> None:
    product_id, actor_user_id = stocked_product

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(
            pool.map(
                lambda _: _consume_once(product_id, actor_user_id), range(WORKERS)
            )
        )

    # No deadlock / 500 / unexpected error surfaced from any worker.
    errors = [r for r in results if r.startswith("error:")]
    assert not errors, errors

    winners = results.count("ok")
    losers = results.count("conflict")
    assert winners == EXPECTED_WINNERS
    assert losers == WORKERS - EXPECTED_WINNERS
    assert losers >= 1  # contention really happened — at least one clean 409

    db.expire_all()
    batches = db.exec(
        select(PartBatch).where(PartBatch.product_id == product_id)
    ).all()
    # No batch driven negative; total stock conserved exactly.
    assert all(b.remaining_qty >= 0 for b in batches)
    assert sum(b.remaining_qty for b in batches) == EXPECTED_REMAINING

    # Every winner's movement has cost_lines summing to its quantity, and the
    # total consumed across the ledger matches the winners.
    movements = db.exec(
        select(PartMovement).where(
            PartMovement.product_id == product_id,
            PartMovement.event_type == MovementType.SOLD,
        )
    ).all()
    assert len(movements) == EXPECTED_WINNERS
    total_costed = 0
    for movement in movements:
        cost_lines = db.exec(
            select(CostLine).where(CostLine.part_movement_id == movement.id)
        ).all()
        assert sum(c.quantity for c in cost_lines) == movement.quantity
        total_costed += sum(c.quantity for c in cost_lines)
    assert total_costed == EXPECTED_CONSUMED
