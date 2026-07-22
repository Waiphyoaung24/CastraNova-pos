import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import delete
from sqlmodel import Session, col

from app import crud
from app.core.config import settings
from app.core.limiter import limiter
from app.models import ProductCreate, SyncReviewItem, TrackingMode
from tests.conftest import admin_engine


@pytest.fixture
def rate_limit_on():
    limiter.reset()
    limiter.enabled = True
    yield
    limiter.enabled = False
    limiter.reset()


def test_sixth_login_attempt_is_rate_limited(
    client: TestClient,
    rate_limit_on: None,  # noqa: ARG001 — side-effect fixture; enables rate limiting
) -> None:
    url = f"{settings.API_V1_STR}/login/access-token"
    data = {"username": "nobody@example.com", "password": "wrongpass"}

    codes = [client.post(url, data=data).status_code for _ in range(5)]
    assert all(c == 400 for c in codes)

    r6 = client.post(url, data=data)
    assert r6.status_code == 429
    assert "Rate limit" in r6.json().get("error", "")


def test_refresh_is_rate_limited_above_the_cap(
    client: TestClient,
    rate_limit_on: None,  # noqa: ARG001 — side-effect fixture; enables rate limiting
) -> None:
    """Refresh-token endpoint is rate limited (hardening spec §4.1.4)."""
    client.cookies.clear()  # no refresh cookie -> 401s, which still count
    url = f"{settings.API_V1_STR}/login/refresh-token"

    codes = [client.post(url).status_code for _ in range(60)]
    assert all(c == 401 for c in codes)

    r61 = client.post(url)
    assert r61.status_code == 429
    assert "Rate limit" in r61.json().get("error", "")


def test_twenty_first_logout_is_rate_limited(
    client: TestClient,
    rate_limit_on: None,  # noqa: ARG001 — side-effect fixture; enables rate limiting
) -> None:
    """Logout endpoint is rate limited (hardening spec §4.1.4)."""
    url = f"{settings.API_V1_STR}/login/logout"

    codes = [client.post(url).status_code for _ in range(20)]
    assert all(c == 200 for c in codes)

    r21 = client.post(url)
    assert r21.status_code == 429
    assert "Rate limit" in r21.json().get("error", "")


def test_thirty_first_pricing_override_is_rate_limited(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
    rate_limit_on: None,  # noqa: ARG001 — side-effect fixture; enables rate limiting
) -> None:
    """Pricing-override creation is rate limited (hardening spec §4.1.4)."""
    crud.set_setting(session=db, key=crud.OVERRIDE_THRESHOLD_KEY, value=5.0)
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"RATELIM-{uuid.uuid4().hex[:8]}",
            model_name="Rate Limit Test",
            brand="Acme",
            category="compressor",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb=Decimal("1000.00"),
            repair_price_thb=Decimal("300.00"),
        ),
    )
    url = f"{settings.API_V1_STR}/pricing-overrides"
    payload = {
        "target_kind": "SALE_LINE",
        "product_id": str(product.id),
        "requested_price_thb": "970.00",  # 3% -> AUTO_APPROVED, repeatable
        "reason": "rate limit test",
    }

    codes = [
        client.post(url, headers=staff_token_headers, json=payload).status_code
        for _ in range(30)
    ]
    assert all(c == 200 for c in codes)

    r31 = client.post(url, headers=staff_token_headers, json=payload)
    assert r31.status_code == 429
    assert "Rate limit" in r31.json().get("error", "")


def test_121st_pricing_override_poll_is_rate_limited(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
    rate_limit_on: None,  # noqa: ARG001 — side-effect fixture; enables rate limiting
) -> None:
    """Pricing-override poll read is rate limited (FR-010 polling backstop)."""
    crud.set_setting(session=db, key=crud.OVERRIDE_THRESHOLD_KEY, value=5.0)
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"POLLLIM-{uuid.uuid4().hex[:8]}",
            model_name="Poll Rate Limit Test",
            brand="Acme",
            category="compressor",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb=Decimal("1000.00"),
            repair_price_thb=Decimal("300.00"),
        ),
    )
    created = client.post(
        f"{settings.API_V1_STR}/pricing-overrides",
        headers=staff_token_headers,
        json={
            "target_kind": "SALE_LINE",
            "product_id": str(product.id),
            "requested_price_thb": "970.00",  # 3% -> AUTO_APPROVED
            "reason": "poll rate limit test",
        },
    )
    assert created.status_code == 200, created.text
    url = f"{settings.API_V1_STR}/pricing-overrides/{created.json()['id']}"

    codes = [
        client.get(url, headers=staff_token_headers).status_code for _ in range(120)
    ]
    assert all(c == 200 for c in codes)

    r121 = client.get(url, headers=staff_token_headers)
    assert r121.status_code == 429
    assert "Rate limit" in r121.json().get("error", "")


def test_121st_sync_ingest_is_rate_limited(
    client: TestClient,
    staff_token_headers: dict[str, str],
    rate_limit_on: None,  # noqa: ARG001 — side-effect fixture; enables rate limiting
) -> None:
    """Sync-review ingest is rate limited (hardening spec §4.1.4)."""
    url = f"{settings.API_V1_STR}/sync-review"

    def _ingest() -> Response:
        return client.post(
            url,
            headers=staff_token_headers,
            json={
                "idempotency_key": str(uuid.uuid4()),  # fresh key per request
                "mutation_kind": "sale",
                "payload": {"total_thb": "1200.00"},
                "reason": "STALE",
            },
        )

    responses = [_ingest() for _ in range(120)]
    try:
        assert all(r.status_code == 200 for r in responses)

        r121 = _ingest()
        assert r121.status_code == 429
        assert "Rate limit" in r121.json().get("error", "")
    finally:
        # 120 leftover PENDING rows would drown later list tests (limit=100);
        # remove exactly the rows this test created. Test-only cleanup runs on
        # the admin engine — the app role has no DELETE on syncreviewitem
        # (M026 grants are scoped to real app delete paths only).
        ids = [uuid.UUID(r.json()["id"]) for r in responses if r.status_code == 200]
        if ids:
            with Session(admin_engine) as admin_session:
                admin_session.execute(
                    delete(SyncReviewItem).where(col(SyncReviewItem.id).in_(ids))
                )
                admin_session.commit()
