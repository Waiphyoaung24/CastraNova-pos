import re
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


def _page_count(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page(?!s)", pdf))


def _create_quantity_product(
    client: TestClient, headers: dict[str, str]
) -> dict[str, object]:
    sku = f"QTY-{uuid.uuid4().hex[:8]}"
    r = client.post(
        f"{PREFIX}/products/",
        headers=headers,
        json=_product_body(sku, tracking_mode="QUANTITY"),
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_sku_label_pdf_for_quantity_product(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    p = _create_quantity_product(client, superuser_token_headers)
    r = client.get(
        f"{PREFIX}/products/{p['id']}/label.pdf?qty=4",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"
    assert _page_count(r.content) == 4


def test_sku_label_defaults_to_one_page(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    p = _create_quantity_product(client, superuser_token_headers)
    r = client.get(
        f"{PREFIX}/products/{p['id']}/label.pdf", headers=superuser_token_headers
    )
    assert r.status_code == 200
    assert _page_count(r.content) == 1


def test_sku_label_404_for_missing_product(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.get(
        f"{PREFIX}/products/{uuid.uuid4()}/label.pdf",
        headers=superuser_token_headers,
    )
    assert r.status_code == 404


def test_sku_label_400_for_serialized_product(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    sku = f"SER-{uuid.uuid4().hex[:8]}"
    p = client.post(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        json=_product_body(sku, tracking_mode="SERIALIZED"),
    ).json()
    r = client.get(
        f"{PREFIX}/products/{p['id']}/label.pdf", headers=superuser_token_headers
    )
    assert r.status_code == 400


def test_sku_label_qty_out_of_range_422(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    p = _create_quantity_product(client, superuser_token_headers)
    assert (
        client.get(
            f"{PREFIX}/products/{p['id']}/label.pdf?qty=0",
            headers=superuser_token_headers,
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"{PREFIX}/products/{p['id']}/label.pdf?qty=1001",
            headers=superuser_token_headers,
        ).status_code
        == 422
    )


def test_sku_label_requires_auth(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    p = _create_quantity_product(client, superuser_token_headers)
    r = client.get(f"{PREFIX}/products/{p['id']}/label.pdf")
    assert r.status_code == 401


def test_staff_can_fetch_sku_label(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
) -> None:
    p = _create_quantity_product(client, superuser_token_headers)
    r = client.get(
        f"{PREFIX}/products/{p['id']}/label.pdf", headers=staff_token_headers
    )
    assert r.status_code == 200


def test_read_options_returns_all_ascending_by_sku(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    sku_z = f"ZZZ-{uuid.uuid4().hex[:8]}"
    sku_a = f"AAA-{uuid.uuid4().hex[:8]}"
    for sku in (sku_z, sku_a):
        r = client.post(
            f"{PREFIX}/products/",
            headers=superuser_token_headers,
            json=_product_body(sku),
        )
        assert r.status_code == 200, r.text

    r = client.get(f"{PREFIX}/products/options", headers=superuser_token_headers)
    assert r.status_code == 200
    options = r.json()
    skus = [o["sku"] for o in options]
    assert sku_a in skus
    assert sku_z in skus
    # Relative order only — see test_products.py history for why a full
    # sorted() equality check is collation-fragile across a shared test DB.
    assert skus.index(sku_a) < skus.index(sku_z)


def test_read_options_payload_shape(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    sku = f"OPT-{uuid.uuid4().hex[:8]}"
    created = client.post(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        json=_product_body(sku, retail_price_thb="1234.50", repair_price_thb="99.00"),
    )
    assert created.status_code == 200, created.text
    pid = created.json()["id"]

    r = client.get(f"{PREFIX}/products/options", headers=superuser_token_headers)
    assert r.status_code == 200
    match = next(o for o in r.json() if o["id"] == pid)
    assert match["sku"] == sku
    assert match["model_name"] == "Compressor 100"
    assert match["tracking_mode"] == "SERIALIZED"
    assert match["retail_price_thb"] == "1234.50"
    assert match["repair_price_thb"] == "99.00"
    assert "specs" not in match
    assert "brand" not in match
    assert "category" not in match


def test_staff_can_read_options(
    client: TestClient, staff_token_headers: dict[str, str]
) -> None:
    r = client.get(f"{PREFIX}/products/options", headers=staff_token_headers)
    assert r.status_code == 200


def test_read_options_includes_inactive_product(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    sku = f"INACT-{uuid.uuid4().hex[:8]}"
    created = client.post(
        f"{PREFIX}/products/", headers=superuser_token_headers, json=_product_body(sku)
    )
    assert created.status_code == 200, created.text
    pid = created.json()["id"]
    upd = client.patch(
        f"{PREFIX}/products/{pid}",
        headers=superuser_token_headers,
        json={"is_active": False},
    )
    assert upd.status_code == 200
    assert upd.json()["is_active"] is False

    r = client.get(f"{PREFIX}/products/options", headers=superuser_token_headers)
    assert r.status_code == 200
    assert sku in [o["sku"] for o in r.json()]


def test_read_options_requires_auth(client: TestClient) -> None:
    r = client.get(f"{PREFIX}/products/options")
    assert r.status_code == 401
