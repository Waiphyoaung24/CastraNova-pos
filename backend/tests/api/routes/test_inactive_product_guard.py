"""Inactive products must be rejected at the API boundary, not just hidden
from the pickers. Regression tests for the sale-of-inactive-product hole found
in manual testing (typed SKU / scanned barcode bypassed the picker filter)."""

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
    CustomerCreate,
    Location,
    ProductCreate,
    ProjectCreate,
    ReceivePiece,
    SupplierCreate,
    TrackingMode,
)

PREFIX = settings.API_V1_STR


@pytest.fixture
def inactive_ctx(db: Session) -> Iterator[dict[str, Any]]:
    """A stocked QUANTITY product and a SERIALIZED product with one IN_STOCK
    unit — both then marked inactive — plus an active customer, supplier and
    project. Yields the ids/skus needed to hit every consumption endpoint."""
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Inactive Guard Cust")
    )
    project = crud.create_project(
        session=db,
        project_in=ProjectCreate(
            code=f"PRJ-{uuid.uuid4().hex[:8]}",
            name="Guard Site",
            customer_id=customer.id,
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name="Guard Supplier")
    )
    part = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"INACT-Q-{uuid.uuid4().hex[:8]}",
            model_name="Discontinued Bolt",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="10.00",
            repair_price_thb="2.00",
        ),
    )
    serialized = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"INACT-S-{uuid.uuid4().hex[:8]}",
            model_name="Discontinued Compressor",
            tracking_mode=TrackingMode.SERIALIZED,
            retail_price_thb="500.00",
            repair_price_thb="50.00",
        ),
    )
    crud.receive_quantity(
        session=db,
        product_id=part.id,
        supplier_id=supplier.id,
        received_qty=5,
        purchase_cost_thb=Decimal("4.00"),
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user.id,
    )
    units = crud.receive_serialized(
        session=db,
        product_id=serialized.id,
        supplier_id=supplier.id,
        pieces=[
            ReceivePiece(supplier_serial="SN-INACT", purchase_cost_thb="300.00")
        ],
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user.id,
    )
    for product in (part, serialized):
        product.is_active = False
        db.add(product)
    db.commit()
    yield {
        "customer_id": customer.id,
        "project_id": project.id,
        "supplier_id": supplier.id,
        "part_id": part.id,
        "part_sku": part.sku,
        "serialized_id": serialized.id,
        "barcode": units[0].castranova_barcode,
    }


def _assert_inactive_400(r: Any) -> None:
    assert r.status_code == 400, r.text
    assert "inactive" in r.json()["detail"].lower()


def test_sale_part_line_rejects_inactive_sku(
    client: TestClient,
    staff_token_headers: dict[str, str],
    inactive_ctx: dict[str, Any],
) -> None:
    r = client.post(
        f"{PREFIX}/sales",
        headers=staff_token_headers,
        json={
            "customer_id": str(inactive_ctx["customer_id"]),
            "lines": [
                {
                    "line_kind": "PART",
                    "sku": inactive_ctx["part_sku"],
                    "quantity": 1,
                }
            ],
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    _assert_inactive_400(r)


def test_sale_unit_line_rejects_inactive_products_unit(
    client: TestClient,
    staff_token_headers: dict[str, str],
    inactive_ctx: dict[str, Any],
) -> None:
    r = client.post(
        f"{PREFIX}/sales",
        headers=staff_token_headers,
        json={
            "customer_id": str(inactive_ctx["customer_id"]),
            "lines": [
                {
                    "line_kind": "UNIT",
                    "castranova_barcode": inactive_ctx["barcode"],
                }
            ],
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    _assert_inactive_400(r)


def test_ticket_part_line_rejects_inactive_sku(
    client: TestClient,
    staff_token_headers: dict[str, str],
    inactive_ctx: dict[str, Any],
) -> None:
    r = client.post(
        f"{PREFIX}/service-tickets/record",
        headers=staff_token_headers,
        json={
            "customer_id": str(inactive_ctx["customer_id"]),
            "issue": "Noisy",
            "idempotency_key": str(uuid.uuid4()),
            "parts": [{"sku": inactive_ctx["part_sku"], "quantity": 1}],
        },
    )
    _assert_inactive_400(r)


def test_receive_quantity_rejects_inactive_product(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    inactive_ctx: dict[str, Any],
) -> None:
    r = client.post(
        f"{PREFIX}/receipts/quantity",
        headers=superuser_token_headers,
        json={
            "product_id": str(inactive_ctx["part_id"]),
            "supplier_id": str(inactive_ctx["supplier_id"]),
            "received_qty": 5,
            "purchase_cost_thb": "4.00",
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    _assert_inactive_400(r)


def test_receive_serialized_rejects_inactive_product(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    inactive_ctx: dict[str, Any],
) -> None:
    r = client.post(
        f"{PREFIX}/receipts/serialized",
        headers=superuser_token_headers,
        json={
            "product_id": str(inactive_ctx["serialized_id"]),
            "supplier_id": str(inactive_ctx["supplier_id"]),
            "pieces": [
                {"supplier_serial": "SN-NEW", "purchase_cost_thb": "300.00"}
            ],
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    _assert_inactive_400(r)


def test_pull_create_rejects_inactive_product_line(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    inactive_ctx: dict[str, Any],
) -> None:
    r = client.post(
        f"{PREFIX}/project-pulls",
        headers=superuser_token_headers,
        json={
            "project_id": str(inactive_ctx["project_id"]),
            "admin_notes": "should fail",
            "lines": [
                {
                    "line_kind": "PART",
                    "product_id": str(inactive_ctx["part_id"]),
                    "requested_qty": 1,
                }
            ],
        },
    )
    _assert_inactive_400(r)


def test_sale_error_names_the_offending_sku(
    client: TestClient,
    staff_token_headers: dict[str, str],
    inactive_ctx: dict[str, Any],
) -> None:
    """The 400 must tell the cashier WHICH product is inactive."""
    r = client.post(
        f"{PREFIX}/sales",
        headers=staff_token_headers,
        json={
            "customer_id": str(inactive_ctx["customer_id"]),
            "lines": [
                {
                    "line_kind": "PART",
                    "sku": inactive_ctx["part_sku"],
                    "quantity": 1,
                }
            ],
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 400, r.text
    assert inactive_ctx["part_sku"] in r.json()["detail"]
