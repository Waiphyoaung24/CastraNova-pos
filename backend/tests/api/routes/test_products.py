import re
import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.models import OverrideTargetKind, PricingOverrideCreate, SupplierCreate

PREFIX = settings.API_V1_STR


def _receive_quantity(db: Session, product_id: str) -> None:
    """Give a product one QUANTITY receipt (a PartBatch) so it is no longer
    'fresh' — used to assert the SKU edit lock and the is_fresh flag."""
    admin = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert admin is not None
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"Sup-{uuid.uuid4().hex[:6]}")
    )
    crud.receive_quantity(
        session=db,
        product_id=uuid.UUID(product_id),
        supplier_id=supplier.id,
        received_qty=3,
        purchase_cost_thb=Decimal("10.00"),
        idempotency_key=uuid.uuid4(),
        received_by_user_id=admin.id,
    )


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


def test_read_products_filters_by_is_active(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    active_sku = f"ACT-{uuid.uuid4().hex[:8]}"
    inactive_sku = f"INA-{uuid.uuid4().hex[:8]}"
    client.post(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        json=_product_body(active_sku),
    )
    created = client.post(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        json=_product_body(inactive_sku),
    ).json()
    client.patch(
        f"{PREFIX}/products/{created['id']}",
        headers=superuser_token_headers,
        json={"is_active": False},
    )

    active_only = client.get(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        params={"is_active": True, "q": active_sku},
    )
    assert active_only.status_code == 200
    assert [p["sku"] for p in active_only.json()["data"]] == [active_sku]

    inactive_only = client.get(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        params={"is_active": False, "q": inactive_sku},
    )
    assert inactive_only.status_code == 200
    assert [p["sku"] for p in inactive_only.json()["data"]] == [inactive_sku]


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
    assert rows[0]["changed_by_full_name"] == settings.FIRST_SUPERUSER


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


def test_update_sku_on_fresh_product_succeeds(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    sku = f"FRESH-{uuid.uuid4().hex[:8]}"
    created = client.post(
        f"{PREFIX}/products/", headers=superuser_token_headers, json=_product_body(sku)
    ).json()
    new_sku = f"RENAMED-{uuid.uuid4().hex[:8]}"
    r = client.patch(
        f"{PREFIX}/products/{created['id']}",
        headers=superuser_token_headers,
        json={"sku": new_sku},
    )
    assert r.status_code == 200, r.text
    assert r.json()["sku"] == new_sku
    # Renaming did not add stock, so the product stays fresh.
    assert r.json()["is_fresh"] is True


def test_update_sku_blocked_after_receive(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    sku = f"USED-{uuid.uuid4().hex[:8]}"
    created = client.post(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        json=_product_body(sku, tracking_mode="QUANTITY"),
    ).json()
    _receive_quantity(db, created["id"])

    r = client.patch(
        f"{PREFIX}/products/{created['id']}",
        headers=superuser_token_headers,
        json={"sku": f"NOPE-{uuid.uuid4().hex[:8]}"},
    )
    assert r.status_code == 409, r.text
    # Non-SKU fields still update on a used product.
    ok = client.patch(
        f"{PREFIX}/products/{created['id']}",
        headers=superuser_token_headers,
        json={"model_name": "Renamed model"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["model_name"] == "Renamed model"


def test_update_duplicate_sku_returns_409(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    taken = f"TAKEN-{uuid.uuid4().hex[:8]}"
    client.post(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        json=_product_body(taken),
    )
    other = client.post(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        json=_product_body(f"OTHER-{uuid.uuid4().hex[:8]}"),
    ).json()

    r = client.patch(
        f"{PREFIX}/products/{other['id']}",
        headers=superuser_token_headers,
        json={"sku": taken},
    )
    assert r.status_code == 409, r.text


def test_products_list_is_fresh_flag(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    sku = f"FLAG-{uuid.uuid4().hex[:8]}"
    created = client.post(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        json=_product_body(sku, tracking_mode="QUANTITY"),
    ).json()

    def _row() -> dict[str, object]:
        listing = client.get(
            f"{PREFIX}/products/",
            headers=superuser_token_headers,
            params={"q": sku},
        ).json()
        return next(p for p in listing["data"] if p["id"] == created["id"])

    assert _row()["is_fresh"] is True
    _receive_quantity(db, created["id"])
    assert _row()["is_fresh"] is False


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


def _create_product(
    client: TestClient, headers: dict[str, str], **over: object
) -> dict[str, object]:
    """Create one product via the API and return its JSON body."""
    sku = f"DEL-{uuid.uuid4().hex[:8]}"
    r = client.post(
        f"{PREFIX}/products/", headers=headers, json=_product_body(sku, **over)
    )
    assert r.status_code == 200, r.text
    return dict(r.json())


def test_superuser_deletes_fresh_product(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    product = _create_product(client, superuser_token_headers)
    product_id = product["id"]

    r = client.delete(
        f"{PREFIX}/products/{product_id}", headers=superuser_token_headers
    )
    assert r.status_code == 204, r.text

    listed = client.get(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        params={"q": product["sku"]},
    )
    assert listed.status_code == 200
    assert listed.json()["data"] == []


def test_cannot_delete_product_with_price_history(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """pricechange is an append-only ledger (m021's reject_ledger_mutation), so
    a re-priced product can never be deleted — only deactivated."""
    product = _create_product(client, superuser_token_headers)
    product_id = product["id"]
    patched = client.patch(
        f"{PREFIX}/products/{product_id}",
        headers=superuser_token_headers,
        json={"retail_price_thb": "1500.00"},
    )
    assert patched.status_code == 200, patched.text
    history = client.get(
        f"{PREFIX}/products/{product_id}/price-history",
        headers=superuser_token_headers,
    )
    assert len(history.json()) >= 1

    r = client.delete(
        f"{PREFIX}/products/{product_id}", headers=superuser_token_headers
    )
    assert r.status_code == 409, r.text
    assert "price history" in r.json()["detail"].lower()

    still_there = client.get(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        params={"q": product["sku"]},
    )
    assert still_there.json()["count"] == 1


def test_cannot_delete_product_with_stock(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    # _receive_quantity needs a QUANTITY product; the default body is SERIALIZED.
    product = _create_product(
        client, superuser_token_headers, tracking_mode="QUANTITY"
    )
    product_id = str(product["id"])
    _receive_quantity(db, product_id)

    r = client.delete(
        f"{PREFIX}/products/{product_id}", headers=superuser_token_headers
    )
    assert r.status_code == 409, r.text
    assert "history" in r.json()["detail"].lower()

    listed = client.get(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        params={"q": product["sku"]},
    )
    assert listed.json()["count"] == 1


def test_bkk_admin_cannot_delete_product(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    bkk_admin_token_headers: dict[str, str],
) -> None:
    product = _create_product(client, superuser_token_headers)

    r = client.delete(
        f"{PREFIX}/products/{product['id']}", headers=bkk_admin_token_headers
    )
    assert r.status_code == 403, r.text


def test_staff_cannot_delete_product(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
) -> None:
    product = _create_product(client, superuser_token_headers)

    r = client.delete(
        f"{PREFIX}/products/{product['id']}", headers=staff_token_headers
    )
    assert r.status_code == 403, r.text


def test_cannot_delete_product_referenced_by_override_request(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """A PricingOverrideRequest can exist without any stock or re-price, so it
    passes both explicit gates and is caught only by the IntegrityError
    backstop in crud.delete_product. That path must 409, never 500."""
    product = _create_product(client, superuser_token_headers)
    product_id = uuid.UUID(str(product["id"]))
    admin = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert admin is not None
    crud.create_pricing_override(
        session=db,
        override_in=PricingOverrideCreate(
            target_kind=OverrideTargetKind.SALE_LINE,
            product_id=product_id,
            requested_price_thb=Decimal("900.00"),
            reason="probe",
        ),
        created_by_user_id=admin.id,
    )

    r = client.delete(
        f"{PREFIX}/products/{product_id}", headers=superuser_token_headers
    )
    assert r.status_code == 409, r.text
    assert "referenced" in r.json()["detail"].lower()


def test_delete_unknown_product_404(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.delete(
        f"{PREFIX}/products/{uuid.uuid4()}", headers=superuser_token_headers
    )
    assert r.status_code == 404, r.text
