import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    Location,
    ProductCreate,
    SupplierCreate,
    TrackingMode,
    Unit,
    UnitMovement,
)

PREFIX = settings.API_V1_STR


@pytest.fixture
def seed_product_supplier(db: Session) -> Iterator[tuple[uuid.UUID, uuid.UUID]]:
    """A SERIALIZED product + supplier + the YGN_WH location to receive into."""
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    product = crud.create_product(
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
        session=db, supplier_in=SupplierCreate(name="Acme", country="TH")
    )
    yield product.id, supplier.id


def _body(product_id: uuid.UUID, supplier_id: uuid.UUID, **over: object) -> dict:
    body: dict = {
        "product_id": str(product_id),
        "supplier_id": str(supplier_id),
        "pieces": [{"supplier_serial": "SN-1", "purchase_cost_thb": "900.00"}],
        "idempotency_key": str(uuid.uuid4()),
    }
    body.update(over)
    return body


def test_receive_serialized_creates_unit_and_movement(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
    seed_product_supplier: tuple[uuid.UUID, uuid.UUID],
) -> None:
    product_id, supplier_id = seed_product_supplier
    r = client.post(
        f"{PREFIX}/receipts/serialized",
        headers=staff_token_headers,
        json=_body(product_id, supplier_id),
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["units"]) == 1
    unit = body["units"][0]
    assert unit["current_state"] == "IN_STOCK"
    assert unit["castranova_barcode"]  # generated
    assert unit["supplier_serial"] == "SN-1"

    # An append-only RECEIVED movement was written for this unit.
    db.expire_all()
    movements = db.exec(
        select(UnitMovement).where(UnitMovement.unit_id == uuid.UUID(unit["id"]))
    ).all()
    assert len(movements) == 1
    assert movements[0].event_type.value == "RECEIVED"


def test_receive_serialized_idempotent_replay(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
    seed_product_supplier: tuple[uuid.UUID, uuid.UUID],
) -> None:
    product_id, supplier_id = seed_product_supplier
    body = _body(product_id, supplier_id)
    r1 = client.post(
        f"{PREFIX}/receipts/serialized", headers=staff_token_headers, json=body
    )
    assert r1.status_code == 200
    db.expire_all()
    units_before = len(db.exec(select(Unit)).all())
    movements_before = len(db.exec(select(UnitMovement)).all())

    r2 = client.post(
        f"{PREFIX}/receipts/serialized", headers=staff_token_headers, json=body
    )
    assert r2.status_code == 200
    # Replay returns the same unit and persists no new unit/movement rows.
    assert r1.json()["units"][0]["id"] == r2.json()["units"][0]["id"]
    db.expire_all()
    assert len(db.exec(select(Unit)).all()) == units_before
    assert len(db.exec(select(UnitMovement)).all()) == movements_before


def test_receive_serialized_requires_auth(
    client: TestClient,
    seed_product_supplier: tuple[uuid.UUID, uuid.UUID],
) -> None:
    product_id, supplier_id = seed_product_supplier
    r = client.post(
        f"{PREFIX}/receipts/serialized", json=_body(product_id, supplier_id)
    )
    assert r.status_code == 401


def test_label_pdf_returned_for_unit(
    client: TestClient,
    staff_token_headers: dict[str, str],
    seed_product_supplier: tuple[uuid.UUID, uuid.UUID],
) -> None:
    product_id, supplier_id = seed_product_supplier
    rec = client.post(
        f"{PREFIX}/receipts/serialized",
        headers=staff_token_headers,
        json=_body(product_id, supplier_id),
    )
    unit_id = rec.json()["units"][0]["id"]
    r = client.get(
        f"{PREFIX}/receipts/serialized/{unit_id}/label.pdf",
        headers=staff_token_headers,
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"
