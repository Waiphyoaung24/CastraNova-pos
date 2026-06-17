"""Raw-HTTP redaction lock (hardening spec §4.1.7, spec §6.5/S7, PRD FR-015).

Walks staff-token responses and asserts NO derived-financial key appears at any
depth. Catches future schema edits that re-leak cost to staff. The one staff-
visible cost-by-design is the receive flow echoing the staff's own input
(2026-06-09 decision) — receive endpoints are deliberately not swept here.
"""

import uuid
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
    ProjectPullCreate,
    ProjectPullLineCreate,
    ReceivePiece,
    SaleLineInput,
    SaleLineKind,
    SupplierCreate,
    TrackingMode,
)

PREFIX = settings.API_V1_STR

FORBIDDEN_KEYS = {
    "purchase_cost_thb",
    "unit_cost_thb",
    "total_cost_thb",
    "total_cogs_thb",
    "cogs_thb",
    "margin_thb",
    "budget_thb",
    "consumed_cost_thb",
    # deviation_pct: conservative — staff DO see it on their own override request
    # today; forbidden here so no *list/report* surface ever exposes it in bulk.
    "deviation_pct",
}

# Substring layer: catches renamed/derived leaks the exact set misses
# (lifetime_sale_cogs_thb, revenue_thb, total_margin_thb, ...). The staff-public
# price keys (retail_price_thb, repair_price_thb, unit_price_thb, total_thb,
# default_price_thb, requested_price_thb) contain none of these.
FORBIDDEN_SUBSTRINGS = ("cogs", "margin", "budget", "revenue", "consumed_cost", "cost")


def _assert_no_forbidden_keys(node: Any, path: str = "$") -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            assert k not in FORBIDDEN_KEYS, f"financial key '{k}' leaked at {path}"
            assert not any(s in k for s in FORBIDDEN_SUBSTRINGS), (
                f"financial-looking key '{k}' leaked at {path}"
            )
            _assert_no_forbidden_keys(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _assert_no_forbidden_keys(v, f"{path}[{i}]")


def _user_id(db: Session) -> uuid.UUID:
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    return user.id


def _seed(db: Session) -> None:
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)


def _seed_sweep_rows(db: Session) -> dict[str, Any]:
    """One row on every swept surface so the sweep can't pass vacuously: a
    QUANTITY product with on-hand 3 < min-stock 100 (populates /products/,
    /dashboards/stock-on-hand AND /low-stock) plus one PENDING project pull."""
    _seed(db)
    user_id = _user_id(db)
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"RLSW-{uuid.uuid4().hex[:8]}",
            model_name="Widget",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="100.00",
            repair_price_thb="20.00",
            default_min_stock_level=100,
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"Sup-{uuid.uuid4().hex[:6]}")
    )
    crud.receive_quantity(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        received_qty=3,
        purchase_cost_thb=Decimal("10.00"),
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user_id,
    )
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Sweep Seed Co")
    )
    project = crud.create_project(
        session=db,
        project_in=ProjectCreate(
            code=f"PRJ-{uuid.uuid4().hex[:8]}",
            name="Sweep Site",
            customer_id=customer.id,
        ),
    )
    pull = crud.create_project_pull(
        session=db,
        pull_in=ProjectPullCreate(
            project_id=project.id,
            lines=[
                ProjectPullLineCreate(
                    line_kind=SaleLineKind.PART,
                    product_id=product.id,
                    requested_qty=1,
                )
            ],
        ),
        created_by_user_id=user_id,
    )
    return {"sku": product.sku, "pull_id": str(pull.id)}


