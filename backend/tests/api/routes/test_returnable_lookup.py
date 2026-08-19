"""GET /sales/returnable — the sale picker's data source."""

import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from tests.api.routes.test_sale_returns import (
    _customer,
    _line_of,
    _part_product,
    _receive,
    _return,
    _seed,
    _sell_parts,
    _sell_unit,
    _serialized_unit,
)

PREFIX = settings.API_V1_STR


def test_barcode_resolves_a_sold_unit_to_its_sale(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _seed(db)
    barcode, _ = _serialized_unit(db)
    sale = _sell_unit(db, barcode=barcode, customer_id=_customer(db))

    r = client.get(
        f"{PREFIX}/sales/returnable",
        headers=superuser_token_headers,
        params={"castranova_barcode": barcode},
    )

    assert r.status_code == 200
    sales = r.json()["sales"]
    assert len(sales) == 1
    assert sales[0]["sale_id"] == str(sale.id)
    line = sales[0]["lines"][0]
    assert line["quantity_sold"] == 1
    assert line["quantity_returned"] == 0
    assert line["quantity_returnable"] == 1


def test_a_fully_returned_unit_disappears_from_the_lookup(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _seed(db)
    barcode, _ = _serialized_unit(db)
    sale = _sell_unit(db, barcode=barcode, customer_id=_customer(db))
    _return(db, sale=sale, sale_line_id=_line_of(db, sale).id, quantity=1)

    r = client.get(
        f"{PREFIX}/sales/returnable",
        headers=superuser_token_headers,
        params={"castranova_barcode": barcode},
    )
    assert r.json()["sales"] == []


def test_sku_lists_recent_sales_with_partial_returnable_counts(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _seed(db)
    product_id, sku = _part_product(db)
    _receive(db, product_id=product_id, qty=10, cost="10.00")
    sale = _sell_parts(db, sku=sku, qty=5, customer_id=_customer(db))
    _return(db, sale=sale, sale_line_id=_line_of(db, sale).id, quantity=2)

    r = client.get(
        f"{PREFIX}/sales/returnable",
        headers=superuser_token_headers,
        params={"sku": sku},
    )

    line = r.json()["sales"][0]["lines"][0]
    assert line["quantity_sold"] == 5
    assert line["quantity_returned"] == 2
    assert line["quantity_returnable"] == 3
    assert Decimal(line["unit_price_thb"]) == Decimal("100.00")


def test_lookup_requires_exactly_one_selector(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    assert (
        client.get(
            f"{PREFIX}/sales/returnable", headers=superuser_token_headers
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"{PREFIX}/sales/returnable",
            headers=superuser_token_headers,
            params={"sku": "A", "castranova_barcode": "B"},
        ).status_code
        == 422
    )


def test_staff_cannot_use_the_lookup(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    r = client.get(
        f"{PREFIX}/sales/returnable",
        headers=normal_user_token_headers,
        params={"sku": f"missing-{uuid.uuid4().hex[:8]}"},
    )
    assert r.status_code == 403
