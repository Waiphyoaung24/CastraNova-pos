"""Customer list `country`/`type` filters and the `/customers/countries` option list.

count_customers and list_customers share `_customer_filter_clauses`, so the
count must always reflect the same filter as the list.
"""

import uuid

from fastapi.testclient import TestClient

from app.core.config import settings

PREFIX = settings.API_V1_STR


def _tag() -> str:
    return uuid.uuid4().hex[:10]


def _create_customer(
    client: TestClient,
    headers: dict[str, str],
    *,
    name: str,
    country: str | None = None,
    type: str | None = None,
) -> None:
    body: dict[str, object] = {"name": name}
    if country is not None:
        body["country"] = country
    if type is not None:
        body["type"] = type
    r = client.post(f"{PREFIX}/customers/", headers=headers, json=body)
    assert r.status_code == 200


def test_country_filter_returns_only_matching_customers(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    tag = _tag()
    country = f"Testland-{tag}"
    _create_customer(client, superuser_token_headers, name=f"Cust-A-{tag}", country=country)
    _create_customer(client, superuser_token_headers, name=f"Cust-B-{tag}", country=country)
    _create_customer(
        client, superuser_token_headers, name=f"Cust-C-{tag}", country=f"Other-{tag}"
    )

    resp = client.get(
        f"{PREFIX}/customers/",
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
    _create_customer(client, superuser_token_headers, name=f"Bright-{tag}", country=country)
    _create_customer(client, superuser_token_headers, name=f"Dim-{tag}", country=country)

    resp = client.get(
        f"{PREFIX}/customers/",
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
        f"{PREFIX}/customers/",
        headers=superuser_token_headers,
        params={"country": f"Unused-{tag}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0
    assert body["data"] == []


def test_country_filter_percent_is_literal_not_wildcard(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    tag = _tag()
    _create_customer(client, superuser_token_headers, name=f"Pct-{tag}", country=f"C-{tag}")

    resp = client.get(
        f"{PREFIX}/customers/",
        headers=superuser_token_headers,
        params={"country": "%"},
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


def test_country_filter_blank_behaves_like_no_filter(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    unfiltered = client.get(f"{PREFIX}/customers/", headers=superuser_token_headers)
    blank = client.get(
        f"{PREFIX}/customers/",
        headers=superuser_token_headers,
        params={"country": "   "},
    )
    assert unfiltered.status_code == blank.status_code == 200
    assert unfiltered.json()["count"] == blank.json()["count"]


def test_countries_endpoint_includes_created_country_no_nulls_or_dupes(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    tag = _tag()
    country = f"Testland-{tag}"
    _create_customer(client, superuser_token_headers, name=f"Cust-A-{tag}", country=country)
    _create_customer(client, superuser_token_headers, name=f"Cust-B-{tag}", country=country)
    _create_customer(client, superuser_token_headers, name=f"Cust-C-{tag}", country=None)

    resp = client.get(f"{PREFIX}/customers/countries", headers=superuser_token_headers)
    assert resp.status_code == 200
    countries = resp.json()
    assert country in countries
    assert None not in countries
    assert len(countries) == len(set(countries))


def test_type_filter_returns_only_matching_customers(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    tag = _tag()
    _create_customer(
        client, superuser_token_headers, name=f"Dealer-{tag}", type="DEALER"
    )
    _create_customer(
        client, superuser_token_headers, name=f"End-{tag}", type="END_CUSTOMER"
    )

    resp = client.get(
        f"{PREFIX}/customers/",
        headers=superuser_token_headers,
        params={"q": tag, "type": "DEALER"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["data"][0]["name"] == f"Dealer-{tag}"


def test_type_filter_composes_with_country_and_q(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    tag = _tag()
    country = f"Testland-{tag}"
    _create_customer(
        client,
        superuser_token_headers,
        name=f"Match-{tag}",
        country=country,
        type="DEALER",
    )
    _create_customer(
        client,
        superuser_token_headers,
        name=f"WrongType-{tag}",
        country=country,
        type="END_CUSTOMER",
    )
    _create_customer(
        client,
        superuser_token_headers,
        name=f"WrongCountry-{tag}",
        country=f"Other-{tag}",
        type="DEALER",
    )

    resp = client.get(
        f"{PREFIX}/customers/",
        headers=superuser_token_headers,
        params={"q": tag, "country": country, "type": "DEALER"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["data"][0]["name"] == f"Match-{tag}"


def test_type_filter_rejects_unknown_type(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    resp = client.get(
        f"{PREFIX}/customers/",
        headers=superuser_token_headers,
        params={"type": "BOGUS"},
    )
    assert resp.status_code == 422