@pytest.mark.parametrize(
    "path",
    [
        "/low-stock",
        "/products/",
        "/dashboards/stock-on-hand",
        "/project-pulls",
    ],
)
def test_staff_get_sweep_carries_no_financial_keys(
    client: TestClient, staff_token_headers: dict[str, str], db: Session, path: str
) -> None:
    seeded = _seed_sweep_rows(db)
    r = client.get(f"{PREFIX}{path}", headers=staff_token_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    # Non-vacuous: the seeded row must be on the swept surface (lists are
    # newest-first, so the just-seeded row is within the default page).
    if path == "/products/":
        assert any(p["sku"] == seeded["sku"] for p in body)
    elif path == "/low-stock":
        assert any(row["sku"] == seeded["sku"] for row in body)
    elif path == "/dashboards/stock-on-hand":
        assert any(row["sku"] == seeded["sku"] for row in body["rows"])
    else:  # /project-pulls
        assert any(p["id"] == seeded["pull_id"] for p in body)
    _assert_no_forbidden_keys(body)


def test_staff_sku_search_keeps_attribution_without_cost(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    _seed(db)
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"RLCK-{uuid.uuid4().hex[:8]}",
            model_name="Widget",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="100.00",
            repair_price_thb="20.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"Sup-{uuid.uuid4().hex[:6]}")
    )
    crud.receive_quantity(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        received_qty=3,
        purchase_cost_thb=Decimal("10.00"),
        idempotency_key=uuid.uuid4(),
        received_by_user_id=_user_id(db),
    )

    r = client.get(f"{PREFIX}/search/sku/{product.sku}", headers=staff_token_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    _assert_no_forbidden_keys(body)
    # FR-015: staff keep batch-by-batch attribution — just without cost.
    assert body["batches"]
    assert {"batch_no", "received_at", "received_qty", "remaining_qty"} <= set(
        body["batches"][0]
    )


def test_staff_serial_search_movements_carry_no_cost(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    _seed(db)
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"RLCS-{uuid.uuid4().hex[:8]}",
            model_name="Machine",
            tracking_mode=TrackingMode.SERIALIZED,
            retail_price_thb="1000.00",
            repair_price_thb="300.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"Sup-{uuid.uuid4().hex[:6]}")
    )
    units = crud.receive_serialized(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        pieces=[
            ReceivePiece(
                supplier_serial=f"SN-{uuid.uuid4().hex[:6]}",
                purchase_cost_thb=Decimal("600.00"),
            )
        ],
        idempotency_key=uuid.uuid4(),
        received_by_user_id=_user_id(db),
    )
    barcode = units[0].castranova_barcode

    r = client.get(f"{PREFIX}/search/serial/{barcode}", headers=staff_token_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["movements"], "serial search must return the seeded RECEIVED movement"
    _assert_no_forbidden_keys(body)


@pytest.mark.parametrize(
    "path",
    [
        "/reports/channel-margin?month=2026-06",
        "/reports/holding-period",
    ],
)
def test_staff_reports_forbidden(
    client: TestClient, staff_token_headers: dict[str, str], path: str
) -> None:
    r = client.get(f"{PREFIX}{path}", headers=staff_token_headers)
    assert r.status_code == 403


def test_staff_customer_dashboard_carries_no_financials(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    # Seed a customer with one real sale (adapted from test_customer_dashboard.
    # _seed_customer_with_one_sale) so the swept response carries transactions.
    _seed(db)
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"RLCD-{uuid.uuid4().hex[:8]}",
            model_name="Compressor",
            tracking_mode=TrackingMode.SERIALIZED,
            retail_price_thb="1000.00",
            repair_price_thb="200.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"Sup-{uuid.uuid4().hex[:6]}")
    )
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Redaction Lock Co")
    )
    units = crud.receive_serialized(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        pieces=[
            ReceivePiece(
                supplier_serial=f"SN-{uuid.uuid4().hex[:6]}",
                purchase_cost_thb=Decimal("600.00"),
            )
        ],
        idempotency_key=uuid.uuid4(),
        received_by_user_id=_user_id(db),
    )
    crud.create_sale(
        session=db,
        customer_id=customer.id,
        lines=[
            SaleLineInput(
                line_kind=SaleLineKind.UNIT,
                castranova_barcode=units[0].castranova_barcode,
            )
        ],
        idempotency_key=uuid.uuid4(),
        created_by_user_id=_user_id(db),
    )

    r = client.get(
        f"{PREFIX}/customers/{customer.id}/dashboard", headers=staff_token_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    _assert_no_forbidden_keys(body)
    assert body["transactions"]


def test_staff_sku_search_consumption_carries_no_cost(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    _seed(db)
    uid = _user_id(db)
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"RLCC-{uuid.uuid4().hex[:8]}",
            model_name="Widget",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="100.00",
            repair_price_thb="20.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"Sup-{uuid.uuid4().hex[:6]}")
    )
    crud.receive_quantity(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        received_qty=10,
        purchase_cost_thb=Decimal("10.00"),
        idempotency_key=uuid.uuid4(),
        received_by_user_id=uid,
    )
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Lock Buyer")
    )
    crud.create_sale(
        session=db,
        customer_id=customer.id,
        lines=[SaleLineInput(line_kind=SaleLineKind.PART, sku=product.sku, quantity=4)],
        idempotency_key=uuid.uuid4(),
        created_by_user_id=uid,
    )

    r = client.get(f"{PREFIX}/search/sku/{product.sku}", headers=staff_token_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    _assert_no_forbidden_keys(body)  # NO cogs/cost/margin keys at any depth
    # Non-vacuous: the consuming event is present with attribution.
    assert body["consumption"], "consumption must be populated"
    ev = body["consumption"][0]
    assert ev["reference_kind"] == "SALE"
    assert ev["customer_name"] == "Lock Buyer"
