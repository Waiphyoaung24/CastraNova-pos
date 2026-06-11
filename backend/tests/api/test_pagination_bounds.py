"""Pagination bounds (hardening spec §3): limit clamped to [1, 500], skip >= 0."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings

BOUNDED_LIST_PATHS = [
    "/users/",
    "/products/",
    "/customers/",
    "/suppliers/",
    "/projects/",
    "/project-pulls",
]


@pytest.mark.parametrize("path", BOUNDED_LIST_PATHS)
@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 501}, {"skip": -1}],
    ids=["limit-zero", "limit-over-cap", "negative-skip"],
)
def test_out_of_bounds_pagination_is_422(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    path: str,
    params: dict[str, int],
) -> None:
    r = client.get(
        f"{settings.API_V1_STR}{path}", headers=superuser_token_headers, params=params
    )
    assert r.status_code == 422
