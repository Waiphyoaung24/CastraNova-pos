"""Search (FR-015, Task 3.4). Serial → chronological lifecycle; SKU → batch
attribution + QOH. Both roles; no cost fields leaked."""

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
    ReceivePiece,
    SaleLineInput,
    SaleLineKind,
    SupplierCreate,
    TrackingMode,
)

PREFIX = settings.API_V1_STR


def _user_id(db: Session) -> uuid.UUID:
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    return user.id


def _seed(db: Session) -> None:
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)


def test_serial_search_returns_chronological_lifecycle(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    _seed(db)
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"SRCH-{uuid.uuid4().hex[:8]}",
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
        pieces=[ReceivePiece(supplier_serial="SN-S1", purchase_cost_thb=Decimal("600.00"))],
        idempotency_key=uuid.uuid4(),
        received_by_user_id=_user_id(db),
    )
    barcode = units[0].castranova_barcode
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Buyer")
    )
    crud.create_sale(
        session=db,
        customer_id=customer.id,
        lines=[SaleLineInput(line_kind=SaleLineKind.UNIT, castranova_barcode=barcode)],
        idempotency_key=uuid.uuid4(),
        created_by_user_id=_user_id(db),
    )

    r = client.get(
        f"{PREFIX}/search/serial/{barcode}", headers=staff_token_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["castranova_barcode"] == barcode
    assert body["current_state"] == "SOLD"
    events = [m["event_type"] for m in body["movements"]]
    assert events == ["RECEIVED", "SOLD"]  # chronological
    # No cost fields leaked to staff.
    assert "purchase_cost_thb" not in body
    assert all("cost" not in k for m in body["movements"] for k in m)


def test_serial_search_unknown_404(
    client: TestClient, staff_token_headers: dict[str, str]
) -> None:
    r = client.get(
        f"{PREFIX}/search/serial/NOPE-123", headers=staff_token_headers
    )
    assert r.status_code == 404


def test_sku_search_batch_attribution(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    _seed(db)
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"SKUS-{uuid.uuid4().hex[:8]}",
            model_name="Widget",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="100.00",
            repair_price_thb="20.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"Sup-{uuid.uuid4().hex[:6]}")
    )
    for qty, cost in ((3, "10.00"), (4, "12.00")):
        crud.receive_quantity(
            session=db,
            product_id=product.id,
            supplier_id=supplier.id,
            received_qty=qty,
            purchase_cost_thb=Decimal(cost),
            idempotency_key=uuid.uuid4(),
            received_by_user_id=_user_id(db),
        )

    r = client.get(
        f"{PREFIX}/search/sku/{product.sku}", headers=staff_token_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tracking_mode"] == "QUANTITY"
    assert body["total_on_hand"] == 7
    assert len(body["batches"]) == 2
    # Batches oldest-first; no cost field leaked.
    assert [b["received_qty"] for b in body["batches"]] == [3, 4]
    assert all("cost" not in k for b in body["batches"] for k in b)
