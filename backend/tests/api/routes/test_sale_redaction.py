"""TDD red-step: staff sale responses must omit cost fields.

Task 1.1 — schemas added; route dispatch (Task 1.2) not yet wired.
The staff test is expected to FAIL until Task 1.2 switches the endpoint
to return SaleStaffPublic for YGN_STAFF callers.
"""
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
)

PREFIX = settings.API_V1_STR


@pytest.fixture
def seed_redaction_unit(
    db: Session,
) -> Iterator[tuple[str, uuid.UUID]]:
    """Receive one IN_STOCK serialized unit (retail 1000) + a customer.

    Yields (castranova_barcode, customer_id).
    """
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"REDACT-{uuid.uuid4().hex[:8]}",
            model_name="RedactCompressor",
            tracking_mode=TrackingMode.SERIALIZED,
            retail_price_thb="1000.00",
            repair_price_thb="200.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name="RedactSupplier")
    )
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="RedactWalkIn")
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


def _sale_body(barcode: str, customer_id: uuid.UUID) -> dict[str, object]:
    return {
        "customer_id": str(customer_id),
        "lines": [{"line_kind": "UNIT", "castranova_barcode": barcode}],
        "idempotency_key": str(uuid.uuid4()),
    }


def test_staff_sale_response_omits_cost_fields(
    client: TestClient,
    staff_token_headers: dict[str, str],
    seed_redaction_unit: tuple[str, uuid.UUID],
) -> None:
    """STAFF callers must NOT see total_cogs_thb or unit_cost_thb (TDD RED)."""
    barcode, customer_id = seed_redaction_unit
    r = client.post(
        f"{PREFIX}/sales",
        headers=staff_token_headers,
        json=_sale_body(barcode, customer_id),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Revenue total must be present
    assert "total_thb" in body
    # Cost fields must be ABSENT for staff
    assert "total_cogs_thb" not in body, "total_cogs_thb must be redacted for staff"
    for line in body.get("lines", []):
        assert "unit_cost_thb" not in line, "unit_cost_thb must be redacted for staff"


def test_admin_sale_response_includes_cost_fields(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    seed_redaction_unit: tuple[str, uuid.UUID],
) -> None:
    """SUPERUSER callers must still see total_cogs_thb and unit_cost_thb."""
    barcode, customer_id = seed_redaction_unit
    r = client.post(
        f"{PREFIX}/sales",
        headers=superuser_token_headers,
        json=_sale_body(barcode, customer_id),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "total_thb" in body
    assert "total_cogs_thb" in body, "total_cogs_thb must be visible to superuser"
    for line in body.get("lines", []):
        assert "unit_cost_thb" in line, "unit_cost_thb must be visible to superuser"
