import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    CostLine,
    CustomerCreate,
    Location,
    MovementType,
    OverrideTargetKind,
    PartMovement,
    PricingOverrideCreate,
    ProductCreate,
    ServiceTicket,
    SupplierCreate,
    TrackingMode,
)

PREFIX = settings.API_V1_STR


def _approved_ticket_override(
    db: Session, product_id: uuid.UUID, requested: str
) -> uuid.UUID:
    """Create + approve a SERVICE_TICKET_PART override, returning its id."""
    crud.set_setting(session=db, key=crud.OVERRIDE_THRESHOLD_KEY, value=5.0)
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    ovr = crud.create_pricing_override(
        session=db,
        override_in=PricingOverrideCreate(
            target_kind=OverrideTargetKind.SERVICE_TICKET_PART,
            product_id=product_id,
            requested_price_thb=Decimal(requested),
            reason="goodwill",
        ),
        created_by_user_id=user.id,
    )
    crud.decide_pricing_override(
        session=db, override_id=ovr.id, decision="APPROVED", decided_by_user_id=user.id
    )
    return ovr.id


@pytest.fixture
def seed_ticket_ctx(db: Session) -> Iterator[tuple[uuid.UUID, str, uuid.UUID]]:
    """A customer + a QUANTITY product (repair 20) stocked 3 @ 10.00 then
    4 @ 12.00. Yields (customer_id, sku, product_id)."""
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Repair Cust")
    )
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"SVC-{uuid.uuid4().hex[:8]}",
            model_name="Bearing",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="100.00",
            repair_price_thb="20.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name="Acme Parts")
    )
    for qty, cost in ((3, "10.00"), (4, "12.00")):
        crud.receive_quantity(
            session=db,
            product_id=product.id,
            supplier_id=supplier.id,
            received_qty=qty,
            purchase_cost_thb=Decimal(cost),
            idempotency_key=uuid.uuid4(),
            received_by_user_id=user.id,
        )
    yield customer.id, product.sku, product.id


def _record_body(
    customer_id: uuid.UUID,
    *,
    parts: list[dict[str, Any]] | None = None,
    **over: object,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "customer_id": str(customer_id),
        "issue": "Compressor noisy",
        "idempotency_key": str(uuid.uuid4()),
        "parts": parts if parts is not None else [],
    }
    body.update(over)
    return body


def _record(
    client: TestClient,
    headers: dict[str, str],
    customer_id: uuid.UUID,
    *,
    parts: list[dict[str, Any]] | None = None,
    **over: object,
) -> Any:
    return client.post(
        f"{PREFIX}/service-tickets/record",
        headers=headers,
        json=_record_body(customer_id, parts=parts, **over),
    )


def _maint_movements(db: Session, product_id: uuid.UUID) -> list[PartMovement]:
    return list(
        db.exec(
            select(PartMovement).where(
                PartMovement.product_id == product_id,
                PartMovement.event_type == MovementType.MAINTENANCE_OUT,
            )
        ).all()
    )


def test_record_creates_closed_ticket(
    client: TestClient,
    staff_token_headers: dict[str, str],
    seed_ticket_ctx: tuple[uuid.UUID, str, uuid.UUID],
) -> None:
    customer_id, _, _ = seed_ticket_ctx
    r = _record(
        client, staff_token_headers, customer_id, resolution="Replaced bearings"
    )
    assert r.status_code == 200, r.text
    ticket = r.json()
    # Recorded == closed: there is no persistent open state.
    assert ticket["closed_at"] is not None
    assert ticket["opened_at"]
    assert ticket["issue"] == "Compressor noisy"
    assert ticket["resolution"] == "Replaced bearings"
    assert ticket["parts"] == []


def test_record_part_defaults_to_repair_price(
    client: TestClient,
    staff_token_headers: dict[str, str],
    seed_ticket_ctx: tuple[uuid.UUID, str, uuid.UUID],
) -> None:
    customer_id, sku, product_id = seed_ticket_ctx
    r = _record(
        client,
        staff_token_headers,
        customer_id,
        parts=[{"sku": sku, "quantity": 2}],
    )
    assert r.status_code == 200, r.text
    part = r.json()["parts"][0]
    assert part["product_id"] == str(product_id)
    assert part["quantity"] == 2
    assert part["unit_price_thb"] == "20.00"  # product.repair_price_thb


def test_record_unknown_sku_404_creates_nothing(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
    seed_ticket_ctx: tuple[uuid.UUID, str, uuid.UUID],
) -> None:
    customer_id, _, _ = seed_ticket_ctx
    before = len(db.exec(select(ServiceTicket)).all())
    r = _record(
        client,
        staff_token_headers,
        customer_id,
        parts=[{"sku": "NOPE", "quantity": 1}],
    )
    assert r.status_code == 404
    db.expire_all()
    assert len(db.exec(select(ServiceTicket)).all()) == before  # no orphan ticket


