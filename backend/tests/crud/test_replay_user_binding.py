"""Idempotency replays must be bound to the original actor.

Hardening spec §4.1.2 / spec §6.6 addendum: a same-key request from a DIFFERENT
user is a stolen/duplicated key (keys are client-generated 122-bit UUIDs), so
the replay path raises 409 instead of handing back another user's row. A
same-key replay from the SAME user keeps returning the existing row.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    CustomerCreate,
    Location,
    ProductCreate,
    ReceivePiece,
    SaleLineInput,
    SaleLineKind,
    SupplierCreate,
    TrackingMode,
    User,
)
from tests.utils.user import create_random_user


def _seed_users(db: Session) -> tuple[User, User]:
    """The acting superuser (original actor) and a second, different user."""
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    actor = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert actor is not None
    other = create_random_user(db)
    return actor, other


def _serialized_product_and_supplier(db: Session) -> tuple[uuid.UUID, uuid.UUID]:
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"RUB-SER-{uuid.uuid4().hex[:8]}",
            model_name="Compressor",
            tracking_mode=TrackingMode.SERIALIZED,
            retail_price_thb="1000.00",
            repair_price_thb="200.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"RUB-{uuid.uuid4().hex[:6]}")
    )
    return product.id, supplier.id


def _quantity_product_and_supplier(db: Session) -> tuple[uuid.UUID, str, uuid.UUID]:
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"RUB-QTY-{uuid.uuid4().hex[:8]}",
            model_name="Bearing",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="100.00",
            repair_price_thb="20.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"RUB-{uuid.uuid4().hex[:6]}")
    )
    return product.id, product.sku, supplier.id


# --- receive_serialized --------------------------------------------------------


def test_receive_serialized_replay_different_user_409(db: Session) -> None:
    """Same key, different user -> 409 (spec §4.1.2 / §6.6 addendum)."""
    actor, other = _seed_users(db)
    product_id, supplier_id = _serialized_product_and_supplier(db)
    key = uuid.uuid4()
    pieces = [
        ReceivePiece(
            supplier_serial=f"SN-{uuid.uuid4().hex[:6]}",
            purchase_cost_thb=Decimal("900.00"),
        )
    ]
    crud.receive_serialized(
        session=db,
        product_id=product_id,
        supplier_id=supplier_id,
        pieces=pieces,
        idempotency_key=key,
        received_by_user_id=actor.id,
    )
    with pytest.raises(HTTPException) as exc_info:
        crud.receive_serialized(
            session=db,
            product_id=product_id,
            supplier_id=supplier_id,
            pieces=pieces,
            idempotency_key=key,
            received_by_user_id=other.id,
        )
    assert exc_info.value.status_code == 409


def test_receive_serialized_replay_same_user_returns_same_units(db: Session) -> None:
    """Same key, same user -> replay returns the existing units (§6.6 addendum)."""
    actor, _ = _seed_users(db)
    product_id, supplier_id = _serialized_product_and_supplier(db)
    key = uuid.uuid4()
    pieces = [
        ReceivePiece(
            supplier_serial=f"SN-{uuid.uuid4().hex[:6]}",
            purchase_cost_thb=Decimal("900.00"),
        )
    ]
    first = crud.receive_serialized(
        session=db,
        product_id=product_id,
        supplier_id=supplier_id,
        pieces=pieces,
        idempotency_key=key,
        received_by_user_id=actor.id,
    )
    replay = crud.receive_serialized(
        session=db,
        product_id=product_id,
        supplier_id=supplier_id,
        pieces=pieces,
        idempotency_key=key,
        received_by_user_id=actor.id,
    )
    assert [u.id for u in replay] == [u.id for u in first]
    # Identity is pinned from the stored row, not rebuilt from the caller.
    assert replay[0].received_by_user_id == actor.id


# --- receive_quantity ----------------------------------------------------------


def test_receive_quantity_replay_different_user_409(db: Session) -> None:
    """Same key, different user -> 409 (spec §4.1.2 / §6.6 addendum)."""
    actor, other = _seed_users(db)
    product_id, _, supplier_id = _quantity_product_and_supplier(db)
    key = uuid.uuid4()
    crud.receive_quantity(
        session=db,
        product_id=product_id,
        supplier_id=supplier_id,
        received_qty=5,
        purchase_cost_thb=Decimal("10.00"),
        idempotency_key=key,
        received_by_user_id=actor.id,
    )
    with pytest.raises(HTTPException) as exc_info:
        crud.receive_quantity(
            session=db,
            product_id=product_id,
            supplier_id=supplier_id,
            received_qty=5,
            purchase_cost_thb=Decimal("10.00"),
            idempotency_key=key,
            received_by_user_id=other.id,
        )
    assert exc_info.value.status_code == 409


def test_receive_quantity_replay_same_user_returns_same_batch(db: Session) -> None:
    """Same key, same user -> replay returns the existing batch (§6.6 addendum)."""
    actor, _ = _seed_users(db)
    product_id, _, supplier_id = _quantity_product_and_supplier(db)
    key = uuid.uuid4()
    first = crud.receive_quantity(
        session=db,
        product_id=product_id,
        supplier_id=supplier_id,
        received_qty=5,
        purchase_cost_thb=Decimal("10.00"),
        idempotency_key=key,
        received_by_user_id=actor.id,
    )
    replay = crud.receive_quantity(
        session=db,
        product_id=product_id,
        supplier_id=supplier_id,
        received_qty=5,
        purchase_cost_thb=Decimal("10.00"),
        idempotency_key=key,
        received_by_user_id=actor.id,
    )
    assert replay.id == first.id
    # Identity is pinned from the stored row, not rebuilt from the caller.
    assert replay.received_by_user_id == actor.id


# --- create_sale ----------------------------------------------------------------


def _seed_sale(
    db: Session, actor_id: uuid.UUID, key: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID, list[SaleLineInput]]:
    """Stock a QUANTITY product and create a sale with ``key``; returns
    (sale_id, customer_id, lines) so the caller can replay the same request."""
    product_id, sku, supplier_id = _quantity_product_and_supplier(db)
    crud.receive_quantity(
        session=db,
        product_id=product_id,
        supplier_id=supplier_id,
        received_qty=5,
        purchase_cost_thb=Decimal("10.00"),
        idempotency_key=uuid.uuid4(),
        received_by_user_id=actor_id,
    )
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Walk-in")
    )
    lines = [SaleLineInput(line_kind=SaleLineKind.PART, sku=sku, quantity=2)]
    sale = crud.create_sale(
        session=db,
        customer_id=customer.id,
        lines=lines,
        idempotency_key=key,
        created_by_user_id=actor_id,
    )
    return sale.id, customer.id, lines


def test_create_sale_replay_different_user_409(db: Session) -> None:
    """Same key, different user -> 409 (spec §4.1.2 / §6.6 addendum)."""
    actor, other = _seed_users(db)
    key = uuid.uuid4()
    _, customer_id, lines = _seed_sale(db, actor.id, key)
    with pytest.raises(HTTPException) as exc_info:
        crud.create_sale(
            session=db,
            customer_id=customer_id,
            lines=lines,
            idempotency_key=key,
            created_by_user_id=other.id,
        )
    assert exc_info.value.status_code == 409


def test_create_sale_replay_same_user_returns_same_sale(db: Session) -> None:
    """Same key, same user -> replay returns the existing sale (§6.6 addendum)."""
    actor, _ = _seed_users(db)
    key = uuid.uuid4()
    sale_id, customer_id, lines = _seed_sale(db, actor.id, key)
    replay = crud.create_sale(
        session=db,
        customer_id=customer_id,
        lines=lines,
        idempotency_key=key,
        created_by_user_id=actor.id,
    )
    assert replay.id == sale_id
    # Identity is pinned from the stored row, not rebuilt from the caller.
    assert replay.created_by_user_id == actor.id


# --- record_service_ticket -------------------------------------------------------


def test_record_service_ticket_replay_different_user_409(db: Session) -> None:
    """Same key, different user -> 409 (spec §4.1.2 / §6.6 addendum)."""
    actor, other = _seed_users(db)
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Ticket Cust")
    )
    key = uuid.uuid4()
    crud.record_service_ticket(
        session=db,
        customer_id=customer.id,
        issue="noisy",
        parts=[],
        idempotency_key=key,
        actor_user_id=actor.id,
    )
    with pytest.raises(HTTPException) as exc_info:
        crud.record_service_ticket(
            session=db,
            customer_id=customer.id,
            issue="noisy",
            parts=[],
            idempotency_key=key,
            actor_user_id=other.id,
        )
    assert exc_info.value.status_code == 409


def test_record_service_ticket_replay_same_user_returns_same_ticket(
    db: Session,
) -> None:
    """Same key, same user -> replay returns the existing ticket (§6.6 addendum)."""
    actor, _ = _seed_users(db)
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Ticket Cust")
    )
    key = uuid.uuid4()
    first = crud.record_service_ticket(
        session=db,
        customer_id=customer.id,
        issue="noisy",
        parts=[],
        idempotency_key=key,
        actor_user_id=actor.id,
    )
    replay = crud.record_service_ticket(
        session=db,
        customer_id=customer.id,
        issue="noisy",
        parts=[],
        idempotency_key=key,
        actor_user_id=actor.id,
    )
    assert replay.id == first.id
    # Identity is pinned from the stored row, not rebuilt from the caller.
    assert replay.created_by_user_id == actor.id
