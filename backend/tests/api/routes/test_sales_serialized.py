import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    CustomerCreate,
    Location,
    ProductCreate,
    ReceivePiece,
    SupplierCreate,
    TrackingMode,
    Unit,
    UnitState,
)

PREFIX = settings.API_V1_STR


@pytest.fixture
def seed_sale_unit(
    db: Session,
) -> Iterator[tuple[str, uuid.UUID]]:
    """Receive one IN_STOCK serialized unit (retail 1000) + a customer.

    Yields (castranova_barcode, customer_id)."""
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"SALE-{uuid.uuid4().hex[:8]}",
            model_name="Compressor",
            tracking_mode=TrackingMode.SERIALIZED,
            retail_price_thb="1000.00",
            repair_price_thb="200.00",
        ),
    )
    supplier = crud.create_supplier(session=db, supplier_in=SupplierCreate(name="Acme"))
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Walk-in")
    )
    units = crud.receive_serialized(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        pieces=[
            ReceivePiece(
                supplier_serial=f"SN-{uuid.uuid4().hex[:6]}",
                purchase_cost_thb="600.00",
            )
        ],
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user.id,
    )
    yield units[0].castranova_barcode, customer.id


def _sale_body(barcode: str, customer_id: uuid.UUID, **over: object) -> dict:
    body: dict = {
        "customer_id": str(customer_id),
        "lines": [{"line_kind": "UNIT", "castranova_barcode": barcode}],
        "idempotency_key": str(uuid.uuid4()),
    }
    body.update(over)
    return body


def test_sale_of_serialized_unit_happy_path(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    seed_sale_unit: tuple[str, uuid.UUID],
) -> None:
    barcode, customer_id = seed_sale_unit
    r = client.post(
        f"{PREFIX}/sales",
        headers=superuser_token_headers,
        json=_sale_body(barcode, customer_id),
    )
    assert r.status_code == 200, r.text
    sale = r.json()
    assert sale["total_thb"] == "1000.00"
    assert sale["total_cogs_thb"] == "600.00"
    assert len(sale["lines"]) == 1
    line = sale["lines"][0]
    assert line["line_kind"] == "UNIT"
    assert line["unit_price_thb"] == "1000.00"
    assert line["unit_cost_thb"] == "600.00"

    # Unit transitioned to SOLD.
    db.expire_all()
    unit = db.exec(
        select(Unit).where(Unit.castranova_barcode == barcode)
    ).one()
    assert unit.current_state == UnitState.SOLD


def test_sale_requires_customer(
    client: TestClient,
    staff_token_headers: dict[str, str],
    seed_sale_unit: tuple[str, uuid.UUID],
) -> None:
    barcode, _ = seed_sale_unit
    body = {
        "lines": [{"line_kind": "UNIT", "castranova_barcode": barcode}],
        "idempotency_key": str(uuid.uuid4()),
    }
    r = client.post(f"{PREFIX}/sales", headers=staff_token_headers, json=body)
    assert r.status_code == 422


def test_sale_already_sold_conflicts(
    client: TestClient,
    staff_token_headers: dict[str, str],
    seed_sale_unit: tuple[str, uuid.UUID],
) -> None:
    barcode, customer_id = seed_sale_unit
    first = client.post(
        f"{PREFIX}/sales",
        headers=staff_token_headers,
        json=_sale_body(barcode, customer_id),
    )
    assert first.status_code == 200
    # New idempotency key, same already-sold unit -> 409 with current state.
    second = client.post(
        f"{PREFIX}/sales",
        headers=staff_token_headers,
        json=_sale_body(barcode, customer_id),
    )
    assert second.status_code == 409
    assert "SOLD" in second.json()["detail"]


def test_sale_idempotent_replay(
    client: TestClient,
    staff_token_headers: dict[str, str],
    seed_sale_unit: tuple[str, uuid.UUID],
) -> None:
    barcode, customer_id = seed_sale_unit
    body = _sale_body(barcode, customer_id)
    r1 = client.post(f"{PREFIX}/sales", headers=staff_token_headers, json=body)
    assert r1.status_code == 200
    r2 = client.post(f"{PREFIX}/sales", headers=staff_token_headers, json=body)
    assert r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]


def test_sale_receipt_pdf(
    client: TestClient,
    staff_token_headers: dict[str, str],
    seed_sale_unit: tuple[str, uuid.UUID],
) -> None:
    barcode, customer_id = seed_sale_unit
    sale = client.post(
        f"{PREFIX}/sales",
        headers=staff_token_headers,
        json=_sale_body(barcode, customer_id),
    )
    sale_id = sale.json()["id"]
    r = client.get(
        f"{PREFIX}/sales/{sale_id}/receipt.pdf", headers=staff_token_headers
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"


def test_sale_part_line_unknown_sku_404(
    client: TestClient,
    staff_token_headers: dict[str, str],
    seed_sale_unit: tuple[str, uuid.UUID],
) -> None:
    # PART lines are enabled (Task 2.4); an unknown SKU now resolves to 404
    # rather than the old "not enabled" 400. Happy-path FIFO is in test_sales_part.
    _, customer_id = seed_sale_unit
    body = {
        "customer_id": str(customer_id),
        "lines": [{"line_kind": "PART", "sku": "SOME-SKU", "quantity": 2}],
        "idempotency_key": str(uuid.uuid4()),
    }
    r = client.post(f"{PREFIX}/sales", headers=staff_token_headers, json=body)
    assert r.status_code == 404
    assert "Product" in r.json()["detail"]


def test_get_sale_receipt_data_resolves_names_and_labels(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    seed_sale_unit: tuple[str, uuid.UUID],
) -> None:
    barcode, customer_id = seed_sale_unit
    created = client.post(
        f"{PREFIX}/sales",
        headers=superuser_token_headers,
        json=_sale_body(barcode, customer_id),
    )
    assert created.status_code == 200, created.text
    sale_id = created.json()["id"]

    data = crud.get_sale_receipt_data(session=db, sale_id=uuid.UUID(sale_id))
    assert data is not None
    assert data.customer_name == "Walk-in"
    assert "@" in data.sold_by or data.sold_by  # full name or email, never empty
    assert len(data.lines) == 1
    label, qty, price = data.lines[0]
    assert "Compressor" in label  # not the raw "UNIT" placeholder
    assert "UNIT" != label
    assert qty == 1


def test_get_sale_receipt_data_unknown_sale_returns_none(db: Session) -> None:
    assert crud.get_sale_receipt_data(session=db, sale_id=uuid.uuid4()) is None
