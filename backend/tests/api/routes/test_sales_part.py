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
    SupplierCreate,
    TrackingMode,
)

PREFIX = settings.API_V1_STR


@pytest.fixture
def seed_part_sale(db: Session) -> Iterator[tuple[str, uuid.UUID, uuid.UUID]]:
    """A QUANTITY product (retail 100) with two FIFO batches — 3 @ 10.00 then
    4 @ 12.00 — plus a customer. Yields (sku, customer_id, product_id)."""
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"PART-{uuid.uuid4().hex[:8]}",
            model_name="Bearing",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="100.00",
            repair_price_thb="20.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name="Acme Parts")
    )
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Walk-in")
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
    yield product.sku, customer.id, product.id


def _part_body(sku: str, customer_id: uuid.UUID, qty: int, **over: object) -> dict:
    body: dict = {
        "customer_id": str(customer_id),
        "lines": [{"line_kind": "PART", "sku": sku, "quantity": qty}],
        "idempotency_key": str(uuid.uuid4()),
    }
    body.update(over)
    return body


def test_part_sale_fifo_spans_two_batches(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    seed_part_sale: tuple[str, uuid.UUID, uuid.UUID],
) -> None:
    sku, customer_id, product_id = seed_part_sale
    r = client.post(
        f"{PREFIX}/sales",
        headers=superuser_token_headers,
        json=_part_body(sku, customer_id, 5),
    )
    assert r.status_code == 200, r.text
    sale = r.json()
    # 3@10 + 2@12 = 54 COGS; 5 @ retail 100 = 500 revenue; snapshot 54/5 = 10.80.
    assert sale["total_thb"] == "500.00"
    assert sale["total_cogs_thb"] == "54.00"
    assert len(sale["lines"]) == 1
    line = sale["lines"][0]
    assert line["line_kind"] == "PART"
    assert line["product_id"] == str(product_id)
    assert line["quantity"] == 5
    assert line["unit_price_thb"] == "100.00"
    assert line["unit_cost_thb"] == "10.80"

    # One SOLD part_movement (qty 5) + two cost_lines splitting across the batches.
    db.expire_all()
    movements = db.exec(
        select(PartMovement).where(
            PartMovement.product_id == product_id,
            PartMovement.event_type == MovementType.SOLD,
        )
    ).all()
    assert len(movements) == 1
    assert movements[0].quantity == 5
    cost_lines = db.exec(
        select(CostLine).where(CostLine.part_movement_id == movements[0].id)
    ).all()
    assert len(cost_lines) == 2
    assert sum(c.quantity for c in cost_lines) == 5
    assert sum(c.total_cost_thb for c in cost_lines) == Decimal("54.00")


def test_part_sale_idempotent_replay(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
    seed_part_sale: tuple[str, uuid.UUID, uuid.UUID],
) -> None:
    sku, customer_id, product_id = seed_part_sale
    body = _part_body(sku, customer_id, 5)
    r1 = client.post(f"{PREFIX}/sales", headers=staff_token_headers, json=body)
    assert r1.status_code == 200, r1.text
    db.expire_all()
    movements_before = len(
        db.exec(select(PartMovement).where(PartMovement.product_id == product_id)).all()
    )
    cost_lines_before = len(db.exec(select(CostLine)).all())

    r2 = client.post(f"{PREFIX}/sales", headers=staff_token_headers, json=body)
    assert r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]
    db.expire_all()
    assert (
        len(db.exec(select(PartMovement).where(PartMovement.product_id == product_id)).all())
        == movements_before
    )
    assert len(db.exec(select(CostLine)).all()) == cost_lines_before


def test_part_sale_insufficient_stock_409(
    client: TestClient,
    staff_token_headers: dict[str, str],
    seed_part_sale: tuple[str, uuid.UUID, uuid.UUID],
) -> None:
    sku, customer_id, _ = seed_part_sale
    r = client.post(
        f"{PREFIX}/sales",
        headers=staff_token_headers,
        json=_part_body(sku, customer_id, 100),  # only 7 in stock
    )
    assert r.status_code == 409
    assert "7" in r.json()["detail"]


def test_part_sale_unknown_sku_404(
    client: TestClient,
    staff_token_headers: dict[str, str],
    seed_part_sale: tuple[str, uuid.UUID, uuid.UUID],
) -> None:
    _, customer_id, _ = seed_part_sale
    r = client.post(
        f"{PREFIX}/sales",
        headers=staff_token_headers,
        json=_part_body("NO-SUCH-SKU", customer_id, 1),
    )
    assert r.status_code == 404
    assert "Product" in r.json()["detail"]


def test_part_sale_rejects_duplicate_sku_lines(
    client: TestClient,
    staff_token_headers: dict[str, str],
    seed_part_sale: tuple[str, uuid.UUID, uuid.UUID],
) -> None:
    sku, customer_id, _ = seed_part_sale
    body = {
        "customer_id": str(customer_id),
        "lines": [
            {"line_kind": "PART", "sku": sku, "quantity": 2},
            {"line_kind": "PART", "sku": sku, "quantity": 3},
        ],
        "idempotency_key": str(uuid.uuid4()),
    }
    r = client.post(f"{PREFIX}/sales", headers=staff_token_headers, json=body)
    assert r.status_code == 422
    assert sku in r.json()["detail"]


def test_mixed_unit_and_part_sale(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    seed_part_sale: tuple[str, uuid.UUID, uuid.UUID],
) -> None:
    # A serialized UNIT (retail 1000, cost 600) sold alongside a PART line in one
    # sale. Totals must accumulate across both code paths.
    from app.models import ReceivePiece

    sku, customer_id, _ = seed_part_sale
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    ser_product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"SER-{uuid.uuid4().hex[:8]}",
            model_name="Compressor",
            tracking_mode=TrackingMode.SERIALIZED,
            retail_price_thb="1000.00",
            repair_price_thb="200.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name="Acme Serial")
    )
    units = crud.receive_serialized(
        session=db,
        product_id=ser_product.id,
        supplier_id=supplier.id,
        pieces=[ReceivePiece(supplier_serial="SN-MIX", purchase_cost_thb="600.00")],
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user.id,
    )
    barcode = units[0].castranova_barcode

    body = {
        "customer_id": str(customer_id),
        "lines": [
            {"line_kind": "UNIT", "castranova_barcode": barcode},
            {"line_kind": "PART", "sku": sku, "quantity": 2},  # 2 @ 10.00 = 20 cogs
        ],
        "idempotency_key": str(uuid.uuid4()),
    }
    r = client.post(f"{PREFIX}/sales", headers=superuser_token_headers, json=body)
    assert r.status_code == 200, r.text
    sale = r.json()
    # Revenue: 1000 (unit) + 2*100 (part) = 1200; COGS: 600 + 2*10 = 620.
    assert sale["total_thb"] == "1200.00"
    assert sale["total_cogs_thb"] == "620.00"
    assert len(sale["lines"]) == 2
