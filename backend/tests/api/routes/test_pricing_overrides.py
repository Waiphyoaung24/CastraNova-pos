import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.models import ProductCreate, TrackingMode, UserRole
from tests.utils.user import authentication_token_from_email_with_role


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


def test_get_pricing_override_as_creator(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    pid = _seed_product(db)
    created = client.post(
        "/api/v1/pricing-overrides",
        headers=staff_token_headers,
        json=_create_payload(pid, "970.00"),  # 3% -> AUTO_APPROVED
    ).json()
    r = client.get(
        f"/api/v1/pricing-overrides/{created['id']}", headers=staff_token_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == created["id"]
    assert body["state"] == "AUTO_APPROVED"
    assert body["product_sku"].startswith("OVRAPI-")


def test_get_pricing_override_as_admin(
    client: TestClient,
    staff_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
    bkk_admin_token_headers: dict[str, str],
    db: Session,
) -> None:
    pid = _seed_product(db)
    created = client.post(
        "/api/v1/pricing-overrides",
        headers=staff_token_headers,
        json=_create_payload(pid, "900.00"),  # 10% -> PENDING
    ).json()
    r = client.get(
        f"/api/v1/pricing-overrides/{created['id']}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "PENDING"

    r = client.get(
        f"/api/v1/pricing-overrides/{created['id']}",
        headers=bkk_admin_token_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "PENDING"


def test_get_pricing_override_other_user_forbidden(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    pid = _seed_product(db)
    created = client.post(
        "/api/v1/pricing-overrides",
        headers=staff_token_headers,
        json=_create_payload(pid, "970.00"),
    ).json()
    other_staff = authentication_token_from_email_with_role(
        client=client, email="staff2@example.com", db=db, role=UserRole.YGN_STAFF
    )
    r = client.get(
        f"/api/v1/pricing-overrides/{created['id']}", headers=other_staff
    )
    assert r.status_code == 403


def test_get_pricing_override_not_found(
    client: TestClient, staff_token_headers: dict[str, str]
) -> None:
    r = client.get(
        f"/api/v1/pricing-overrides/{uuid.uuid4()}", headers=staff_token_headers
    )
    assert r.status_code == 404
