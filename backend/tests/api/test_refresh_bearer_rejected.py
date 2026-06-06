from datetime import timedelta

import jwt
from fastapi.testclient import TestClient

from app.core import security
from app.core.config import settings


def test_refresh_token_rejected_as_bearer(client: TestClient) -> None:
    login = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={
            "username": settings.FIRST_SUPERUSER,
            "password": settings.FIRST_SUPERUSER_PASSWORD,
        },
    )
    access = login.json()["access_token"]
    sub = jwt.decode(access, settings.SECRET_KEY, algorithms=[security.ALGORITHM])["sub"]
    refresh = security.create_refresh_token(sub, expires_delta=timedelta(minutes=5))

    r = client.post(
        f"{settings.API_V1_STR}/login/test-token",
        headers={"Authorization": f"Bearer {refresh}"},
    )
    assert r.status_code == 403
