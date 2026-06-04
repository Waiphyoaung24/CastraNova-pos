import uuid
from collections.abc import Iterator
from decimal import Decimal

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
    PartMovement,
    ProductCreate,
    ServiceTicket,
    SupplierCreate,
    TrackingMode,
)

PREFIX = settings.API_V1_STR


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


def _open_body(customer_id: uuid.UUID, **over: object) -> dict:
    body: dict = {
        "customer_id": str(customer_id),
        "issue": "Compressor noisy",
        "idempotency_key": str(uuid.uuid4()),
    }
    body.update(over)
    return body


def _open(
    client: TestClient, headers: dict[str, str], customer_id: uuid.UUID, **over: object
) -> dict:
    r = client.post(
        f"{PREFIX}/service-tickets", headers=headers, json=_open_body(customer_id, **over)
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_open_ticket_creates_open_ticket(
    client: TestClient,
    staff_token_headers: dict[str, str],
    seed_ticket_ctx: tuple[uuid.UUID, str, uuid.UUID],
) -> None:
    customer_id, _, _ = seed_ticket_ctx
    ticket = _open(client, staff_token_headers, customer_id)
    assert ticket["closed_at"] is None
    assert ticket["opened_at"]
    assert ticket["issue"] == "Compressor noisy"


def test_open_ticket_idempotent_replay(
    client: TestClient,
    staff_token_headers: dict[str, str],
    seed_ticket_ctx: tuple[uuid.UUID, str, uuid.UUID],
) -> None:
    customer_id, _, _ = seed_ticket_ctx
    body = _open_body(customer_id)
    r1 = client.post(f"{PREFIX}/service-tickets", headers=staff_token_headers, json=body)
    r2 = client.post(f"{PREFIX}/service-tickets", headers=staff_token_headers, json=body)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]


def test_add_part_defaults_to_repair_price(
    client: TestClient,
    staff_token_headers: dict[str, str],
    seed_ticket_ctx: tuple[uuid.UUID, str, uuid.UUID],
) -> None:
    customer_id, sku, product_id = seed_ticket_ctx
    ticket = _open(client, staff_token_headers, customer_id)
    r = client.post(
        f"{PREFIX}/service-tickets/{ticket['id']}/parts",
        headers=staff_token_headers,
        json={"sku": sku, "quantity": 2},
    )
    assert r.status_code == 200, r.text
    part = r.json()
    assert part["product_id"] == str(product_id)
    assert part["quantity"] == 2
    assert part["unit_price_thb"] == "20.00"  # product.repair_price_thb


def test_add_part_unknown_sku_404(
    client: TestClient,
    staff_token_headers: dict[str, str],
    seed_ticket_ctx: tuple[uuid.UUID, str, uuid.UUID],
) -> None:
    customer_id, _, _ = seed_ticket_ctx
    ticket = _open(client, staff_token_headers, customer_id)
    r = client.post(
        f"{PREFIX}/service-tickets/{ticket['id']}/parts",
        headers=staff_token_headers,
        json={"sku": "NOPE", "quantity": 1},
    )
    assert r.status_code == 404


def test_close_runs_fifo_and_sets_closed_at(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
    seed_ticket_ctx: tuple[uuid.UUID, str, uuid.UUID],
) -> None:
    customer_id, sku, product_id = seed_ticket_ctx
    ticket = _open(client, staff_token_headers, customer_id)
    tid = ticket["id"]
    client.post(
        f"{PREFIX}/service-tickets/{tid}/parts",
        headers=staff_token_headers,
        json={"sku": sku, "quantity": 5},  # 3@10 + 2@12
    )
    r = client.post(
        f"{PREFIX}/service-tickets/{tid}/close",
        headers=staff_token_headers,
        json={"resolution": "Replaced bearings"},
    )
    assert r.status_code == 200, r.text
    closed = r.json()
    assert closed["closed_at"] is not None
    assert closed["resolution"] == "Replaced bearings"

    db.expire_all()
    movements = db.exec(
        select(PartMovement).where(
            PartMovement.product_id == product_id,
            PartMovement.event_type == MovementType.MAINTENANCE_OUT,
        )
    ).all()
    assert len(movements) == 1
    assert movements[0].quantity == 5
    assert movements[0].service_ticket_id == uuid.UUID(tid)
    cost_lines = db.exec(
        select(CostLine).where(CostLine.part_movement_id == movements[0].id)
    ).all()
    assert sum(c.quantity for c in cost_lines) == 5
    assert sum(c.total_cost_thb for c in cost_lines) == Decimal("54.00")


