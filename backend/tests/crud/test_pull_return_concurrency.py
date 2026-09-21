"""Pull returns racing sales on the same product (design 2026-09-21).

A pull return re-credits batches via _reverse_part_out, which re-locks in
(received_at, id) order — the same order consume_quantity_fifo takes. Any
divergence shows up here as an "error:" result (DeadlockDetected), never a
silent pass. Mirrors test_return_concurrency.py.
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
    ProductCreate,
    ProjectCreate,
    ProjectPullCreate,
    ProjectPullLineCreate,
    ProjectPullReturnCreate,
    ProjectPullReturnLine,
    SaleLineInput,
    SaleLineKind,
    SupplierCreate,
    TrackingMode,
)

PULLS = 4
PULL_QTY = 3
RECEIVED = 20  # 8@10 + 12@12; 4 pulls of 3 cross the batch boundary


@pytest.fixture
def pulled(db: Session) -> Iterator[tuple[str, uuid.UUID, uuid.UUID, list[tuple[uuid.UUID, uuid.UUID]]]]:
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"PRET-{uuid.uuid4().hex[:8]}",
            model_name="Bearing",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="50.00",
            repair_price_thb="10.00",
        ),
    )
    supplier = crud.create_supplier(session=db, supplier_in=SupplierCreate(name="Acme"))
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
    customer = crud.create_customer(session=db, customer_in=CustomerCreate(name="Conc Pull"))
    project = crud.create_project(
        session=db,
        project_in=ProjectCreate(code=f"PRJ-{uuid.uuid4().hex[:8]}", name="Site", customer_id=customer.id),
    )
    pulls: list[tuple[uuid.UUID, uuid.UUID]] = []
    for _ in range(PULLS):
        pull = crud.create_project_pull(
            session=db,
            pull_in=ProjectPullCreate(
                project_id=project.id,
                lines=[
                    ProjectPullLineCreate(
                        line_kind=SaleLineKind.PART, product_id=product.id, requested_qty=PULL_QTY
                    )
                ],
            ),
            created_by_user_id=user.id,
        )
        crud.fulfill_project_pull(session=db, pull_id=pull.id, fulfill_lines=[], actor_user_id=user.id)
        line = crud.list_project_pull_lines(session=db, pull_id=pull.id)[0]
        pulls.append((pull.id, line.id))
    db.commit()
    yield product.sku, customer.id, user.id, pulls


def _return_once(pull_id: uuid.UUID, line_id: uuid.UUID, actor: uuid.UUID) -> str:
    with Session(engine) as session:
        try:
            crud.return_project_pull(
                session=session,
                pull_id=pull_id,
                payload=ProjectPullReturnCreate(
                    idempotency_key=uuid.uuid4(),
                    lines=[ProjectPullReturnLine(line_id=line_id, quantity=PULL_QTY)],
                ),
                actor_user_id=actor,
            )
            return "ok"
        except HTTPException as exc:
            session.rollback()
            return "conflict" if exc.status_code == 409 else f"error:{exc.detail}"
        except Exception as exc:  # deadlock / 500 / anything unexpected
            session.rollback()
            return f"error:{exc!r}"


def _sell_once(customer_id: uuid.UUID, sku: str, actor: uuid.UUID) -> str:
    with Session(engine) as session:
        try:
            crud.create_sale(
                session=session,
                customer_id=customer_id,
                created_by_user_id=actor,
                idempotency_key=uuid.uuid4(),
                lines=[SaleLineInput(line_kind=SaleLineKind.PART, sku=sku, quantity=PULL_QTY)],
            )
            return "ok"
        except HTTPException as exc:
            session.rollback()
            return "conflict" if exc.status_code == 409 else f"error:{exc.detail}"
        except Exception as exc:
            session.rollback()
            return f"error:{exc!r}"


def test_concurrent_pull_returns_and_sales_neither_deadlock_nor_corrupt_stock(
    db: Session,
    pulled: tuple[str, uuid.UUID, uuid.UUID, list[tuple[uuid.UUID, uuid.UUID]]],
) -> None:
    sku, customer_id, actor, pulls = pulled
    jobs = [
        (lambda p=p, ln=ln: _return_once(p, ln, actor)) for p, ln in pulls
    ] + [(lambda: _sell_once(customer_id, sku, actor)) for _ in range(PULLS)]
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        results = list(pool.map(lambda job: job(), jobs))

    errors = [r for r in results if r.startswith("error:")]
    assert not errors, errors
    assert results[:PULLS] == ["ok"] * PULLS  # distinct pulls, all win
    assert all(r in ("ok", "conflict") for r in results[PULLS:])

    db.expire_all()
    product_id = db.exec(select(PartMovement.product_id).where(PartMovement.project_pull_id == pulls[0][0])).first()
    batches = db.exec(select(PartBatch).where(PartBatch.product_id == product_id)).all()
    assert all(0 <= b.remaining_qty <= b.received_qty for b in batches)

    def _moved(event: MovementType) -> int:
        return sum(
            m.quantity
            for m in db.exec(
                select(PartMovement).where(
                    PartMovement.product_id == product_id, PartMovement.event_type == event
                )
            ).all()
        )

    on_hand = sum(b.remaining_qty for b in batches)
    assert on_hand == RECEIVED - _moved(MovementType.PROJECT_OUT) - _moved(MovementType.SOLD) + _moved(MovementType.RETURNED)
