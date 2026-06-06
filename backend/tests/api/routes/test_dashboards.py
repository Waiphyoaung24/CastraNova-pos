import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    CustomerCreate,
    Location,
    ProductCreate,
    SupplierCreate,
    TrackingMode,
)


def _ensure_locations(db: Session) -> None:
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)


def _seed_quantity_with_batches(
    client: TestClient,
    headers: dict[str, str],
    db: Session,
    qtys: list[int],
    *,
    sku: str | None = None,
    category: str | None = None,
) -> uuid.UUID:
    """Create a QUANTITY product + supplier (admin), then receive one batch per
    qty (staff). Returns the product_id."""
    _ensure_locations(db)
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=sku or f"QTY-{uuid.uuid4().hex[:8]}",
            model_name="Bearing",
            category=category,
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="50.00",
            repair_price_thb="10.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name="Acme Parts", country="TH")
    )
    for qty in qtys:
        r = client.post(
            f"{settings.API_V1_STR}/receipts/quantity",
            headers=headers,
            json={
                "product_id": str(product.id),
                "supplier_id": str(supplier.id),
                "received_qty": qty,
                "purchase_cost_thb": "5.00",
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        assert r.status_code == 200, r.text
    return product.id


def _seed_serialized_units(
    client: TestClient,
    headers: dict[str, str],
    db: Session,
    n: int,
    *,
    sku: str | None = None,
    category: str | None = None,
) -> uuid.UUID:
    """Create a SERIALIZED product + supplier (admin), then receive n units
    (staff). Returns the product_id."""
    _ensure_locations(db)
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=sku or f"SER-{uuid.uuid4().hex[:8]}",
            model_name="Compressor",
            category=category,
            tracking_mode=TrackingMode.SERIALIZED,
            retail_price_thb="1000.00",
            repair_price_thb="200.00",
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name="Acme", country="TH")
    )
    pieces = [
        {"supplier_serial": f"SN-{uuid.uuid4().hex[:8]}", "purchase_cost_thb": "900.00"}
        for _ in range(n)
    ]
    r = client.post(
        f"{settings.API_V1_STR}/receipts/serialized",
        headers=headers,
        json={
            "product_id": str(product.id),
            "supplier_id": str(supplier.id),
            "pieces": pieces,
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 200, r.text
    return product.id


def test_stock_on_hand_sums_quantity_batches(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    qty_sku = f"QTY-{uuid.uuid4().hex[:8]}"
    ser_sku = f"SER-{uuid.uuid4().hex[:8]}"
    _seed_quantity_with_batches(client, staff_token_headers, db, [8, 12], sku=qty_sku)
    _seed_serialized_units(client, staff_token_headers, db, 2, sku=ser_sku)

    r = client.get(
        f"{settings.API_V1_STR}/dashboards/stock-on-hand", headers=staff_token_headers
    )
    assert r.status_code == 200, r.text
    rows = {row["sku"]: row for row in r.json()["rows"]}

    assert rows[qty_sku]["tracking_mode"] == "QUANTITY"
    assert rows[qty_sku]["quantity_on_hand"] == 20
    assert rows[ser_sku]["tracking_mode"] == "SERIALIZED"
    assert rows[ser_sku]["quantity_on_hand"] == 2
    # No cost/COGS leakage in this both-roles view.
    assert "cost" not in str(rows[qty_sku]).lower()


def test_stock_on_hand_filter_by_category(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    comp_sku = f"COMP-{uuid.uuid4().hex[:8]}"
    fan_sku = f"FAN-{uuid.uuid4().hex[:8]}"
    _seed_quantity_with_batches(
        client, staff_token_headers, db, [5], sku=comp_sku, category="compressor"
    )
    _seed_quantity_with_batches(
        client, staff_token_headers, db, [5], sku=fan_sku, category="fan"
    )

    r = client.get(
        f"{settings.API_V1_STR}/dashboards/stock-on-hand",
        headers=staff_token_headers,
        params={"category": "compressor"},
    )
    assert r.status_code == 200, r.text
    skus = {row["sku"] for row in r.json()["rows"]}
    assert comp_sku in skus
    assert fan_sku not in skus


def test_stock_on_hand_filter_by_customer(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    # Two QUANTITY products; the customer buys a small qty of only the first,
    # leaving stock on hand. The customer= filter must return only the product
    # that customer transacted, excluding the untouched one.
    bought_sku = f"BUY-{uuid.uuid4().hex[:8]}"
    other_sku = f"OTHER-{uuid.uuid4().hex[:8]}"
    _seed_quantity_with_batches(client, staff_token_headers, db, [10], sku=bought_sku)
    _seed_quantity_with_batches(client, staff_token_headers, db, [10], sku=other_sku)
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Filtered Customer")
    )

    sale = client.post(
        f"{settings.API_V1_STR}/sales",
        headers=staff_token_headers,
        json={
            "customer_id": str(customer.id),
            "lines": [{"line_kind": "PART", "sku": bought_sku, "quantity": 2}],
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    assert sale.status_code == 200, sale.text

    r = client.get(
        f"{settings.API_V1_STR}/dashboards/stock-on-hand",
        headers=staff_token_headers,
        params={"customer": str(customer.id)},
    )
    assert r.status_code == 200, r.text
    skus = {row["sku"] for row in r.json()["rows"]}
    assert bought_sku in skus
    assert other_sku not in skus


def test_stock_on_hand_filter_by_supplier_quantity(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    # One QUANTITY product receiving qty 10 from supplier A and qty 5 from
    # supplier B. No filter -> on-hand 15; ?supplier=A -> 10; ?supplier=B -> 5.
    _ensure_locations(db)
    sku = f"QTY-{uuid.uuid4().hex[:8]}"
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=sku,
            model_name="Bearing",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="50.00",
            repair_price_thb="10.00",
        ),
    )
    supplier_a = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name="Supplier A", country="TH")
    )
    supplier_b = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name="Supplier B", country="TH")
    )
    for supplier_id, qty in ((supplier_a.id, 10), (supplier_b.id, 5)):
        r = client.post(
            f"{settings.API_V1_STR}/receipts/quantity",
            headers=staff_token_headers,
            json={
                "product_id": str(product.id),
                "supplier_id": str(supplier_id),
                "received_qty": qty,
                "purchase_cost_thb": "5.00",
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        assert r.status_code == 200, r.text

    def _qoh(params: dict[str, str]) -> int:
        resp = client.get(
            f"{settings.API_V1_STR}/dashboards/stock-on-hand",
            headers=staff_token_headers,
            params=params,
        )
        assert resp.status_code == 200, resp.text
        rows = {row["sku"]: row for row in resp.json()["rows"]}
        return int(rows[sku]["quantity_on_hand"])

    assert _qoh({}) == 15
    assert _qoh({"supplier": str(supplier_a.id)}) == 10
    assert _qoh({"supplier": str(supplier_b.id)}) == 5


def test_stock_on_hand_filter_by_supplier_serialized(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    # One SERIALIZED product receiving 3 units from supplier A and 2 from
    # supplier B. No filter -> in-stock count 5; ?supplier=A -> 3; ?supplier=B -> 2.
    _ensure_locations(db)
    sku = f"SER-{uuid.uuid4().hex[:8]}"
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=sku,
            model_name="Compressor",
            tracking_mode=TrackingMode.SERIALIZED,
            retail_price_thb="1000.00",
            repair_price_thb="200.00",
        ),
    )
    supplier_a = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name="Ser Supplier A", country="TH")
    )
    supplier_b = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name="Ser Supplier B", country="TH")
    )
    for supplier_id, n in ((supplier_a.id, 3), (supplier_b.id, 2)):
        pieces = [
            {
                "supplier_serial": f"SN-{uuid.uuid4().hex[:8]}",
                "purchase_cost_thb": "900.00",
            }
            for _ in range(n)
        ]
        r = client.post(
            f"{settings.API_V1_STR}/receipts/serialized",
            headers=staff_token_headers,
            json={
                "product_id": str(product.id),
                "supplier_id": str(supplier_id),
                "pieces": pieces,
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        assert r.status_code == 200, r.text

    def _count(params: dict[str, str]) -> int:
        resp = client.get(
            f"{settings.API_V1_STR}/dashboards/stock-on-hand",
            headers=staff_token_headers,
            params=params,
        )
        assert resp.status_code == 200, resp.text
        rows = {row["sku"]: row for row in resp.json()["rows"]}
        return int(rows[sku]["quantity_on_hand"])

    assert _count({}) == 5
    assert _count({"supplier": str(supplier_a.id)}) == 3
    assert _count({"supplier": str(supplier_b.id)}) == 2


def test_stock_on_hand_requires_auth(client: TestClient) -> None:
    r = client.get(f"{settings.API_V1_STR}/dashboards/stock-on-hand")
    assert r.status_code == 401


def test_batch_drilldown_lists_active_batches(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    product_id = _seed_quantity_with_batches(
        client, staff_token_headers, db, [8, 12]
    )
    r = client.get(
        f"{settings.API_V1_STR}/dashboards/stock-on-hand/{product_id}/batches",
        headers=staff_token_headers,
    )
    assert r.status_code == 200, r.text
    remaining = [b["remaining_qty"] for b in r.json()]
    assert remaining == [8, 12]


def test_stock_on_hand_is_single_pass_not_n_plus_one(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    for i in range(50):
        _seed_quantity_with_batches(
            client, staff_token_headers, db, [5], sku=f"PERF-{i:03d}"
        )
    from sqlalchemy import event

    from app.core.db import engine

    counter = {"n": 0}

    def _count(*_args: object, **_kwargs: object) -> None:
        counter["n"] += 1

    event.listen(engine, "before_cursor_execute", _count)
    try:
        r = client.get(
            f"{settings.API_V1_STR}/dashboards/stock-on-hand",
            headers=staff_token_headers,
        )
    finally:
        event.remove(engine, "before_cursor_execute", _count)
    assert r.status_code == 200
    assert len(r.json()["rows"]) >= 50
    assert counter["n"] < 15
