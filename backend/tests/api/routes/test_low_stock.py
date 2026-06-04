"""Low-stock alerts (FR-016, Task 2.8).

Covers the per-SKU min-stock-level admin edits (single + bulk), the GET
/low-stock list (both tracking modes), and the cross-threshold push alert fired
from the FIFO consumption chokepoint when on-hand DROPS below the threshold.

The notify network seam ``app.services.notify._post`` is monkeypatched so no
real HTTP happens. Starlette's TestClient runs BackgroundTasks synchronously
within the request, so the NotificationLog row is assertable right after a call.
"""

import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    CustomerCreate,
    Location,
    NotificationChannel,
    NotificationEvent,
    NotificationLog,
    NotificationPreference,
    NotificationStatus,
    Product,
    ProductCreate,
    ReceivePiece,
    SupplierCreate,
    TrackingMode,
    User,
    UserCreate,
    UserRole,
)
from app.services import notify

PREFIX = settings.API_V1_STR


# --- helpers ------------------------------------------------------------------


def _make_quantity_product(db: Session, *, min_level: int | None) -> Product:
    return crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"LS-Q-{uuid.uuid4().hex[:8]}",
            model_name="Widget",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="100.00",
            repair_price_thb="20.00",
            default_min_stock_level=min_level,
        ),
    )


def _stock_quantity(db: Session, product: Product, qty: int) -> None:
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"Sup-{uuid.uuid4().hex[:6]}")
    )
    crud.receive_quantity(
        session=db,
        product_id=product.id,
        supplier_id=supplier.id,
        received_qty=qty,
        purchase_cost_thb=Decimal("10.00"),
        idempotency_key=uuid.uuid4(),
        received_by_user_id=user.id,
    )


def _make_serialized_product_with_stock(
    db: Session, *, min_level: int, in_stock: int
) -> Product:
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"LS-S-{uuid.uuid4().hex[:8]}",
            model_name="Compressor",
            tracking_mode=TrackingMode.SERIALIZED,
            retail_price_thb="1000.00",
            repair_price_thb="200.00",
            default_min_stock_level=min_level,
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"Sup-{uuid.uuid4().hex[:6]}")
    )
    if in_stock:
        crud.receive_serialized(
            session=db,
            product_id=product.id,
            supplier_id=supplier.id,
            pieces=[
                ReceivePiece(
                    supplier_serial=f"SN-{uuid.uuid4().hex[:8]}",
                    purchase_cost_thb="600.00",
                )
                for _ in range(in_stock)
            ],
            idempotency_key=uuid.uuid4(),
            received_by_user_id=user.id,
        )
    return product


def _resp(status_code: int, json_body: dict[str, Any] | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=json_body if json_body is not None else {},
        request=httpx.Request("POST", "https://example.test"),
    )


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tenacity.nap.time.sleep", lambda *_: None)


@pytest.fixture(autouse=True)
def _tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LINE_CHANNEL_ACCESS_TOKEN", "line-token")
    monkeypatch.setattr(settings, "VIBER_AUTH_TOKEN", "viber-token")


def _opt_in_admin(db: Session) -> User:
    """An admin opted into LINE LOW_STOCK with a line_user_id set."""
    admin = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=f"lowstock-{uuid.uuid4().hex[:8]}@example.com",
            password="password123",
            role=UserRole.BKK_ADMIN,
        ),
    )
    admin.line_user_id = "L-admin"
    db.add(admin)
    db.add(
        NotificationPreference(
            user_id=admin.id,
            channel=NotificationChannel.LINE,
            event_type=NotificationEvent.LOW_STOCK,
            enabled=True,
        )
    )
    db.commit()
    db.refresh(admin)
    return admin


def _make_customer(db: Session) -> uuid.UUID:
    return crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Walk-in")
    ).id


def _low_stock_logs(db: Session, product_id: uuid.UUID) -> list[NotificationLog]:
    db.expire_all()
    logs = db.exec(
        select(NotificationLog).where(
            NotificationLog.event_type == NotificationEvent.LOW_STOCK
        )
    ).all()
    return [log for log in logs if log.payload.get("product_id") == str(product_id)]


# --- GET /low-stock -----------------------------------------------------------


