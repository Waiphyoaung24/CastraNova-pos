import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    CustomerCreate,
    Location,
    ProductCreate,
    ProjectCreate,
    SupplierCreate,
    TrackingMode,
)
from tests.utils.utils import assert_no_financial_keys

PREFIX = settings.API_V1_STR


def _seed_project_with_one_pull(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
) -> uuid.UUID:
    """Create a customer + project (admin), receive a QUANTITY part, then create
    a project pull (admin) and fulfill it (staff) so consumed_cost_thb > 0."""
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    admin = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert admin is not None
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Proj Dash Cust")
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

    create_body = {
        "project_id": str(project.id),
        "lines": [
            {
                "line_kind": "PART",
                "product_id": str(part.id),
                "requested_qty": 2,
            }
        ],
    }
    r = client.post(
        f"{PREFIX}/project-pulls",
        headers=superuser_token_headers,
        json=create_body,
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
    return project.id


def test_project_dashboard_staff_redacts_budget_and_cost(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
) -> None:
    project_id = _seed_project_with_one_pull(
        client, superuser_token_headers, staff_token_headers, db
    )
    r = client.get(
        f"{PREFIX}/projects/{project_id}/dashboard", headers=staff_token_headers
    )
    assert r.status_code == 200
    assert_no_financial_keys(r.json())


def test_project_dashboard_admin_shows_budget_and_consumed_cost(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
) -> None:
    project_id = _seed_project_with_one_pull(
        client, superuser_token_headers, staff_token_headers, db
    )
    r = client.get(
        f"{PREFIX}/projects/{project_id}/dashboard",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert "budget_thb" in body and "consumed_cost_thb" in body
    # The fulfilled pull pulled 2 parts @ 12.00 = 24.00 consumed cost.
    assert body["consumed_cost_thb"] == "24.00"


def test_project_dashboard_404(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.get(
        f"{PREFIX}/projects/{uuid.uuid4()}/dashboard",
        headers=superuser_token_headers,
    )
    assert r.status_code == 404


def test_project_routes_still_admin_only(
    client: TestClient, staff_token_headers: dict[str, str]
) -> None:
    # guard relocation must NOT open the write/list routes to staff
    assert (
        client.get(f"{PREFIX}/projects/", headers=staff_token_headers).status_code
        == 403
    )
    assert (
        client.post(
            f"{PREFIX}/projects/", headers=staff_token_headers, json={}
        ).status_code
        == 403
    )
