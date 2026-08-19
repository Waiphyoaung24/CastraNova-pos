"""Supplier list `country` filter and the `/suppliers/countries` option list.

The count endpoint must reflect the same filter as the list (crud.list_suppliers
and crud.count_suppliers share a `_supplier_where` predicate) or pagination on
the frontend would disagree with what's actually on the page.
"""

import uuid

from fastapi.testclient import TestClient

from app.core.config import settings

PREFIX = settings.API_V1_STR


def _tag() -> str:
    return uuid.uuid4().hex[:10]


def _create_supplier(
    client: TestClient,
    headers: dict[str, str],
    *,
    name: str,
    country: str | None = None,
) -> None:
    body: dict[str, object] = {"name": name}
    if country is not None:
        body["country"] = country
    r = client.post(f"{PREFIX}/suppliers/", headers=headers, json=body)
    assert r.status_code == 200


def test_country_filter_returns_only_matching_suppliers(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    tag = _tag()
    country = f"Testland-{tag}"
    _create_supplier(client, superuser_token_headers, name=f"Sup-A-{tag}", country=country)
    _create_supplier(client, superuser_token_headers, name=f"Sup-B-{tag}", country=country)
    _create_supplier(
        client, superuser_token_headers, name=f"Sup-C-{tag}", country=f"Other-{tag}"
    )

    resp = client.get(
        f"{PREFIX}/suppliers/",
        headers=superuser_token_headers,
        params={"country": country},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert len(body["data"]) == 2
    assert all(row["country"] == country for row in body["data"])


def test_country_filter_composes_with_q(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    tag = _tag()
    country = f"Testland-{tag}"
    _create_supplier(client, superuser_token_headers, name=f"Bright-{tag}", country=country)
    _create_supplier(client, superuser_token_headers, name=f"Dim-{tag}", country=country)

    resp = client.get(
        f"{PREFIX}/suppliers/",
        headers=superuser_token_headers,
        params={"country": country, "q": f"bright-{tag}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["data"][0]["name"] == f"Bright-{tag}"


def test_country_filter_with_unused_country_returns_empty(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    tag = _tag()
    resp = client.get(
        f"{PREFIX}/suppliers/",
        headers=superuser_token_headers,
        params={"country": f"Unused-{tag}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0
    assert body["data"] == []


def test_countries_endpoint_includes_created_country_no_nulls_or_dupes(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    tag = _tag()
    country = f"Testland-{tag}"
    _create_supplier(client, superuser_token_headers, name=f"Sup-A-{tag}", country=country)
    _create_supplier(client, superuser_token_headers, name=f"Sup-B-{tag}", country=country)
    _create_supplier(client, superuser_token_headers, name=f"Sup-C-{tag}", country=None)

    resp = client.get(f"{PREFIX}/suppliers/countries", headers=superuser_token_headers)
    assert resp.status_code == 200
    countries = resp.json()
    assert country in countries
    assert None not in countries
    assert len(countries) == len(set(countries))