def test_low_stock_list_quantity_and_serialized(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    low_q = _make_quantity_product(db, min_level=5)
    _stock_quantity(db, low_q, 3)  # 3 < 5 -> low
    ok_q = _make_quantity_product(db, min_level=5)
    _stock_quantity(db, ok_q, 10)  # 10 >= 5 -> not low
    unmonitored = _make_quantity_product(db, min_level=None)
    _stock_quantity(db, unmonitored, 1)  # NULL threshold -> never low
    low_s = _make_serialized_product_with_stock(db, min_level=4, in_stock=2)  # low

    r = client.get(f"{PREFIX}/low-stock", headers=staff_token_headers)
    assert r.status_code == 200, r.text
    by_id = {item["product_id"]: item for item in r.json()}

    assert str(low_q.id) in by_id
    assert by_id[str(low_q.id)]["on_hand"] == 3
    assert by_id[str(low_q.id)]["min_stock_level"] == 5
    assert by_id[str(low_q.id)]["tracking_mode"] == "QUANTITY"

    assert str(ok_q.id) not in by_id
    assert str(unmonitored.id) not in by_id

    assert str(low_s.id) in by_id
    assert by_id[str(low_s.id)]["on_hand"] == 2
    assert by_id[str(low_s.id)]["min_stock_level"] == 4
    assert by_id[str(low_s.id)]["tracking_mode"] == "SERIALIZED"


# --- PATCH /products/{id}/min-stock-level -------------------------------------


def test_set_min_stock_level_admin(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    product = _make_quantity_product(db, min_level=None)
    r = client.patch(
        f"{PREFIX}/products/{product.id}/min-stock-level",
        headers=superuser_token_headers,
        json={"min_stock_level": 7},
    )
    assert r.status_code == 200, r.text
    assert r.json()["default_min_stock_level"] == 7
    db.expire_all()
    persisted = db.get(Product, product.id)
    assert persisted is not None and persisted.default_min_stock_level == 7


def test_set_min_stock_level_clear_with_null(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    product = _make_quantity_product(db, min_level=5)
    r = client.patch(
        f"{PREFIX}/products/{product.id}/min-stock-level",
        headers=superuser_token_headers,
        json={"min_stock_level": None},
    )
    assert r.status_code == 200, r.text
    assert r.json()["default_min_stock_level"] is None
    db.expire_all()
    persisted = db.get(Product, product.id)
    assert persisted is not None and persisted.default_min_stock_level is None


def test_set_min_stock_level_staff_forbidden(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    product = _make_quantity_product(db, min_level=None)
    r = client.patch(
        f"{PREFIX}/products/{product.id}/min-stock-level",
        headers=staff_token_headers,
        json={"min_stock_level": 7},
    )
    assert r.status_code == 403


def test_set_min_stock_level_unknown_product_404(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.patch(
        f"{PREFIX}/products/{uuid.uuid4()}/min-stock-level",
        headers=superuser_token_headers,
        json={"min_stock_level": 7},
    )
    assert r.status_code == 404


# --- PATCH /low-stock/bulk ----------------------------------------------------


def test_bulk_set_min_stock_level_20_skus(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    products = [_make_quantity_product(db, min_level=None) for _ in range(20)]
    items = [
        {"product_id": str(p.id), "min_stock_level": i + 1}
        for i, p in enumerate(products)
    ]
    r = client.patch(
        f"{PREFIX}/low-stock/bulk",
        headers=superuser_token_headers,
        json={"items": items},
    )
    assert r.status_code == 200, r.text
    db.expire_all()
    for i, p in enumerate(products):
        persisted = db.get(Product, p.id)
        assert persisted is not None and persisted.default_min_stock_level == i + 1


def test_bulk_set_min_stock_level_staff_forbidden(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    product = _make_quantity_product(db, min_level=None)
    r = client.patch(
        f"{PREFIX}/low-stock/bulk",
        headers=staff_token_headers,
        json={"items": [{"product_id": str(product.id), "min_stock_level": 5}]},
    )
    assert r.status_code == 403


def test_bulk_set_unknown_product_404_nothing_applied(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    good = _make_quantity_product(db, min_level=None)
    missing = uuid.uuid4()
    r = client.patch(
        f"{PREFIX}/low-stock/bulk",
        headers=superuser_token_headers,
        json={
            "items": [
                {"product_id": str(good.id), "min_stock_level": 5},
                {"product_id": str(missing), "min_stock_level": 9},
            ]
        },
    )
    assert r.status_code == 404
    db.expire_all()
    # nothing applied — the good product is untouched
    persisted = db.get(Product, good.id)
    assert persisted is not None and persisted.default_min_stock_level is None


def test_bulk_set_duplicate_product_422(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    product = _make_quantity_product(db, min_level=None)
    r = client.patch(
        f"{PREFIX}/low-stock/bulk",
        headers=superuser_token_headers,
        json={
            "items": [
                {"product_id": str(product.id), "min_stock_level": 5},
                {"product_id": str(product.id), "min_stock_level": 9},
            ]
        },
    )
    assert r.status_code == 422


# --- cross-threshold alert ----------------------------------------------------


def _sale_part_body(sku: str, customer_id: uuid.UUID, qty: int) -> dict[str, Any]:
    return {
        "customer_id": str(customer_id),
        "lines": [{"line_kind": "PART", "sku": sku, "quantity": qty}],
        "idempotency_key": str(uuid.uuid4()),
    }


def test_sale_crossing_threshold_fires_alert(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notify, "_post", lambda *a, **k: _resp(200))
    _opt_in_admin(db)
    product = _make_quantity_product(db, min_level=5)
    _stock_quantity(db, product, 6)  # 6 >= 5
    customer_id = _make_customer(db)

    r = client.post(
        f"{PREFIX}/sales",
        headers=staff_token_headers,
        json=_sale_part_body(product.sku, customer_id, 2),  # 6 -> 4, crosses below 5
    )
    assert r.status_code == 200, r.text

    logs = _low_stock_logs(db, product.id)
    sent = [log for log in logs if log.status == NotificationStatus.SENT]
    assert len(sent) >= 1
    log = sent[0]
    assert log.channel == NotificationChannel.LINE
    assert log.payload["sku"] == product.sku
    assert log.payload["on_hand"] == 4
    assert log.payload["min_stock_level"] == 5


def test_ticket_close_crossing_threshold_fires_alert(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notify, "_post", lambda *a, **k: _resp(200))
    _opt_in_admin(db)
    product = _make_quantity_product(db, min_level=5)
    _stock_quantity(db, product, 6)
    customer_id = _make_customer(db)

    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    ticket = crud.open_service_ticket(
        session=db,
        customer_id=customer_id,
        issue="fix",
        notes=None,
        idempotency_key=uuid.uuid4(),
        created_by_user_id=user.id,
    )
    crud.add_service_ticket_part(
        session=db,
        ticket_id=ticket.id,
        sku=product.sku,
        quantity=2,  # 6 -> 4 at close, crosses below 5
        unit_price_thb=Decimal("50.00"),
    )

    r = client.post(
        f"{PREFIX}/service-tickets/{ticket.id}/close",
        headers=staff_token_headers,
        json={"resolution": "done"},
    )
    assert r.status_code == 200, r.text

    logs = _low_stock_logs(db, product.id)
    sent = [log for log in logs if log.status == NotificationStatus.SENT]
    assert len(sent) >= 1
    assert sent[0].payload["on_hand"] == 4


# --- no false alerts ----------------------------------------------------------


def test_already_below_threshold_no_new_alert(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notify, "_post", lambda *a, **k: _resp(200))
    _opt_in_admin(db)
    product = _make_quantity_product(db, min_level=5)
    _stock_quantity(db, product, 4)  # already below 5
    customer_id = _make_customer(db)

    r = client.post(
        f"{PREFIX}/sales",
        headers=staff_token_headers,
        json=_sale_part_body(product.sku, customer_id, 1),  # 4 -> 3, still below
    )
    assert r.status_code == 200, r.text
    assert _low_stock_logs(db, product.id) == []


def test_stays_above_threshold_no_alert(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notify, "_post", lambda *a, **k: _resp(200))
    _opt_in_admin(db)
    product = _make_quantity_product(db, min_level=5)
    _stock_quantity(db, product, 10)
    customer_id = _make_customer(db)

    r = client.post(
        f"{PREFIX}/sales",
        headers=staff_token_headers,
        json=_sale_part_body(product.sku, customer_id, 2),  # 10 -> 8, still >= 5
    )
    assert r.status_code == 200, r.text
    assert _low_stock_logs(db, product.id) == []


def test_null_threshold_never_alerts(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notify, "_post", lambda *a, **k: _resp(200))
    _opt_in_admin(db)
    product = _make_quantity_product(db, min_level=None)
    _stock_quantity(db, product, 6)
    customer_id = _make_customer(db)

    r = client.post(
        f"{PREFIX}/sales",
        headers=staff_token_headers,
        json=_sale_part_body(product.sku, customer_id, 5),  # 6 -> 1, no threshold
    )
    assert r.status_code == 200, r.text
    assert _low_stock_logs(db, product.id) == []


def test_alert_failure_does_not_break_sale(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notify, "_post", lambda *a, **k: _resp(503))
    _opt_in_admin(db)
    product = _make_quantity_product(db, min_level=5)
    _stock_quantity(db, product, 6)
    customer_id = _make_customer(db)

    r = client.post(
        f"{PREFIX}/sales",
        headers=staff_token_headers,
        json=_sale_part_body(product.sku, customer_id, 2),  # crosses below 5
    )
    # sale still succeeds; a FAILED log is recorded
    assert r.status_code == 200, r.text
    logs = _low_stock_logs(db, product.id)
    assert any(log.status == NotificationStatus.FAILED for log in logs)
