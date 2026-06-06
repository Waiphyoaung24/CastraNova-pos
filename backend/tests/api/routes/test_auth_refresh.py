from datetime import timedelta

from fastapi.testclient import TestClient

from app.core import security
from app.core.config import settings

LOGIN = f"{settings.API_V1_STR}/login/access-token"
REFRESH = f"{settings.API_V1_STR}/login/refresh-token"
LOGOUT = f"{settings.API_V1_STR}/login/logout"
TEST_TOKEN = f"{settings.API_V1_STR}/login/test-token"


def _login(client: TestClient):
    return client.post(
        LOGIN,
        data={
            "username": settings.FIRST_SUPERUSER,
            "password": settings.FIRST_SUPERUSER_PASSWORD,
        },
    )


def test_login_sets_httponly_refresh_cookie(client: TestClient) -> None:
    r = _login(client)
    assert r.status_code == 200
    assert r.json()["access_token"]
    set_cookie = r.headers.get("set-cookie", "").lower()
    assert security.REFRESH_TOKEN_COOKIE_NAME in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie


def test_refresh_returns_working_access_token(client: TestClient) -> None:
    login = _login(client)
    assert login.cookies.get(security.REFRESH_TOKEN_COOKIE_NAME)
    r = client.post(REFRESH)
    assert r.status_code == 200
    access = r.json()["access_token"]
    me = client.post(TEST_TOKEN, headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200


def test_refresh_without_cookie_returns_401(client: TestClient) -> None:
    client.cookies.clear()
    r = client.post(REFRESH)
    assert r.status_code == 401


def test_logout_clears_refresh_cookie(client: TestClient) -> None:
    _login(client)
    r = client.post(LOGOUT)
    assert r.status_code == 200
    set_cookie = r.headers.get("set-cookie", "").lower()
    assert security.REFRESH_TOKEN_COOKIE_NAME in set_cookie
    assert 'refresh_token=""' in set_cookie or "max-age=0" in set_cookie


def test_access_token_not_accepted_at_refresh(client: TestClient) -> None:
    # An access-typed token placed in the refresh cookie must be rejected.
    client.cookies.clear()
    access = security.create_access_token(
        "any-subject", expires_delta=timedelta(minutes=5)
    )
    client.cookies.set(security.REFRESH_TOKEN_COOKIE_NAME, access)
    r = client.post(REFRESH)
    client.cookies.clear()
    assert r.status_code == 401
