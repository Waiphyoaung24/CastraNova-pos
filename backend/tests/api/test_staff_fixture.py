from fastapi.testclient import TestClient

from app.core.config import settings


def test_staff_token_headers_resolve_to_staff_user(
    client: TestClient, staff_token_headers: dict[str, str]
) -> None:
    r = client.get(f"{settings.API_V1_STR}/users/me", headers=staff_token_headers)
    assert r.status_code == 200
    assert r.json()["role"] == "YGN_STAFF"
