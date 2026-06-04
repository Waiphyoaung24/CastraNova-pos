import uuid

from fastapi.testclient import TestClient

from app.core.config import settings

PREFIX = settings.API_V1_STR


def _product_body(sku: str, **over: object) -> dict[str, object]:
    body: dict[str, object] = {
        "sku": sku,
        "model_name": "Compressor 100",
        "brand": "Acme",
        "category": "compressor",
        "tracking_mode": "SERIALIZED",
        "retail_price_thb": "1000.00",
        "repair_price_thb": "200.00",
    }
    body.update(over)
    return body


def test_admin_creates_serialized_product(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    sku = f"CMP-{uuid.uuid4().hex[:8]}"
    r = client.post(
        f"{PREFIX}/products/", headers=superuser_token_headers, json=_product_body(sku)
    )
    assert r.status_code == 200
    assert r.json()["sku"] == sku
    assert r.json()["tracking_mode"] == "SERIALIZED"


def test_staff_cannot_create_product(
    client: TestClient, staff_token_headers: dict[str, str]
) -> None:
    r = client.post(
        f"{PREFIX}/products/",
        headers=staff_token_headers,
        json=_product_body(f"X-{uuid.uuid4().hex[:8]}"),
    )
    assert r.status_code == 403


def test_duplicate_sku_rejected(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    sku = f"DUP-{uuid.uuid4().hex[:8]}"
    body = _product_body(sku)
    assert (
        client.post(
            f"{PREFIX}/products/", headers=superuser_token_headers, json=body
        ).status_code
        == 200
    )
    r2 = client.post(f"{PREFIX}/products/", headers=superuser_token_headers, json=body)
    assert r2.status_code == 409


def test_staff_can_read_products(
    client: TestClient, staff_token_headers: dict[str, str]
) -> None:
    assert (
        client.get(f"{PREFIX}/products/", headers=staff_token_headers).status_code
        == 200
    )


def test_price_change_recorded_on_update(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    sku = f"PC-{uuid.uuid4().hex[:8]}"
    created = client.post(
        f"{PREFIX}/products/", headers=superuser_token_headers, json=_product_body(sku)
    )
    pid = created.json()["id"]

    upd = client.patch(
        f"{PREFIX}/products/{pid}",
        headers=superuser_token_headers,
        json={"retail_price_thb": "1500.00"},
    )
    assert upd.status_code == 200
    assert upd.json()["retail_price_thb"] == "1500.00"

    hist = client.get(
        f"{PREFIX}/products/{pid}/price-history", headers=superuser_token_headers
    )
    assert hist.status_code == 200
    rows = hist.json()
    assert len(rows) == 1
    assert rows[0]["field"] == "retail_price_thb"
    assert rows[0]["old_value"] == "1000.00"
    assert rows[0]["new_value"] == "1500.00"


def test_price_history_staff_forbidden(
    client: TestClient,
    staff_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
) -> None:
    sku = f"PH-{uuid.uuid4().hex[:8]}"
    created = client.post(
        f"{PREFIX}/products/", headers=superuser_token_headers, json=_product_body(sku)
    )
    pid = created.json()["id"]
    r = client.get(
        f"{PREFIX}/products/{pid}/price-history", headers=staff_token_headers
    )
    assert r.status_code == 403


def test_price_history_unknown_product_404(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.get(
        f"{PREFIX}/products/{uuid.uuid4()}/price-history",
        headers=superuser_token_headers,
    )
    assert r.status_code == 404
