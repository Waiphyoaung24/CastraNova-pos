import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    CustomerCreate,
    CustomerDashboardAdminPublic,
    Location,
    ProductCreate,
    ReceivePiece,
    SupplierCreate,
    TrackingMode,
)
from tests.utils.utils import assert_no_financial_keys

PREFIX = settings.API_V1_STR


def _seed_customer_with_one_sale(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
) -> tuple[uuid.UUID, Decimal, Decimal]:
    """Receive one serialized unit (retail 1000 / cost 600) and sell it to a
    fresh customer via the sales API. Returns (customer_id, revenue, cogs)."""
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"DASH-{uuid.uuid4().hex[:8]}",
            model_name="Compressor",
            tracking_mode=TrackingMode.SERIALIZED,
            retail_price_thb="1000.00",
            repair_price_thb="200.00",
        ),
    )
    supplier = crud.create_supplier(session=db, supplier_in=SupplierCreate(name="Acme"))
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Dashboard Co")
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
    body = {
        "customer_id": str(customer.id),
        "lines": [
            {"line_kind": "UNIT", "castranova_barcode": units[0].castranova_barcode}
        ],
        "idempotency_key": str(uuid.uuid4()),
    }
    r = client.post(f"{PREFIX}/sales", headers=staff_token_headers, json=body)
    assert r.status_code == 200, r.text
    db.expire_all()
    return customer.id, Decimal("1000.00"), Decimal("600.00")


def test_customer_dashboard_admin_aggregates_lifetime_sale(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
) -> None:
    customer_id, expected_rev, expected_cogs = _seed_customer_with_one_sale(
        client, staff_token_headers, db
    )
    data = crud.get_customer_dashboard(session=db, customer_id=customer_id)
    admin = CustomerDashboardAdminPublic.model_validate(data)
    assert admin.lifetime_sale_revenue_thb == expected_rev
    assert admin.lifetime_sale_cogs_thb == expected_cogs
    assert admin.lifetime_sale_margin_thb == expected_rev - expected_cogs


def test_customer_dashboard_staff_has_no_financial_keys(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
) -> None:
    customer_id, _, _ = _seed_customer_with_one_sale(client, staff_token_headers, db)
    r = client.get(
        f"{PREFIX}/customers/{customer_id}/dashboard", headers=staff_token_headers
    )
    assert r.status_code == 200
    body = r.json()
    assert_no_financial_keys(body)
    assert "transactions" in body and "active_projects" in body


def test_customer_dashboard_admin_has_financial_keys(
    client: TestClient,
    staff_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    customer_id, expected_rev, _ = _seed_customer_with_one_sale(
        client, staff_token_headers, db
    )
    r = client.get(
        f"{PREFIX}/customers/{customer_id}/dashboard",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["lifetime_sale_revenue_thb"] == f"{expected_rev:.2f}"
    assert "lifetime_sale_cogs_thb" in body


def test_customer_dashboard_404(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    r = client.get(
        f"{PREFIX}/customers/{uuid.uuid4()}/dashboard",
        headers=superuser_token_headers,
    )
    assert r.status_code == 404