def test_record_runs_fifo_and_closes(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
    seed_ticket_ctx: tuple[uuid.UUID, str, uuid.UUID],
) -> None:
    customer_id, sku, product_id = seed_ticket_ctx
    r = _record(
        client,
        staff_token_headers,
        customer_id,
        parts=[{"sku": sku, "quantity": 5}],  # 3@10 + 2@12
        resolution="Replaced bearings",
    )
    assert r.status_code == 200, r.text
    closed = r.json()
    assert closed["closed_at"] is not None
    tid = closed["id"]

    db.expire_all()
    movements = _maint_movements(db, product_id)
    assert len(movements) == 1
    assert movements[0].quantity == 5
    assert movements[0].service_ticket_id == uuid.UUID(tid)
    cost_lines = db.exec(
        select(CostLine).where(CostLine.part_movement_id == movements[0].id)
    ).all()
    assert sum(c.quantity for c in cost_lines) == 5
    assert sum(c.total_cost_thb for c in cost_lines) == Decimal("54.00")


def test_record_idempotent_replay_consumes_once(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
    seed_ticket_ctx: tuple[uuid.UUID, str, uuid.UUID],
) -> None:
    # The whole-ticket idempotency_key makes a replay return the same ticket and
    # consume stock exactly once — the regression the old 3-call flow could not
    # guarantee (add-part was not idempotent -> duplicate part lines).
    customer_id, sku, product_id = seed_ticket_ctx
    body = _record_body(customer_id, parts=[{"sku": sku, "quantity": 2}])
    r1 = client.post(
        f"{PREFIX}/service-tickets/record", headers=staff_token_headers, json=body
    )
    r2 = client.post(
        f"{PREFIX}/service-tickets/record", headers=staff_token_headers, json=body
    )
    assert r1.status_code == 200 and r2.status_code == 200, r2.text
    assert r1.json()["id"] == r2.json()["id"]  # same ticket
    # exactly one part line, consumed exactly once
    assert len(r2.json()["parts"]) == 1
    db.expire_all()
    movements = _maint_movements(db, product_id)
    assert len(movements) == 1
    assert movements[0].quantity == 2


def test_record_insufficient_stock_409_creates_nothing(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
    seed_ticket_ctx: tuple[uuid.UUID, str, uuid.UUID],
) -> None:
    customer_id, sku, product_id = seed_ticket_ctx
    before = len(db.exec(select(ServiceTicket)).all())
    r = _record(
        client,
        staff_token_headers,
        customer_id,
        parts=[{"sku": sku, "quantity": 100}],  # only 7 in stock
    )
    assert r.status_code == 409
    db.expire_all()
    assert len(db.exec(select(ServiceTicket)).all()) == before  # nothing committed
    assert not _maint_movements(db, product_id)  # no consumption written


def test_record_part_with_approved_override_uses_price(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
    seed_ticket_ctx: tuple[uuid.UUID, str, uuid.UUID],
) -> None:
    # FR-010: a price other than repair_price (20.00) needs an approved override.
    customer_id, sku, product_id = seed_ticket_ctx
    override_id = _approved_ticket_override(db, product_id, "35.00")
    r = _record(
        client,
        staff_token_headers,
        customer_id,
        parts=[
            {
                "sku": sku,
                "quantity": 1,
                "pricing_override_request_id": str(override_id),
            }
        ],
    )
    assert r.status_code == 200, r.text
    assert r.json()["parts"][0]["unit_price_thb"] == "35.00"  # override, not 20.00


def test_record_part_with_pending_override_blocked(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
    seed_ticket_ctx: tuple[uuid.UUID, str, uuid.UUID],
) -> None:
    customer_id, sku, product_id = seed_ticket_ctx
    crud.set_setting(session=db, key=crud.OVERRIDE_THRESHOLD_KEY, value=5.0)
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    ovr = crud.create_pricing_override(  # 75% off repair -> PENDING
        session=db,
        override_in=PricingOverrideCreate(
            target_kind=OverrideTargetKind.SERVICE_TICKET_PART,
            product_id=product_id,
            requested_price_thb=Decimal("35.00"),
            reason="goodwill",
        ),
        created_by_user_id=user.id,
    )
    r = _record(
        client,
        staff_token_headers,
        customer_id,
        parts=[
            {"sku": sku, "quantity": 1, "pricing_override_request_id": str(ovr.id)}
        ],
    )
    assert r.status_code == 400, r.text


def test_record_no_parts_succeeds(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
    seed_ticket_ctx: tuple[uuid.UUID, str, uuid.UUID],
) -> None:
    customer_id, _, product_id = seed_ticket_ctx
    r = _record(client, staff_token_headers, customer_id)
    assert r.status_code == 200, r.text
    assert r.json()["closed_at"] is not None
    db.expire_all()
    assert not _maint_movements(db, product_id)


def test_record_duplicate_sku_422(
    client: TestClient,
    staff_token_headers: dict[str, str],
    seed_ticket_ctx: tuple[uuid.UUID, str, uuid.UUID],
) -> None:
    # One line per SKU (the UI merges by SKU); two lines for the same SKU is a
    # client bug, rejected rather than double-consumed.
    customer_id, sku, _ = seed_ticket_ctx
    r = _record(
        client,
        staff_token_headers,
        customer_id,
        parts=[{"sku": sku, "quantity": 1}, {"sku": sku, "quantity": 2}],
    )
    assert r.status_code == 422, r.text


def test_record_requires_auth(
    client: TestClient,
    seed_ticket_ctx: tuple[uuid.UUID, str, uuid.UUID],
) -> None:
    customer_id, _, _ = seed_ticket_ctx
    r = client.post(
        f"{PREFIX}/service-tickets/record", json=_record_body(customer_id)
    )
    assert r.status_code == 401