def test_add_part_to_closed_ticket_rejected(
    client: TestClient,
    staff_token_headers: dict[str, str],
    seed_ticket_ctx: tuple[uuid.UUID, str, uuid.UUID],
) -> None:
    customer_id, sku, _ = seed_ticket_ctx
    ticket = _open(client, staff_token_headers, customer_id)
    tid = ticket["id"]
    client.post(
        f"{PREFIX}/service-tickets/{tid}/parts",
        headers=staff_token_headers,
        json={"sku": sku, "quantity": 1},
    )
    client.post(f"{PREFIX}/service-tickets/{tid}/close", headers=staff_token_headers, json={})
    r = client.post(
        f"{PREFIX}/service-tickets/{tid}/parts",
        headers=staff_token_headers,
        json={"sku": sku, "quantity": 1},
    )
    assert r.status_code == 409


def test_close_insufficient_stock_409_keeps_ticket_open(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
    seed_ticket_ctx: tuple[uuid.UUID, str, uuid.UUID],
) -> None:
    customer_id, sku, product_id = seed_ticket_ctx
    ticket = _open(client, staff_token_headers, customer_id)
    tid = ticket["id"]
    client.post(
        f"{PREFIX}/service-tickets/{tid}/parts",
        headers=staff_token_headers,
        json={"sku": sku, "quantity": 100},  # only 7 in stock
    )
    r = client.post(f"{PREFIX}/service-tickets/{tid}/close", headers=staff_token_headers, json={})
    assert r.status_code == 409

    db.expire_all()
    ticket_row = db.get(ServiceTicket, uuid.UUID(tid))
    assert ticket_row is not None and ticket_row.closed_at is None  # not closed
    assert not db.exec(
        select(PartMovement).where(
            PartMovement.product_id == product_id,
            PartMovement.event_type == MovementType.MAINTENANCE_OUT,
        )
    ).all()  # no consumption written (the RECEIVED seed movements remain)


def test_add_part_price_override(
    client: TestClient,
    staff_token_headers: dict[str, str],
    seed_ticket_ctx: tuple[uuid.UUID, str, uuid.UUID],
) -> None:
    customer_id, sku, _ = seed_ticket_ctx
    ticket = _open(client, staff_token_headers, customer_id)
    r = client.post(
        f"{PREFIX}/service-tickets/{ticket['id']}/parts",
        headers=staff_token_headers,
        json={"sku": sku, "quantity": 1, "unit_price_thb": "35.00"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["unit_price_thb"] == "35.00"  # override, not repair_price 20.00


def test_close_ticket_with_no_parts_succeeds(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
    seed_ticket_ctx: tuple[uuid.UUID, str, uuid.UUID],
) -> None:
    customer_id, _, product_id = seed_ticket_ctx
    ticket = _open(client, staff_token_headers, customer_id)
    r = client.post(
        f"{PREFIX}/service-tickets/{ticket['id']}/close",
        headers=staff_token_headers,
        json={},
    )
    assert r.status_code == 200, r.text
    assert r.json()["closed_at"] is not None
    db.expire_all()
    assert not db.exec(
        select(PartMovement).where(
            PartMovement.product_id == product_id,
            PartMovement.event_type == MovementType.MAINTENANCE_OUT,
        )
    ).all()


def test_close_is_idempotent(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
    seed_ticket_ctx: tuple[uuid.UUID, str, uuid.UUID],
) -> None:
    customer_id, sku, _ = seed_ticket_ctx
    ticket = _open(client, staff_token_headers, customer_id)
    tid = ticket["id"]
    client.post(
        f"{PREFIX}/service-tickets/{tid}/parts",
        headers=staff_token_headers,
        json={"sku": sku, "quantity": 2},
    )
    client.post(f"{PREFIX}/service-tickets/{tid}/close", headers=staff_token_headers, json={})
    db.expire_all()
    cost_lines_before = len(db.exec(select(CostLine)).all())

    r2 = client.post(
        f"{PREFIX}/service-tickets/{tid}/close", headers=staff_token_headers, json={}
    )
    assert r2.status_code == 200  # idempotent, not a re-consume
    db.expire_all()
    assert len(db.exec(select(CostLine)).all()) == cost_lines_before
