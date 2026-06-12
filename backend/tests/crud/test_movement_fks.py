"""M025 FK smoke tests: unit_movement/part_movement.service_ticket_id must
reference a real serviceticket row (system design §10 M015/M016). Rows
inserted here are append-only and cannot be cleaned up; the session-end
TRUNCATE handles them."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    CustomerCreate,
    Location,
    MovementType,
    PartMovement,
    ProductCreate,
    ReceivePiece,
    ServiceTicket,
    SupplierCreate,
    TrackingMode,
    UnitMovement,
)


@pytest.fixture
def fk_prereqs(db: Session) -> dict[str, uuid.UUID]:
    """A real user, product, unit, and open service ticket (mirrors
    test_append_only's seeding style)."""
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name="MovementFk Co")
    )
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="MovementFk Cust")
    )
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"FK-{uuid.uuid4().hex[:8]}",
            model_name="Widget",
            tracking_mode=TrackingMode.SERIALIZED,
            retail_price_thb="100.00",
            repair_price_thb="20.00",
        ),
    )
    units = crud.receive_serialized(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        pieces=[
            ReceivePiece(
                supplier_serial=f"SN-{uuid.uuid4().hex[:8]}",
                purchase_cost_thb=Decimal("50.00"),
            )
        ],
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user.id,
    )
    unit = units[0]
    ticket = crud.open_service_ticket(
        session=db,
        customer_id=customer.id,
        issue="FK smoke",
        idempotency_key=uuid.uuid4(),
        created_by_user_id=user.id,
    )
    return {
        "user_id": user.id,
        "product_id": product.id,
        "unit_id": unit.id,
        "ticket_id": ticket.id,
    }


def test_partmovement_dangling_service_ticket_rejected(
    db: Session, fk_prereqs: dict[str, uuid.UUID]
) -> None:
    db.add(
        PartMovement(
            product_id=fk_prereqs["product_id"],
            event_type=MovementType.MAINTENANCE_OUT,
            quantity=1,
            service_ticket_id=uuid.uuid4(),  # nonexistent ticket
            actor_user_id=fk_prereqs["user_id"],
            idempotency_key=uuid.uuid4(),
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_unitmovement_dangling_service_ticket_rejected(
    db: Session, fk_prereqs: dict[str, uuid.UUID]
) -> None:
    db.add(
        UnitMovement(
            unit_id=fk_prereqs["unit_id"],
            event_type=MovementType.MAINTENANCE_OUT,
            service_ticket_id=uuid.uuid4(),  # nonexistent ticket
            actor_user_id=fk_prereqs["user_id"],
            idempotency_key=uuid.uuid4(),
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_movements_with_real_service_ticket_accepted(
    db: Session, fk_prereqs: dict[str, uuid.UUID]
) -> None:
    assert db.get(ServiceTicket, fk_prereqs["ticket_id"]) is not None
    pm = PartMovement(
        product_id=fk_prereqs["product_id"],
        event_type=MovementType.MAINTENANCE_OUT,
        quantity=1,
        service_ticket_id=fk_prereqs["ticket_id"],
        actor_user_id=fk_prereqs["user_id"],
        idempotency_key=uuid.uuid4(),
    )
    um = UnitMovement(
        unit_id=fk_prereqs["unit_id"],
        event_type=MovementType.MAINTENANCE_OUT,
        service_ticket_id=fk_prereqs["ticket_id"],
        actor_user_id=fk_prereqs["user_id"],
        idempotency_key=uuid.uuid4(),
    )
    db.add(pm)
    db.add(um)
    db.commit()
    db.refresh(pm)
    db.refresh(um)
    assert pm.service_ticket_id == fk_prereqs["ticket_id"]
    assert um.service_ticket_id == fk_prereqs["ticket_id"]
