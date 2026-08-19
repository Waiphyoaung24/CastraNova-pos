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
    ReceivePiece,
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


def _seed_project_with_unit_and_multibatch_part(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
) -> dict[str, object]:
    """One pull consuming BOTH ledgers: a SERIALIZED unit (cost 100.00) and 5
    QUANTITY parts drawn FIFO across two batches (3 @ 10.00 then 2 @ 12.00 =
    54.00). Total consumed cost 154.00. Returns ids for the assertions."""
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    admin = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert admin is not None
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Consumed Items Cust")
    )
    project = crud.create_project(
        session=db,
        project_in=ProjectCreate(
            code=f"PRJ-{uuid.uuid4().hex[:8]}",
            name="Consumed Items Site",
            customer_id=customer.id,
            budget_thb=Decimal("1000.00"),
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name="Acme Consumed")
    )
    serialized = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"SER-{uuid.uuid4().hex[:8]}",
            model_name="Machine",
            tracking_mode=TrackingMode.SERIALIZED,
            retail_price_thb="500.00",
            repair_price_thb="50.00",
        ),
    )
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
    units = crud.receive_serialized(
        session=db,
        product_id=serialized.id,
        supplier_id=supplier.id,
        pieces=[
            ReceivePiece(supplier_serial="SER-1", purchase_cost_thb=Decimal("100.00"))
        ],
        idempotency_key=uuid.uuid4(),
        received_by_user_id=admin.id,
    )
    barcode = units[0].castranova_barcode
    # Two batches so the 5-part draw must split FIFO across both.
    for qty, cost in ((3, "10.00"), (4, "12.00")):
        crud.receive_quantity(
            session=db,
            product_id=part.id,
            supplier_id=supplier.id,
            received_qty=qty,
            purchase_cost_thb=Decimal(cost),
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
                {
                    "line_kind": "UNIT",
                    "product_id": str(serialized.id),
                    "unit_serial": barcode,
                },
                {
                    "line_kind": "PART",
                    "product_id": str(part.id),
                    "requested_qty": 5,
                },
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
    assert r.json()["state"] == "FULFILLED", r.text
    db.expire_all()
    return {
        "project_id": project.id,
        "pull_id": pull["id"],
        "barcode": barcode,
        "serialized_product_id": str(serialized.id),
        "part_product_id": str(part.id),
    }


def test_project_dashboard_admin_lists_consumed_items_with_batch_attribution(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
) -> None:
    """FR-020: the project page shows the consumed-items list with batch
    attribution — one row per PROJECT_OUT movement, PART rows carrying the FIFO
    batch draws behind their cost."""
    ctx = _seed_project_with_unit_and_multibatch_part(
        client, superuser_token_headers, staff_token_headers, db
    )
    r = client.get(
        f"{PREFIX}/projects/{ctx['project_id']}/dashboard",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "consumed_items" in body, body.keys()
    rows = body["consumed_items"]
    assert len(rows) == 2, rows

    by_kind = {row["line_kind"]: row for row in rows}
    assert set(by_kind) == {"UNIT", "PART"}

    unit_row = by_kind["UNIT"]
    assert unit_row["unit_serial"] == ctx["barcode"]
    assert unit_row["product_id"] == ctx["serialized_product_id"]
    assert unit_row["quantity"] == 1
    assert unit_row["total_cost_thb"] == "100.00"
    # A serialized unit IS its own cost layer — no FIFO batch to attribute.
    assert unit_row["draws"] == []
    assert unit_row["project_pull_id"] == ctx["pull_id"]

    part_row = by_kind["PART"]
    assert part_row["unit_serial"] is None
    assert part_row["product_id"] == ctx["part_product_id"]
    assert part_row["quantity"] == 5
    assert part_row["total_cost_thb"] == "54.00"
    assert part_row["project_pull_id"] == ctx["pull_id"]
    # Batch attribution, oldest batch first: 3 @ 10.00 then 2 @ 12.00.
    draws = part_row["draws"]
    assert len(draws) == 2, draws
    assert [d["quantity"] for d in draws] == [3, 2]
    assert [d["unit_cost_thb"] for d in draws] == ["10.00", "12.00"]
    assert [d["total_cost_thb"] for d in draws] == ["30.00", "24.00"]
    assert all(d["batch_no"] for d in draws)
    assert len({d["batch_no"] for d in draws}) == 2


def test_consumed_items_reconcile_with_consumed_cost(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
) -> None:
    """The row costs must add up to the Budget card's consumed cost, which is
    computed by a separate aggregate — if these two ever disagree the screen
    contradicts itself."""
    ctx = _seed_project_with_unit_and_multibatch_part(
        client, superuser_token_headers, staff_token_headers, db
    )
    body = client.get(
        f"{PREFIX}/projects/{ctx['project_id']}/dashboard",
        headers=superuser_token_headers,
    ).json()
    assert body["consumed_cost_thb"] == "154.00"
    rows_total = sum(Decimal(row["total_cost_thb"]) for row in body["consumed_items"])
    assert rows_total == Decimal(body["consumed_cost_thb"])
    # Every PART row's draws must also add up to that row's own cost.
    for row in body["consumed_items"]:
        if row["draws"]:
            assert sum(Decimal(d["total_cost_thb"]) for d in row["draws"]) == Decimal(
                row["total_cost_thb"]
            )


def test_consumed_items_newest_first(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
) -> None:
    ctx = _seed_project_with_unit_and_multibatch_part(
        client, superuser_token_headers, staff_token_headers, db
    )
    rows = client.get(
        f"{PREFIX}/projects/{ctx['project_id']}/dashboard",
        headers=superuser_token_headers,
    ).json()["consumed_items"]
    stamps = [row["occurred_at"] for row in rows]
    assert stamps == sorted(stamps, reverse=True), stamps


def test_project_dashboard_staff_gets_no_consumed_items(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
) -> None:
    """consumed_items carries cost, so it is admin-only and must be physically
    absent from the staff payload — not merely empty. assert_no_financial_keys
    does not cover it (it screens for 'consumed_cost', not 'total_cost_thb')."""
    ctx = _seed_project_with_unit_and_multibatch_part(
        client, superuser_token_headers, staff_token_headers, db
    )
    body = client.get(
        f"{PREFIX}/projects/{ctx['project_id']}/dashboard",
        headers=staff_token_headers,
    ).json()
    assert "consumed_items" not in body, body.keys()
    assert "cost" not in str(body).lower()


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


def test_project_dashboard_requires_auth(client: TestClient) -> None:
    r = client.get(f"{PREFIX}/projects/{uuid.uuid4()}/dashboard")
    assert r.status_code == 401


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
