import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import Location, ProductCreate, SupplierCreate, TrackingMode


def _ensure_locations(db: Session) -> None:
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)


def _new_product(db: Session, mode: TrackingMode) -> uuid.UUID:
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"PC-{uuid.uuid4().hex[:8]}",
            model_name="Bearing",
            tracking_mode=mode,
            retail_price_thb="50.00",
            repair_price_thb="10.00",
        ),
    )
    return product.id


def _new_supplier(db: Session) -> uuid.UUID:
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name="Acme Parts", country="TH")
    )
    return supplier.id


def _receive_quantity(
    client: TestClient,
    headers: dict[str, str],
    product_id: uuid.UUID,
    supplier_id: uuid.UUID,
    cost: str,
) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/receipts/quantity",
        headers=headers,
        json={
            "product_id": str(product_id),
            "supplier_id": str(supplier_id),
            "received_qty": 5,
            "purchase_cost_thb": cost,
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 200, r.text


def _receive_serialized(
    client: TestClient,
    headers: dict[str, str],
    product_id: uuid.UUID,
    supplier_id: uuid.UUID,
    cost: str,
) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/receipts/serialized",
        headers=headers,
        json={
            "product_id": str(product_id),
            "supplier_id": str(supplier_id),
            "pieces": [
                {"supplier_serial": f"SN-{uuid.uuid4().hex[:10]}", "purchase_cost_thb": cost}
            ],
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 200, r.text


def _costs_by_product(client: TestClient, headers: dict[str, str]) -> dict[str, str]:
    r = client.get(
        f"{settings.API_V1_STR}/products/purchase-costs", headers=headers
    )
    assert r.status_code == 200, r.text
    return {row["product_id"]: row["latest_purchase_cost_thb"] for row in r.json()}


def test_purchase_costs_forbidden_for_staff(
    client: TestClient, staff_token_headers: dict[str, str]
) -> None:
    r = client.get(
        f"{settings.API_V1_STR}/products/purchase-costs",
        headers=staff_token_headers,
    )
    assert r.status_code == 403, r.text


def test_purchase_costs_latest_quantity_batch_wins(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _ensure_locations(db)
    product_id = _new_product(db, TrackingMode.QUANTITY)
    supplier_id = _new_supplier(db)
    _receive_quantity(client, superuser_token_headers, product_id, supplier_id, "5.00")
    _receive_quantity(client, superuser_token_headers, product_id, supplier_id, "7.00")
    costs = _costs_by_product(client, superuser_token_headers)
    assert Decimal(costs[str(product_id)]) == Decimal("7.00")


def test_purchase_costs_latest_serialized_unit_wins(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _ensure_locations(db)
    product_id = _new_product(db, TrackingMode.SERIALIZED)
    supplier_id = _new_supplier(db)
    _receive_serialized(client, superuser_token_headers, product_id, supplier_id, "900.00")
    _receive_serialized(client, superuser_token_headers, product_id, supplier_id, "1100.00")
    costs = _costs_by_product(client, superuser_token_headers)
    assert Decimal(costs[str(product_id)]) == Decimal("1100.00")


def test_purchase_costs_absent_without_receipts(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    product_id = _new_product(db, TrackingMode.QUANTITY)
    costs = _costs_by_product(client, superuser_token_headers)
    assert str(product_id) not in costs


def test_products_list_exposes_no_cost_to_staff(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    _new_product(db, TrackingMode.QUANTITY)
    r = client.get(f"{settings.API_V1_STR}/products/", headers=staff_token_headers)
    assert r.status_code == 200, r.text
    blob = str(r.json()).lower()
    assert "purchase_cost" not in blob
    assert "latest_purchase_cost_thb" not in blob
