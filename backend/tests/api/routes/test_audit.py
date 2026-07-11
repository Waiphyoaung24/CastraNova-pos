"""GET /audit — unified, chronological, admin-only view over the unit_movement
and part_movement ledgers (FR-019)."""

import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from decimal import Decimal

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
    SaleLineInput,
    SaleLineKind,
    SupplierCreate,
    TrackingMode,
    Unit,
)

PREFIX = settings.API_V1_STR


@pytest.fixture
def seed_audit(db: Session) -> Iterator[dict[str, object]]:
    """A SERIALIZED receive (RECEIVED unit_movement) + a UNIT sale (SOLD
    unit_movement) and a QUANTITY receive + PART sale (RECEIVED + SOLD
    part_movement). Yields handy ids for filter assertions."""
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name="Audit Co")
    )
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Audit Cust")
    )

    ser = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"AUD-SER-{uuid.uuid4().hex[:8]}",
            model_name="Widget",
            tracking_mode=TrackingMode.SERIALIZED,
            retail_price_thb="100.00",
            repair_price_thb="20.00",
        ),
    )
    units = crud.receive_serialized(
        session=db,
        product_id=ser.id,
        supplier_id=supplier.id,
        pieces=[
            ReceivePiece(
                supplier_serial=f"SN-{uuid.uuid4().hex[:8]}",
                purchase_cost_thb=Decimal("50.00"),
            )
        ],
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user.id,
    )
    unit = db.get(Unit, units[0].id)
    assert unit is not None
    crud.create_sale(
        session=db,
        customer_id=customer.id,
        lines=[
            SaleLineInput(
                line_kind=SaleLineKind.UNIT,
                castranova_barcode=unit.castranova_barcode,
                quantity=1,
            )
        ],
        idempotency_key=uuid.uuid4(),
        created_by_user_id=user.id,
    )

    qty = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"AUD-QTY-{uuid.uuid4().hex[:8]}",
            model_name="Bearing",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="100.00",
            repair_price_thb="20.00",
        ),
    )
    batch = crud.receive_quantity(
        session=db,
        product_id=qty.id,
        supplier_id=supplier.id,
        received_qty=5,
        purchase_cost_thb=Decimal("10.00"),
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user.id,
    )
    crud.create_sale(
        session=db,
        customer_id=customer.id,
        lines=[
            SaleLineInput(
                line_kind=SaleLineKind.PART, sku=qty.sku, quantity=2
            )
        ],
        idempotency_key=uuid.uuid4(),
        created_by_user_id=user.id,
    )

    yield {
        "user_id": user.id,
        "unit_id": unit.id,
        "part_product_id": qty.id,
        "serial_product_id": ser.id,
        "serial_sku": ser.sku,
        "batch_no": batch.batch_no,
        "customer_name": customer.name,
        "actor_full_name": user.full_name or user.email,
        "part_model_name": qty.model_name,
        "part_sku": qty.sku,
        "unit_castranova_barcode": unit.castranova_barcode,
        "unit_supplier_serial": unit.supplier_serial,
    }


def test_audit_requires_admin(
    client: TestClient, staff_token_headers: dict[str, str]
) -> None:
    r = client.get(f"{PREFIX}/audit", headers=staff_token_headers)
    assert r.status_code == 403


