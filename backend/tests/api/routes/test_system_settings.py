"""Exchange-rate settings API (admin-only config over SystemSetting)."""

from decimal import Decimal

from fastapi.testclient import TestClient

from app.core.config import settings

URL = f"{settings.API_V1_STR}/settings/exchange-rates"


def test_admin_get_exchange_rates(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.get(URL, headers=superuser_token_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "usd_thb" in body and "mmk_thb" in body


def test_admin_put_then_get_persists(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.put(
        URL,
        headers=superuser_token_headers,
        json={"usd_thb": "36.50", "mmk_thb": "0.0135"},
    )
    assert r.status_code == 200, r.text
    assert Decimal(str(r.json()["usd_thb"])) == Decimal("36.50")
    g = client.get(URL, headers=superuser_token_headers)
    assert Decimal(str(g.json()["usd_thb"])) == Decimal("36.50")
    assert Decimal(str(g.json()["mmk_thb"])) == Decimal("0.0135")


def test_staff_cannot_read(
    client: TestClient, staff_token_headers: dict[str, str]
) -> None:
    assert client.get(URL, headers=staff_token_headers).status_code == 403


def test_staff_cannot_write(
    client: TestClient, staff_token_headers: dict[str, str]
) -> None:
    r = client.put(
        URL, headers=staff_token_headers, json={"usd_thb": "1", "mmk_thb": "1"}
    )
    assert r.status_code == 403


def test_unauthenticated_rejected(client: TestClient) -> None:
    assert client.get(URL).status_code in (401, 403)


def test_negative_rate_rejected(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.put(
        URL,
        headers=superuser_token_headers,
        json={"usd_thb": "-1", "mmk_thb": "0"},
    )
    assert r.status_code == 422
