import uuid
from collections.abc import Iterator
from datetime import date, time, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    Location,
    PartBatch,
    PartMovement,
    ProductCreate,
    SupplierCreate,
    TrackingMode,
)

PREFIX = settings.API_V1_STR


@pytest.fixture
def seed_quantity_product(db: Session) -> Iterator[tuple[uuid.UUID, uuid.UUID, str]]:
    """A QUANTITY product + supplier + the YGN_WH location to receive into.

    Yields (product_id, supplier_id, sku)."""
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"QTY-{uuid.uuid4().hex[:8]}",
            model_name="Bearing",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="50.00",
            repair_price_thb="10.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name="Acme Parts", country="TH")
    )
    yield product.id, supplier.id, product.sku


def _body(product_id: uuid.UUID, supplier_id: uuid.UUID, **over: object) -> dict:
    body: dict = {
        "product_id": str(product_id),
        "supplier_id": str(supplier_id),
        "received_qty": 10,
        "purchase_cost_thb": "5.00",
        "idempotency_key": str(uuid.uuid4()),
    }
    body.update(over)
    return body


def test_receive_quantity_creates_batch_and_movement(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    seed_quantity_product: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    product_id, supplier_id, sku = seed_quantity_product
    r = client.post(
        f"{PREFIX}/receipts/quantity",
        headers=superuser_token_headers,
        json=_body(product_id, supplier_id),
    )
    assert r.status_code == 200, r.text
    batch = r.json()
    assert batch["received_qty"] == 10
    assert batch["remaining_qty"] == 10
    assert batch["batch_no"].endswith("-001")
    assert sku in batch["batch_no"]

    # An append-only RECEIVED part_movement was written with the received qty.
    db.expire_all()
    movements = db.exec(
        select(PartMovement).where(PartMovement.product_id == product_id)
    ).all()
    assert len(movements) == 1
    assert movements[0].event_type.value == "RECEIVED"
    assert movements[0].quantity == 10


def test_receive_quantity_idempotent_replay(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    seed_quantity_product: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    product_id, supplier_id, _ = seed_quantity_product
    body = _body(product_id, supplier_id)
    r1 = client.post(
        f"{PREFIX}/receipts/quantity", headers=superuser_token_headers, json=body
    )
    assert r1.status_code == 200
    db.expire_all()
    batches_before = len(db.exec(select(PartBatch)).all())
    movements_before = len(db.exec(select(PartMovement)).all())

    r2 = client.post(
        f"{PREFIX}/receipts/quantity", headers=superuser_token_headers, json=body
    )
    assert r2.status_code == 200
    # Replay returns the same batch and persists no new batch/movement rows.
    assert r1.json()["id"] == r2.json()["id"]
    db.expire_all()
    assert len(db.exec(select(PartBatch)).all()) == batches_before
    assert len(db.exec(select(PartMovement)).all()) == movements_before


def test_receive_quantity_requires_auth(
    client: TestClient,
    seed_quantity_product: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    product_id, supplier_id, _ = seed_quantity_product
    r = client.post(
        f"{PREFIX}/receipts/quantity", json=_body(product_id, supplier_id)
    )
    assert r.status_code == 401


def test_receive_quantity_rejects_serialized_product(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    seed_quantity_product: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    _, supplier_id, _ = seed_quantity_product
    serialized = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"SER-{uuid.uuid4().hex[:8]}",
            model_name="Compressor",
            tracking_mode=TrackingMode.SERIALIZED,
            retail_price_thb="1000.00",
            repair_price_thb="200.00",
        ),
    )
    r = client.post(
        f"{PREFIX}/receipts/quantity",
        headers=superuser_token_headers,
        json=_body(serialized.id, supplier_id),
    )
    assert r.status_code == 400
    assert "QUANTITY" in r.json()["detail"]


def test_receive_quantity_rejects_zero_qty(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    seed_quantity_product: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    product_id, supplier_id, _ = seed_quantity_product
    r = client.post(
        f"{PREFIX}/receipts/quantity",
        headers=superuser_token_headers,
        json=_body(product_id, supplier_id, received_qty=0),
    )
    assert r.status_code == 422


def test_receive_quantity_unknown_product_returns_404(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    seed_quantity_product: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    _, supplier_id, _ = seed_quantity_product
    r = client.post(
        f"{PREFIX}/receipts/quantity",
        headers=superuser_token_headers,
        json=_body(uuid.uuid4(), supplier_id),
    )
    assert r.status_code == 404
    assert "Product" in r.json()["detail"]


def test_receive_quantity_unknown_supplier_returns_404(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    seed_quantity_product: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    product_id, _, _ = seed_quantity_product
    r = client.post(
        f"{PREFIX}/receipts/quantity",
        headers=superuser_token_headers,
        json=_body(product_id, uuid.uuid4()),
    )
    assert r.status_code == 404
    assert "Supplier" in r.json()["detail"]


def test_receive_quantity_records_discrepancy_note(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    seed_quantity_product: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    product_id, supplier_id, _ = seed_quantity_product
    r = client.post(
        f"{PREFIX}/receipts/quantity",
        headers=superuser_token_headers,
        json=_body(
            product_id,
            supplier_id,
            received_qty=8,
            expected_qty=10,
            note="2 units missing from carton",
        ),
    )
    assert r.status_code == 200, r.text
    db.expire_all()
    movement = db.exec(
        select(PartMovement).where(PartMovement.product_id == product_id)
    ).one()
    assert movement.notes is not None
    assert "10" in movement.notes and "8" in movement.notes
    assert "2 units missing from carton" in movement.notes


def test_staff_cannot_receive_quantity(
    client: TestClient,
    staff_token_headers: dict[str, str],
    seed_quantity_product: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    """Receiving is admin-only (reverses FR-005/006 D3); staff are forbidden."""
    product_id, supplier_id, _sku = seed_quantity_product
    resp = client.post(
        f"{PREFIX}/receipts/quantity",
        headers=staff_token_headers,
        json=_body(product_id, supplier_id),
    )
    assert resp.status_code == 403, resp.text


def test_unauthenticated_cannot_receive_quantity(client: TestClient) -> None:
    resp = client.post(f"{PREFIX}/receipts/quantity", json={})
    assert resp.status_code == 401


# --- received_date (receive date picker, design 2026-07-25) -------------------


def test_receive_quantity_accepts_received_date(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    seed_quantity_product: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    """A picked date drives received_at and the batch_no prefix."""
    product_id, supplier_id, sku = seed_quantity_product
    r = client.post(
        f"{PREFIX}/receipts/quantity",
        headers=superuser_token_headers,
        json=_body(product_id, supplier_id, received_date="2026-07-10"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["batch_no"] == f"20260710-{sku}-001"

    db.expire_all()
    batch = db.get(PartBatch, uuid.UUID(body["id"]))
    assert batch is not None
    assert batch.received_at.date() == date(2026, 7, 10)


def test_receive_quantity_composes_current_clock_time(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    seed_quantity_product: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    """Two same-day receives get DISTINCT timestamps, so FIFO between them
    follows entry order rather than the random uuid tiebreaker."""
    product_id, supplier_id, _ = seed_quantity_product
    stamps = []
    for _i in range(2):
        r = client.post(
            f"{PREFIX}/receipts/quantity",
            headers=superuser_token_headers,
            json=_body(product_id, supplier_id, received_date="2026-07-10"),
        )
        assert r.status_code == 200, r.text
        db.expire_all()
        batch = db.get(PartBatch, uuid.UUID(r.json()["id"]))
        assert batch is not None
        stamps.append(batch.received_at)

    assert stamps[0] != stamps[1]
    assert stamps[0] < stamps[1]
    # Neither collapsed to midnight — that is the tie that would hand FIFO
    # ordering over to the random uuid4 primary key.
    assert stamps[0].timetz().replace(tzinfo=None) != time(0, 0)


def test_receive_quantity_rejects_future_date(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    seed_quantity_product: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    product_id, supplier_id, _ = seed_quantity_product
    future = (date.today() + timedelta(days=5)).isoformat()
    r = client.post(
        f"{PREFIX}/receipts/quantity",
        headers=superuser_token_headers,
        json=_body(product_id, supplier_id, received_date=future),
    )
    assert r.status_code == 422
    assert "future" in r.json()["detail"].lower()


def test_receive_quantity_allows_one_day_timezone_skew(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    seed_quantity_product: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    """Yangon/Bangkok run ahead of UTC, so the client's LOCAL 'today' can be one
    day past the server's UTC today. That must not be rejected."""
    product_id, supplier_id, _ = seed_quantity_product
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    r = client.post(
        f"{PREFIX}/receipts/quantity",
        headers=superuser_token_headers,
        json=_body(product_id, supplier_id, received_date=tomorrow),
    )
    assert r.status_code == 200, r.text


def test_receive_quantity_omitting_received_date_uses_today(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    seed_quantity_product: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    product_id, supplier_id, _sku = seed_quantity_product
    r = client.post(
        f"{PREFIX}/receipts/quantity",
        headers=superuser_token_headers,
        json=_body(product_id, supplier_id),
    )
    assert r.status_code == 200, r.text
    assert r.json()["batch_no"].startswith(date.today().strftime("%Y%m%d"))


def test_receive_quantity_replay_of_a_backdated_receive_succeeds(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    seed_quantity_product: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    """The future-date guard runs BEFORE crud's replay lookup, so a retry must
    still return the stored batch rather than tripping validation. It cannot
    trip: the bound is date.today() + 1 and today never moves backwards, so the
    accepted range only widens — a payload accepted once stays accepted."""
    product_id, supplier_id, _ = seed_quantity_product
    body = _body(product_id, supplier_id, received_date="2026-07-10")

    r1 = client.post(
        f"{PREFIX}/receipts/quantity", headers=superuser_token_headers, json=body
    )
    assert r1.status_code == 200, r1.text
    db.expire_all()
    batches_before = len(db.exec(select(PartBatch)).all())

    r2 = client.post(
        f"{PREFIX}/receipts/quantity", headers=superuser_token_headers, json=body
    )
    assert r2.status_code == 200, r2.text
    assert r1.json()["id"] == r2.json()["id"]
    assert r1.json()["batch_no"] == r2.json()["batch_no"]
    db.expire_all()
    assert len(db.exec(select(PartBatch)).all()) == batches_before
