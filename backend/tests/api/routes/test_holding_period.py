"""Holding-period report (FR-014, Task 3.3).

now() - received_at per in-stock unit + per QUANTITY SKU (oldest active batch),
flagged against the system_setting threshold (default 90 days). Admin-only."""

import uuid
from datetime import timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    Location,
    PartBatch,
    ProductCreate,
    ReceivePiece,
    SupplierCreate,
    TrackingMode,
    Unit,
    get_datetime_utc,
)

PREFIX = settings.API_V1_STR


def _user_id(db: Session) -> uuid.UUID:
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    return user.id


def _seed_old_stock(db: Session) -> tuple[str, str]:
    """A QUANTITY SKU (one batch, 100 days old) + a SERIALIZED unit (5 days old).
    Returns (quantity_sku, serial_barcode)."""
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    crud.set_setting(session=db, key=crud.HOLDING_THRESHOLD_KEY, value=90)

    qproduct = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"HOLD-{uuid.uuid4().hex[:8]}",
            model_name="Widget",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="100.00",
            repair_price_thb="20.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"Sup-{uuid.uuid4().hex[:6]}")
    )
    batch = crud.receive_quantity(
        session=db,
        product_id=qproduct.id,
        supplier_id=supplier.id,
        received_qty=10,
        purchase_cost_thb=Decimal("10.00"),
        idempotency_key=uuid.uuid4(),
        received_by_user_id=_user_id(db),
    )
    # Backdate the batch to 100 days ago (> 90-day threshold).
    db_batch = db.get(PartBatch, batch.id)
    assert db_batch is not None
    db_batch.received_at = get_datetime_utc() - timedelta(days=100)
    db.add(db_batch)

    sproduct = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"HOLDU-{uuid.uuid4().hex[:8]}",
            model_name="Machine",
            tracking_mode=TrackingMode.SERIALIZED,
            retail_price_thb="1000.00",
            repair_price_thb="300.00",
        ),
    )
    units = crud.receive_serialized(
        session=db,
        product_id=sproduct.id,
        supplier_id=supplier.id,
        pieces=[ReceivePiece(supplier_serial="SN-H1", purchase_cost_thb=Decimal("600.00"))],
        idempotency_key=uuid.uuid4(),
        received_by_user_id=_user_id(db),
    )
    unit = db.get(Unit, units[0].id)
    assert unit is not None
    unit.received_at = get_datetime_utc() - timedelta(days=5)  # under threshold
    db.add(unit)
    db.commit()
    return qproduct.sku, units[0].castranova_barcode


def test_holding_period_flags_old_quantity_batch(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    qsku, barcode = _seed_old_stock(db)
    r = client.get(
        f"{PREFIX}/reports/holding-period", headers=superuser_token_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["threshold_days"] == 90
    by_ref = {row["reference"]: row for row in body["rows"]}

    # QUANTITY SKU row uses the oldest batch and is flagged.
    qrows = [row for row in body["rows"] if row["sku"] == qsku]
    assert len(qrows) == 1
    assert qrows[0]["tracking_mode"] == "QUANTITY"
    assert qrows[0]["holding_days"] >= 100
    assert qrows[0]["over_threshold"] is True
    assert qrows[0]["quantity"] == 10

    # SERIALIZED unit present, recent, not flagged.
    assert barcode in by_ref
    assert by_ref[barcode]["over_threshold"] is False


def test_holding_period_over_threshold_only_filter(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    qsku, barcode = _seed_old_stock(db)
    r = client.get(
        f"{PREFIX}/reports/holding-period?over_threshold_only=true",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200, r.text
    refs = {row["reference"] for row in r.json()["rows"]}
    assert barcode not in refs  # recent unit filtered out
    assert all(row["over_threshold"] for row in r.json()["rows"])


def test_holding_period_staff_forbidden(
    client: TestClient, staff_token_headers: dict[str, str]
) -> None:
    r = client.get(
        f"{PREFIX}/reports/holding-period", headers=staff_token_headers
    )
    assert r.status_code == 403
