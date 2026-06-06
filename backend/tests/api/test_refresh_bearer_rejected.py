from datetime import timedelta

from fastapi.testclient import TestClient

from app.core import security
from app.core.config import settings


def test_refresh_token_rejected_as_bearer(client: TestClient) -> None:
    # A refresh-typed JWT must never be accepted as a bearer access token.
    refresh = security.create_refresh_token(
        "any-subject", expires_delta=timedelta(minutes=5)
    )
    r = client.post(
        f"{settings.API_V1_STR}/login/test-token",
        headers={"Authorization": f"Bearer {refresh}"},
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "Could not validate credentials"
