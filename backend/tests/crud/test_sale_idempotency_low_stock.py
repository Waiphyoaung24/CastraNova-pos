"""Low-stock crossings must NOT survive the idempotency-race rollback (Task 2.8).

``create_sale`` records crossing product_ids in ``session.info`` DURING the FIFO
consume, BEFORE the commit. On the idempotency-race path the final commit raises
``IntegrityError`` and the consume is rolled back — but ``session.info`` is not
transactional, so a stale crossing would otherwise survive, the route would pop
it, and dispatch a DUPLICATE low-stock alert (the winning request already alerts;
the re-check guard does not dedup when stock is genuinely below threshold).

A faithful two-thread same-key race only collides at COMMIT and is timing
dependent, so rather than ship a flaky test we drive the exact rollback branch
deterministically: the sale insert/consume runs for real (recording the
crossing), the FINAL ``session.commit`` is patched to raise ``IntegrityError``
once (the lost race), and ``_sale_by_key`` returns the winner in the except
branch. We then assert the rolled-back crossing was discarded — so the route
pops nothing and never fires a duplicate alert.
"""

import uuid
from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    CustomerCreate,
    Location,
    ProductCreate,
    Sale,
    SaleLineInput,
    SaleLineKind,
    SupplierCreate,
    TrackingMode,
)


@pytest.fixture
def crossing_product(db: Session) -> Iterator[tuple[uuid.UUID, str, uuid.UUID]]:
    """A QUANTITY product, min_stock_level=5, stocked at 6 so a sale of 2 crosses
    below 5 (6 -> 4) — the consume records a low-stock crossing. Yields
    (product_id, sku, customer_id)."""
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"RACE-{uuid.uuid4().hex[:8]}",
            model_name="Widget",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="100.00",
            repair_price_thb="20.00",
            default_min_stock_level=5,
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"Sup-{uuid.uuid4().hex[:6]}")
    )
    crud.receive_quantity(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        received_qty=6,
        purchase_cost_thb=Decimal("10.00"),
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user.id,
    )
    customer_id = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Walk-in")
    ).id
    yield product.id, product.sku, customer_id


def test_idempotency_race_rollback_discards_low_stock_crossing(
    db: Session,
    crossing_product: tuple[uuid.UUID, str, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product_id, sku, customer_id = crossing_product
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    key = uuid.uuid4()

    # Make the FINAL commit raise once (the lost idempotency race), exactly as a
    # concurrent winner committing the same key first would. The sale insert and
    # the FIFO consume run for real beforehand, so the crossing IS recorded in
    # session.info before the failure.
    real_commit = db.commit
    fired = {"done": False}

    def _commit_then_lose() -> None:
        if not fired["done"]:
            fired["done"] = True
            raise IntegrityError("simulated idempotency race", None, Exception())
        real_commit()

    # The replay guard misses (call #1 -> None) so the body runs and the consume
    # records the crossing; the except branch (call #2) returns the winner. The
    # winner is a stand-in for a row a concurrent transaction committed — NOT
    # persisted here, so the racer's own sale insert/flush does not collide and
    # the failure is forced solely at the patched final commit (true to the race).
    winner = Sale(
        customer_id=customer_id,
        created_by_user_id=user.id,
        idempotency_key=key,
        total_thb=Decimal("0.00"),
        total_cogs_thb=Decimal("0.00"),
    )
    winner_id = winner.id
    calls = {"n": 0}

    def _miss_once(*, session: Session, idempotency_key: uuid.UUID) -> Sale | None:  # noqa: ARG001
        # Args mirror _sale_by_key's keyword call; unused — the stub returns the
        # winner on the except-branch (2nd) call without re-querying.
        calls["n"] += 1
        return None if calls["n"] == 1 else winner

    monkeypatch.setattr(crud, "_sale_by_key", _miss_once)
    monkeypatch.setattr(db, "commit", _commit_then_lose)

    returned = crud.create_sale(
        session=db,
        customer_id=customer_id,
        lines=[SaleLineInput(line_kind=SaleLineKind.PART, sku=sku, quantity=2)],
        idempotency_key=key,
        created_by_user_id=user.id,
    )

    # Returned the winner (idempotent), and the crossing recorded during the
    # rolled-back consume was discarded — the route pops nothing, no dup alert.
    assert returned.id == winner_id
    assert crud.pop_low_stock_crossed(db) == set()