@pytest.mark.usefixtures("seed_audit")
def test_audit_lists_chronologically(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    r = client.get(f"{PREFIX}/audit", headers=superuser_token_headers)
    assert r.status_code == 200
    rows = r.json()
    # RECEIVED unit, SOLD unit, RECEIVED part, SOLD part = 4 entries.
    assert len(rows) >= 4
    times = [row["occurred_at"] for row in rows]
    assert times == sorted(times, reverse=True)


@pytest.mark.usefixtures("seed_audit")
def test_audit_filter_event_type(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    r = client.get(
        f"{PREFIX}/audit?event_type=SOLD", headers=superuser_token_headers
    )
    assert r.status_code == 200
    rows = r.json()
    assert rows
    assert all(row["event_type"] == "SOLD" for row in rows)


def test_audit_filter_product_id_returns_only_part(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    seed_audit: dict[str, uuid.UUID],
) -> None:
    pid = seed_audit["part_product_id"]
    r = client.get(
        f"{PREFIX}/audit?product_id={pid}", headers=superuser_token_headers
    )
    assert r.status_code == 200
    rows = r.json()
    assert rows
    for row in rows:
        assert row["ledger"] == "PART"
        assert row["product_id"] == str(pid)
        assert row["unit_id"] is None
        assert row["quantity"] >= 1


def test_audit_filter_unit_id_returns_only_unit(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    seed_audit: dict[str, uuid.UUID],
) -> None:
    uid = seed_audit["unit_id"]
    r = client.get(
        f"{PREFIX}/audit?unit_id={uid}", headers=superuser_token_headers
    )
    assert r.status_code == 200
    rows = r.json()
    assert rows
    for row in rows:
        assert row["ledger"] == "UNIT"
        assert row["unit_id"] == str(uid)
        assert row["product_id"] is None
        assert row["quantity"] == 1


def test_audit_filter_date_window(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    seed_audit: dict[str, uuid.UUID],
) -> None:
    # Seeded movements occur at ~now; scope to the seeded unit to stay robust
    # against other rows in the session-scoped db.
    uid = seed_audit["unit_id"]
    now = datetime.now(tz=timezone.utc)
    upper = (now + timedelta(hours=1)).isoformat()
    future = (now + timedelta(hours=2)).isoformat()

    r = client.get(
        f"{PREFIX}/audit",
        params={"unit_id": str(uid), "to_date": upper},
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    assert r.json(), "expected seeded rows before the upper bound"

    r = client.get(
        f"{PREFIX}/audit",
        params={"unit_id": str(uid), "from_date": future},
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.usefixtures("seed_audit")
def test_audit_limit_bounds_results(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    r = client.get(f"{PREFIX}/audit?limit=2", headers=superuser_token_headers)
    assert r.status_code == 200
    assert len(r.json()) == 2


@pytest.mark.usefixtures("seed_audit")
def test_audit_ledger_field_distinguishes(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    r = client.get(f"{PREFIX}/audit", headers=superuser_token_headers)
    assert r.status_code == 200
    rows = r.json()
    ledgers = {row["ledger"] for row in rows}
    assert {"UNIT", "PART"} <= ledgers
    for row in rows:
        if row["ledger"] == "UNIT":
            assert row["unit_id"] is not None
            assert row["product_id"] is None
        else:
            assert row["product_id"] is not None
            assert row["unit_id"] is None


def test_audit_enriches_part_rows(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    seed_audit: dict[str, object],
) -> None:
    pid = seed_audit["part_product_id"]
    r = client.get(
        f"{PREFIX}/audit?product_id={pid}", headers=superuser_token_headers
    )
    assert r.status_code == 200
    rows = r.json()
    assert rows
    for row in rows:
        assert row["product_model_name"] == seed_audit["part_model_name"]
        assert row["product_sku"] == seed_audit["part_sku"]
        assert row["actor_full_name"] == seed_audit["actor_full_name"]
    sold = [row for row in rows if row["event_type"] == "SOLD"]
    assert sold, "expected a SOLD part row"
    for row in sold:
        assert row["customer_name"] == seed_audit["customer_name"]


def test_audit_enriches_unit_rows(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    seed_audit: dict[str, object],
) -> None:
    uid = seed_audit["unit_id"]
    r = client.get(
        f"{PREFIX}/audit?unit_id={uid}", headers=superuser_token_headers
    )
    assert r.status_code == 200
    rows = r.json()
    assert rows
    for row in rows:
        assert (
            row["unit_castranova_barcode"]
            == seed_audit["unit_castranova_barcode"]
        )
        assert row["unit_supplier_serial"] == seed_audit["unit_supplier_serial"]
        assert row["product_model_name"] == "Widget"
        assert row["actor_full_name"] == seed_audit["actor_full_name"]
    sold = [row for row in rows if row["event_type"] == "SOLD"]
    assert sold, "expected a SOLD unit row"
    for row in sold:
        assert row["customer_name"] == seed_audit["customer_name"]


def test_audit_filter_sku_quantity_product(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    seed_audit: dict[str, object],
) -> None:
    sku = seed_audit["part_sku"]
    pid = seed_audit["part_product_id"]
    r = client.get(
        f"{PREFIX}/audit", params={"sku": sku}, headers=superuser_token_headers
    )
    assert r.status_code == 200
    rows = r.json()
    assert rows
    for row in rows:
        assert row["ledger"] == "PART"
        assert row["product_id"] == str(pid)
        assert row["unit_id"] is None


def test_audit_filter_sku_serialized_product_reaches_unit_ledger(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    seed_audit: dict[str, object],
) -> None:
    sku = seed_audit["serial_sku"]
    uid = seed_audit["unit_id"]
    r = client.get(
        f"{PREFIX}/audit", params={"sku": sku}, headers=superuser_token_headers
    )
    assert r.status_code == 200
    rows = r.json()
    assert rows, "SKU filter must reach the UNIT ledger for a serialized product"
    for row in rows:
        assert row["ledger"] == "UNIT"
        assert row["unit_id"] == str(uid)


def test_audit_filter_sku_unknown_returns_empty(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    r = client.get(
        f"{PREFIX}/audit",
        params={"sku": "NO-SUCH-SKU-zzz"},
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    assert r.json() == []


def test_audit_filter_batch_no_spans_receive_and_consumption(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    seed_audit: dict[str, object],
) -> None:
    batch_no = seed_audit["batch_no"]
    pid = seed_audit["part_product_id"]
    r = client.get(
        f"{PREFIX}/audit",
        params={"batch_no": batch_no},
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    rows = r.json()
    assert rows
    for row in rows:
        assert row["ledger"] == "PART"
        assert row["product_id"] == str(pid)
    events = {row["event_type"] for row in rows}
    # RECEIVED matches via part_movement.part_batch_id; SOLD via cost_line draw.
    assert {"RECEIVED", "SOLD"} <= events


def test_audit_filter_batch_no_excludes_unit_ledger(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    seed_audit: dict[str, object],
) -> None:
    batch_no = seed_audit["batch_no"]
    r = client.get(
        f"{PREFIX}/audit",
        params={"batch_no": batch_no},
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    rows = r.json()
    assert rows
    assert all(row["ledger"] == "PART" for row in rows)
    assert all(row["unit_id"] is None for row in rows)
