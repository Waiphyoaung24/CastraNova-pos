import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.models import ProductCreate, TrackingMode


def _seed_product(db: Session) -> uuid.UUID:
    crud.set_setting(session=db, key=crud.OVERRIDE_THRESHOLD_KEY, value=5.0)
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"OVRAPI-{uuid.uuid4().hex[:8]}",
            model_name="Override API Test",
            brand="Acme",
            category="compressor",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb=Decimal("1000.00"),
            repair_price_thb=Decimal("300.00"),
        ),
    )
    return product.id


def _create_payload(pid: uuid.UUID, price: str) -> dict[str, object]:
    return {
        "target_kind": "SALE_LINE",
        "product_id": str(pid),
        "requested_price_thb": price,
        "reason": "loyal customer",
    }


def test_staff_can_create_override(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    pid = _seed_product(db)
    r = client.post(
        "/api/v1/pricing-overrides",
        headers=staff_token_headers,
        json=_create_payload(pid, "970.00"),  # 3% -> AUTO_APPROVED
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "AUTO_APPROVED"


def test_admin_can_create_override(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    pid = _seed_product(db)
    r = client.post(
        "/api/v1/pricing-overrides",
        headers=superuser_token_headers,
        json=_create_payload(pid, "900.00"),  # 10% -> PENDING
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "PENDING"


def test_list_overrides_is_admin_only(
    client: TestClient,
    staff_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
) -> None:
    assert (
        client.get(
            "/api/v1/pricing-overrides?state=PENDING", headers=staff_token_headers
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/api/v1/pricing-overrides?state=PENDING",
            headers=superuser_token_headers,
        ).status_code
        == 200
    )


def test_staff_cannot_decide(
    client: TestClient,
    staff_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    pid = _seed_product(db)
    created = client.post(
        "/api/v1/pricing-overrides",
        headers=superuser_token_headers,
        json=_create_payload(pid, "700.00"),  # 30% -> PENDING
    ).json()
    r = client.post(
        f"/api/v1/pricing-overrides/{created['id']}/decide",
        headers=staff_token_headers,
        json={"decision": "APPROVED"},
    )
    assert r.status_code == 403


def test_admin_decides_pending_override(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    pid = _seed_product(db)
    created = client.post(
        "/api/v1/pricing-overrides",
        headers=superuser_token_headers,
        json=_create_payload(pid, "700.00"),  # 30% -> PENDING
    ).json()
    assert created["state"] == "PENDING"
    r = client.post(
        f"/api/v1/pricing-overrides/{created['id']}/decide",
        headers=superuser_token_headers,
        json={"decision": "APPROVED"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "APPROVED"
    assert body["decided_at"] is not None


def test_override_exceptions_report_admin_only(
    client: TestClient,
    staff_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    from datetime import datetime, timezone

    pid = _seed_product(db)
    client.post(
        "/api/v1/pricing-overrides",
        headers=superuser_token_headers,
        json=_create_payload(pid, "900.00"),  # PENDING
    )
    now = datetime.now(timezone.utc)
    month = f"{now.year:04d}-{now.month:02d}"
    url = f"/api/v1/reports/override-exceptions?month={month}"

    assert client.get(url, headers=staff_token_headers).status_code == 403
    r = client.get(url, headers=superuser_token_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["month"] == month
    assert body["total"] == len(body["rows"])
    assert body["pending"] >= 1
