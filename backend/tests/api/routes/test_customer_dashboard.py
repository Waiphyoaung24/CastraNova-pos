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
    ProjectCreate,
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


def _seed_customer_with_one_project_pull(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Adapted from test_project_dashboard._seed_project_with_one_pull: create a
    customer + project (admin), receive a QUANTITY part, then create and fulfill
    a project pull so the project's consumed_cost_thb is 24.00. Returns
    (customer_id, project_id)."""
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    admin = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert admin is not None
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Cust Dash Proj")
    )
    project = crud.create_project(
        session=db,
        project_in=ProjectCreate(
            code=f"PRJ-{uuid.uuid4().hex[:8]}",
            name="Dash Site",
            customer_id=customer.id,
            budget_thb=Decimal("1000.00"),
        ),
    )
    supplier = crud.create_supplier(session=db, supplier_in=SupplierCreate(name="Acme"))
    part = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"QTY-{uuid.uuid4().hex[:8]}",
            model_name="Bolt",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="10.00",
            repair_price_thb="2.00",
        ),
    )
    crud.receive_quantity(
        session=db,
        product_id=part.id,
        supplier_id=supplier.id,
        received_qty=4,
        purchase_cost_thb=Decimal("12.00"),
        idempotency_key=uuid.uuid4(),
        received_by_user_id=admin.id,
    )
    db.expire_all()
    r = client.post(
        f"{PREFIX}/project-pulls",
        headers=superuser_token_headers,
        json={
            "project_id": str(project.id),
            "lines": [
                {"line_kind": "PART", "product_id": str(part.id), "requested_qty": 2}
            ],
        },
    )
    assert r.status_code == 200, r.text
    pull = r.json()
    r = client.post(
        f"{PREFIX}/project-pulls/{pull['id']}/fulfill",
        headers=staff_token_headers,
        json={"lines": []},
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "FULFILLED"
    db.expire_all()
    return customer.id, project.id


def test_customer_dashboard_project_row_has_consumed_cost(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
) -> None:
    # Proves the N+1 -> batch refactor preserves the per-project arithmetic.
    customer_id, project_id = _seed_customer_with_one_project_pull(
        client, superuser_token_headers, staff_token_headers, db
    )
    r = client.get(
        f"{PREFIX}/customers/{customer_id}/dashboard",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    body = r.json()
    rows = body["active_projects"] + body["closed_projects"]
    row = next(p for p in rows if p["id"] == str(project_id))
    # The fulfilled pull pulled 2 parts @ 12.00 = 24.00 consumed cost.
    assert row["consumed_cost_thb"] == "24.00"


def test_customer_dashboard_transactions_include_project_pull(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
) -> None:
    # The fulfilled project pull seeded for this customer must surface as a
    # PROJECT_PULL transaction in the dashboard (covers _customer_transactions
    # PROJECT_PULL branch).
    customer_id, _ = _seed_customer_with_one_project_pull(
        client, superuser_token_headers, staff_token_headers, db
    )
    data = crud.get_customer_dashboard(session=db, customer_id=customer_id)
    kinds = {t["kind"] for t in data["transactions"]}
    assert "PROJECT_PULL" in kinds


def _seed_customer_with_closed_ticket(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
) -> uuid.UUID:
    """Create a fresh customer, stock a QUANTITY part, then open a service
    ticket, add a part, and close it (sets closed_at). Returns customer_id."""
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Maint Cust")
    )
    supplier = crud.create_supplier(session=db, supplier_in=SupplierCreate(name="Acme"))
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
    crud.receive_quantity(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        received_qty=5,
        purchase_cost_thb=Decimal("10.00"),
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user.id,
    )
    db.expire_all()
    r = client.post(
        f"{PREFIX}/service-tickets/record",
        headers=staff_token_headers,
        json={
            "customer_id": str(customer.id),
            "issue": "Noisy compressor",
            "idempotency_key": str(uuid.uuid4()),
            "resolution": "Replaced bearings",
            "parts": [{"sku": product.sku, "quantity": 2}],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["closed_at"] is not None
    db.expire_all()
    return customer.id


def test_customer_dashboard_transactions_include_maintenance(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
) -> None:
    # A closed service ticket must surface as a MAINTENANCE transaction (covers
    # _customer_transactions MAINTENANCE branch).
    customer_id = _seed_customer_with_closed_ticket(client, staff_token_headers, db)
    data = crud.get_customer_dashboard(session=db, customer_id=customer_id)
    kinds = {t["kind"] for t in data["transactions"]}
    assert "MAINTENANCE" in kinds


def _seed_customer_with_one_unit_pull(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
) -> tuple[uuid.UUID, uuid.UUID, Decimal]:
    """Create a customer + project, receive ONE serialized unit (cost 750.00),
    then create and fulfill a project pull of that UNIT line. Returns
    (customer_id, project_id, unit_purchase_cost)."""
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    admin = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert admin is not None
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Cust Unit Pull")
    )
    project = crud.create_project(
        session=db,
        project_in=ProjectCreate(
            code=f"PRJ-{uuid.uuid4().hex[:8]}",
            name="Unit Pull Site",
            customer_id=customer.id,
            budget_thb=Decimal("5000.00"),
        ),
    )
    supplier = crud.create_supplier(session=db, supplier_in=SupplierCreate(name="Acme"))
    serialized = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"SER-{uuid.uuid4().hex[:8]}",
            model_name="Compressor",
            tracking_mode=TrackingMode.SERIALIZED,
            retail_price_thb="2000.00",
            repair_price_thb="400.00",
        ),
    )
    unit_cost = Decimal("750.00")
    units = crud.receive_serialized(
        session=db,
        product_id=serialized.id,
        supplier_id=supplier.id,
        pieces=[
            ReceivePiece(
                supplier_serial=f"SN-{uuid.uuid4().hex[:6]}",
                purchase_cost_thb=unit_cost,
            )
        ],
        idempotency_key=uuid.uuid4(),
        received_by_user_id=admin.id,
    )
    barcode = units[0].castranova_barcode
    db.expire_all()
    r = client.post(
        f"{PREFIX}/project-pulls",
        headers=superuser_token_headers,
        json={
            "project_id": str(project.id),
            "lines": [
                {
                    "line_kind": "UNIT",
                    "product_id": str(serialized.id),
                    "unit_serial": barcode,
                }
            ],
        },
    )
    assert r.status_code == 200, r.text
    pull = r.json()
    r = client.post(
        f"{PREFIX}/project-pulls/{pull['id']}/fulfill",
        headers=staff_token_headers,
        json={"lines": []},
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "FULFILLED"
    db.expire_all()
    return customer.id, project.id, unit_cost


def test_customer_dashboard_project_row_includes_unit_cogs(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
) -> None:
    # Pulling a SERIALIZED unit into a project must count its purchase cost in the
    # project's consumed_cost_thb (covers _project_consumed_costs unit-COGS loop).
    customer_id, project_id, unit_cost = _seed_customer_with_one_unit_pull(
        client, superuser_token_headers, staff_token_headers, db
    )
    r = client.get(
        f"{PREFIX}/customers/{customer_id}/dashboard",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    body = r.json()
    rows = body["active_projects"] + body["closed_projects"]
    row = next(p for p in rows if p["id"] == str(project_id))
    assert row["consumed_cost_thb"] == f"{unit_cost:.2f}"


def test_customer_dashboard_requires_auth(client: TestClient) -> None:
    r = client.get(f"{PREFIX}/customers/{uuid.uuid4()}/dashboard")
    assert r.status_code == 401


def test_customer_dashboard_404(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    r = client.get(
        f"{PREFIX}/customers/{uuid.uuid4()}/dashboard",
        headers=superuser_token_headers,
    )
    assert r.status_code == 404
