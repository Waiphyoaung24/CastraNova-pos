import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
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
    admin_headers: dict[str, str] | None = None,
) -> uuid.UUID:
    """Create a QUANTITY product + supplier (admin), then receive one batch per
    qty (admin). Returns the product_id."""
    _ensure_locations(db)
    receive_headers = admin_headers if admin_headers is not None else headers
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
            headers=receive_headers,
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
    admin_headers: dict[str, str] | None = None,
) -> uuid.UUID:
    """Create a SERIALIZED product + supplier (admin), then receive n units
    (admin). Returns the product_id."""
    _ensure_locations(db)
    receive_headers = admin_headers if admin_headers is not None else headers
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
        headers=receive_headers,
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
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
) -> None:
    qty_sku = f"QTY-{uuid.uuid4().hex[:8]}"
    ser_sku = f"SER-{uuid.uuid4().hex[:8]}"
    _seed_quantity_with_batches(
        client, staff_token_headers, db, [8, 12], sku=qty_sku, admin_headers=superuser_token_headers
    )
    _seed_serialized_units(
        client, staff_token_headers, db, 2, sku=ser_sku, admin_headers=superuser_token_headers
    )

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
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
) -> None:
    comp_sku = f"COMP-{uuid.uuid4().hex[:8]}"
    fan_sku = f"FAN-{uuid.uuid4().hex[:8]}"
    _seed_quantity_with_batches(
        client, staff_token_headers, db, [5], sku=comp_sku, category="compressor",
        admin_headers=superuser_token_headers,
    )
    _seed_quantity_with_batches(
        client, staff_token_headers, db, [5], sku=fan_sku, category="fan",
        admin_headers=superuser_token_headers,
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


def test_stock_on_hand_server_filters_paginate_with_filtered_count(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
) -> None:
    tag = uuid.uuid4().hex[:8]
    matching_skus = [f"SOH-{tag}-A", f"SOH-{tag}-B"]
    for sku in matching_skus:
        crud.create_product(
            session=db,
            product_in=ProductCreate(
                sku=sku,
                model_name=f"Filter model {tag}",
                brand=f"Brand-{tag}",
                category=f"Category-{tag}",
                tracking_mode=TrackingMode.QUANTITY,
                retail_price_thb="50.00",
                repair_price_thb="10.00",
            ),
        )
    crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"SOH-{tag}-OTHER",
            model_name=f"Filter model {tag}",
            brand="Other brand",
            category=f"Category-{tag}",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="50.00",
            repair_price_thb="10.00",
        ),
    )

    first = client.get(
        f"{settings.API_V1_STR}/dashboards/stock-on-hand",
        headers=staff_token_headers,
        params={
            "q": tag.upper(),
            "brand": f"Brand-{tag}",
            "category": f"Category-{tag}",
            "skip": 0,
            "limit": 1,
        },
    )
    assert first.status_code == 200, first.text
    assert first.json()["count"] == 2
    assert [row["sku"] for row in first.json()["rows"]] == [matching_skus[0]]

    second = client.get(
        f"{settings.API_V1_STR}/dashboards/stock-on-hand",
        headers=staff_token_headers,
        params={
            "q": tag,
            "brand": f"Brand-{tag}",
            "category": f"Category-{tag}",
            "skip": 1,
            "limit": 1,
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["count"] == 2
    assert [row["sku"] for row in second.json()["rows"]] == [matching_skus[1]]


def test_stock_on_hand_filter_by_supplier_quantity(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
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
            headers=superuser_token_headers,
            json={
                "product_id": str(product.id),
                "supplier_id": str(supplier_id),
                "received_qty": qty,
                "purchase_cost_thb": "5.00",
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        assert r.status_code == 200, r.text

    unmatched_sku = f"QTY-OTHER-{uuid.uuid4().hex[:8]}"
    _seed_quantity_with_batches(
        client,
        staff_token_headers,
        db,
        [7],
        sku=unmatched_sku,
        admin_headers=superuser_token_headers,
    )

    def _rows(params: dict[str, str]) -> dict[str, dict[str, object]]:
        resp = client.get(
            f"{settings.API_V1_STR}/dashboards/stock-on-hand",
            headers=superuser_token_headers,
            params=params,
        )
        assert resp.status_code == 200, resp.text
        return {row["sku"]: row for row in resp.json()["rows"]}

    assert int(_rows({})[sku]["quantity_on_hand"]) == 15
    supplier_a_rows = _rows({"supplier": str(supplier_a.id)})
    assert int(supplier_a_rows[sku]["quantity_on_hand"]) == 10
    assert unmatched_sku not in supplier_a_rows
    assert int(_rows({"supplier": str(supplier_b.id)})[sku]["quantity_on_hand"]) == 5


def test_stock_on_hand_filter_by_supplier_serialized(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
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
            headers=superuser_token_headers,
            json={
                "product_id": str(product.id),
                "supplier_id": str(supplier_id),
                "pieces": pieces,
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        assert r.status_code == 200, r.text

    unmatched_sku = f"SER-OTHER-{uuid.uuid4().hex[:8]}"
    _seed_serialized_units(
        client,
        staff_token_headers,
        db,
        1,
        sku=unmatched_sku,
        admin_headers=superuser_token_headers,
    )

    def _rows(params: dict[str, str]) -> dict[str, dict[str, object]]:
        resp = client.get(
            f"{settings.API_V1_STR}/dashboards/stock-on-hand",
            headers=superuser_token_headers,
            params=params,
        )
        assert resp.status_code == 200, resp.text
        return {row["sku"]: row for row in resp.json()["rows"]}

    assert int(_rows({})[sku]["quantity_on_hand"]) == 5
    supplier_a_rows = _rows({"supplier": str(supplier_a.id)})
    assert int(supplier_a_rows[sku]["quantity_on_hand"]) == 3
    assert unmatched_sku not in supplier_a_rows
    assert int(_rows({"supplier": str(supplier_b.id)})[sku]["quantity_on_hand"]) == 2


def test_stock_on_hand_requires_auth(client: TestClient) -> None:
    r = client.get(f"{settings.API_V1_STR}/dashboards/stock-on-hand")
    assert r.status_code == 401


def test_batch_drilldown_lists_active_batches(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
) -> None:
    product_id = _seed_quantity_with_batches(
        client, staff_token_headers, db, [8, 12], admin_headers=superuser_token_headers
    )
    r = client.get(
        f"{settings.API_V1_STR}/dashboards/stock-on-hand/{product_id}/batches",
        headers=staff_token_headers,
    )
    assert r.status_code == 200, r.text
    remaining = [b["remaining_qty"] for b in r.json()]
    assert remaining == [8, 12]
    assert {b["supplier"] for b in r.json()} == {None}

    admin = client.get(
        f"{settings.API_V1_STR}/dashboards/stock-on-hand/{product_id}/batches",
        headers=superuser_token_headers,
    )
    assert admin.status_code == 200, admin.text
    assert {b["supplier"] for b in admin.json()} == {"Acme Parts"}


def test_unit_drilldown_exposes_id_usable_for_label(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
) -> None:
    """The serialized-unit drill-down must carry each unit's id so the Stock
    screen can reprint the QR label (FR-005 lost-label reprint). The id must
    resolve to a real unit the label endpoint accepts — proving the whole
    Stock → reprint chain, not just the field's presence."""
    product_id = _seed_serialized_units(
        client, staff_token_headers, db, 2, admin_headers=superuser_token_headers
    )
    r = client.get(
        f"{settings.API_V1_STR}/dashboards/stock-on-hand/{product_id}/units",
        headers=staff_token_headers,
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 2
    assert {row["supplier"] for row in rows} == {None}
    for row in rows:
        unit_id = uuid.UUID(row["id"])  # well-formed UUID
        label = client.get(
            f"{settings.API_V1_STR}/receipts/serialized/{unit_id}/label.pdf",
            headers=staff_token_headers,
        )
        assert label.status_code == 200, label.text
        assert label.content[:4] == b"%PDF"

    admin = client.get(
        f"{settings.API_V1_STR}/dashboards/stock-on-hand/{product_id}/units",
        headers=superuser_token_headers,
    )
    assert admin.status_code == 200, admin.text
    assert {row["supplier"] for row in admin.json()} == {"Acme"}


def test_stock_on_hand_includes_brand(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
) -> None:
    branded_sku = f"BRAND-{uuid.uuid4().hex[:8]}"
    crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=branded_sku,
            model_name="Bearing",
            brand="Acme",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="50.00",
            repair_price_thb="10.00",
        ),
    )
    r = client.get(
        f"{settings.API_V1_STR}/dashboards/stock-on-hand",
        headers=staff_token_headers,
    )
    assert r.status_code == 200, r.text
    rows = {row["sku"]: row for row in r.json()["rows"]}
    assert rows[branded_sku]["brand"] == "Acme"


def test_stock_on_hand_is_single_pass_not_n_plus_one(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
) -> None:
    for i in range(50):
        _seed_quantity_with_batches(
            client, staff_token_headers, db, [5], sku=f"PERF-{i:03d}",
            admin_headers=superuser_token_headers,
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


def test_supplier_filter_is_admin_only(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    bkk_admin_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
) -> None:
    supplier = crud.create_supplier(
        session=db,
        supplier_in=SupplierCreate(
            name=f"Gate Supplier {uuid.uuid4().hex[:8]}", country="TH"
        ),
    )
    params = {"supplier": str(supplier.id)}

    staff = client.get(
        f"{settings.API_V1_STR}/dashboards/stock-on-hand",
        headers=staff_token_headers,
        params=params,
    )
    assert staff.status_code == 403, staff.text
    assert "admin-only" in staff.json()["detail"].lower()

    for headers in (superuser_token_headers, bkk_admin_token_headers):
        admin = client.get(
            f"{settings.API_V1_STR}/dashboards/stock-on-hand",
            headers=headers,
            params=params,
        )
        assert admin.status_code == 200, admin.text


def test_stock_on_hand_pagination_bounds(
    client: TestClient,
    staff_token_headers: dict[str, str],
) -> None:
    for params in (
        {"skip": -1},
        {"skip": 10_001},
        {"limit": 0},
        {"limit": 501},
    ):
        response = client.get(
            f"{settings.API_V1_STR}/dashboards/stock-on-hand",
            headers=staff_token_headers,
            params=params,
        )
        assert response.status_code == 422, (params, response.text)


def test_stock_on_hand_without_supplier_filter_stays_open_to_staff(
    client: TestClient,
    staff_token_headers: dict[str, str],
) -> None:
    """The admin gate must not regress the plain staff stock view."""
    r = client.get(
        f"{settings.API_V1_STR}/dashboards/stock-on-hand",
        headers=staff_token_headers,
    )
    assert r.status_code == 200, r.text
