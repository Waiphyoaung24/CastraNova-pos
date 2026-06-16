import re
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
    superuser_token_headers: dict[str, str],
    db: Session,
    seed_product_supplier: tuple[uuid.UUID, uuid.UUID],
) -> None:
    product_id, supplier_id = seed_product_supplier
    r = client.post(
        f"{PREFIX}/receipts/serialized",
        headers=superuser_token_headers,
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
    superuser_token_headers: dict[str, str],
    db: Session,
    seed_product_supplier: tuple[uuid.UUID, uuid.UUID],
) -> None:
    product_id, supplier_id = seed_product_supplier
    body = _body(product_id, supplier_id)
    r1 = client.post(
        f"{PREFIX}/receipts/serialized", headers=superuser_token_headers, json=body
    )
    assert r1.status_code == 200
    db.expire_all()
    units_before = len(db.exec(select(Unit)).all())
    movements_before = len(db.exec(select(UnitMovement)).all())

    r2 = client.post(
        f"{PREFIX}/receipts/serialized", headers=superuser_token_headers, json=body
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


def test_receive_rejects_negative_cost(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    seed_product_supplier: tuple[uuid.UUID, uuid.UUID],
) -> None:
    product_id, supplier_id = seed_product_supplier
    body = _body(product_id, supplier_id)
    body["pieces"] = [{"supplier_serial": "SN-NEG", "purchase_cost_thb": "-1.00"}]
    r = client.post(
        f"{PREFIX}/receipts/serialized", headers=superuser_token_headers, json=body
    )
    assert r.status_code == 422


def test_label_pdf_returned_for_unit(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    seed_product_supplier: tuple[uuid.UUID, uuid.UUID],
) -> None:
    product_id, supplier_id = seed_product_supplier
    rec = client.post(
        f"{PREFIX}/receipts/serialized",
        headers=superuser_token_headers,
        json=_body(product_id, supplier_id),
    )
    unit_id = rec.json()["units"][0]["id"]
    r = client.get(
        f"{PREFIX}/receipts/serialized/{unit_id}/label.pdf",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"


def test_staff_cannot_receive_serialized(
    client: TestClient,
    staff_token_headers: dict[str, str],
    seed_product_supplier: tuple[uuid.UUID, uuid.UUID],
) -> None:
    """Receiving is admin-only (reverses FR-005/006 D3); staff are forbidden."""
    product_id, supplier_id = seed_product_supplier
    resp = client.post(
        f"{PREFIX}/receipts/serialized",
        headers=staff_token_headers,
        json=_body(product_id, supplier_id),
    )
    assert resp.status_code == 403, resp.text


def test_staff_can_fetch_unit_label(
    client: TestClient,
    staff_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
    seed_product_supplier: tuple[uuid.UUID, uuid.UUID],
) -> None:
    product_id, supplier_id = seed_product_supplier
    # Receiving is admin-only now, so seed the unit as an admin; the label
    # endpoint itself stays shared-team, which is what this test asserts.
    recv = client.post(
        f"{PREFIX}/receipts/serialized",
        headers=superuser_token_headers,
        json=_body(product_id, supplier_id),
    )
    assert recv.status_code == 200, recv.text
    unit_id = recv.json()["units"][0]["id"]
    resp = client.get(
        f"{PREFIX}/receipts/serialized/{unit_id}/label.pdf",
        headers=staff_token_headers,
    )
    assert resp.status_code == 200
    assert resp.content[:4] == b"%PDF"


def test_unauthenticated_cannot_receive_serialized(client: TestClient) -> None:
    resp = client.post(f"{PREFIX}/receipts/serialized", json={})
    assert resp.status_code == 401


def test_unauthenticated_cannot_fetch_unit_label(client: TestClient) -> None:
    unit_id = uuid.uuid4()
    resp = client.get(f"{PREFIX}/receipts/serialized/{unit_id}/label.pdf")
    assert resp.status_code == 401


def _page_count(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page(?!s)", pdf))


def test_unit_label_qty_emits_multiple_pages(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    seed_product_supplier: tuple[uuid.UUID, uuid.UUID],
) -> None:
    product_id, supplier_id = seed_product_supplier
    rec = client.post(
        f"{PREFIX}/receipts/serialized",
        headers=superuser_token_headers,
        json=_body(product_id, supplier_id),
    )
    unit_id = rec.json()["units"][0]["id"]

    r3 = client.get(
        f"{PREFIX}/receipts/serialized/{unit_id}/label.pdf?qty=3",
        headers=superuser_token_headers,
    )
    assert r3.status_code == 200
    assert _page_count(r3.content) == 3

    r1 = client.get(
        f"{PREFIX}/receipts/serialized/{unit_id}/label.pdf",
        headers=superuser_token_headers,
    )
    assert r1.status_code == 200
    assert _page_count(r1.content) == 1
