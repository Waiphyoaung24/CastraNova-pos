import uuid
from datetime import timedelta

from fastapi.testclient import TestClient

from app.core import security
from app.core.config import settings

# A bearer token that the server cannot turn into a valid, active user must
# return 401 (so clients re-authenticate), not 403/404. 403 is reserved for an
# authenticated user lacking a role; 404 is for route-level resource lookups.
TEST_TOKEN = f"{settings.API_V1_STR}/login/test-token"


def test_malformed_bearer_token_returns_401(client: TestClient) -> None:
    r = client.post(TEST_TOKEN, headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401
    assert r.headers.get("WWW-Authenticate") == "Bearer"


def test_wrong_type_token_returns_401(client: TestClient) -> None:
    # A refresh-typed JWT must never authenticate as a bearer access token.
    refresh = security.create_refresh_token(
        "any-subject", expires_delta=timedelta(minutes=5)
    )
    r = client.post(TEST_TOKEN, headers={"Authorization": f"Bearer {refresh}"})
    assert r.status_code == 401


def test_valid_token_for_missing_user_returns_401(client: TestClient) -> None:
    # Well-formed access token whose subject is no longer (or never) a user:
    # this is the stale-token case — authentication fails, so 401, not 404.
    token = security.create_access_token(
        str(uuid.uuid4()), expires_delta=timedelta(minutes=5)
    )
    r = client.post(TEST_TOKEN, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
