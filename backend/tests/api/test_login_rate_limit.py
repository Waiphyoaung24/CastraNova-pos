import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.limiter import limiter


@pytest.fixture
def rate_limit_on():
    limiter.reset()
    limiter.enabled = True
    yield
    limiter.enabled = False
    limiter.reset()


def test_sixth_login_attempt_is_rate_limited(
    client: TestClient, rate_limit_on: None  # noqa: ARG001 — side-effect fixture
) -> None:
    url = f"{settings.API_V1_STR}/login/access-token"
    data = {"username": "nobody@example.com", "password": "wrongpass"}

    codes = [client.post(url, data=data).status_code for _ in range(5)]
    assert all(c == 400 for c in codes)

    r6 = client.post(url, data=data)
    assert r6.status_code == 429
