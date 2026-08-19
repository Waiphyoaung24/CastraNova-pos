"""Catalog list search (`q`): products/customers/suppliers/projects.

Each list endpoint gained an optional case-insensitive substring filter on
name/identifier columns. The count endpoint must reflect the same filter as
the list, or PaginationControls on the frontend would report a total that
disagrees with what's actually on the page.
"""

import uuid

from fastapi.testclient import TestClient

from app.core.config import settings

PREFIX = settings.API_V1_STR


def _tag() -> str:
    return uuid.uuid4().hex[:10]


# --- Products (sku OR model_name) ----------------------------------------------


def _product_body(
    sku: str,
    model_name: str,
    *,
    brand: str | None = None,
    category: str | None = None,
    tracking_mode: str = "SERIALIZED",
) -> dict[str, object]:
    body: dict[str, object] = {
        "sku": sku,
        "model_name": model_name,
        "tracking_mode": tracking_mode,
        "retail_price_thb": "1000.00",
        "repair_price_thb": "200.00",
    }
    if brand is not None:
        body["brand"] = brand
    if category is not None:
        body["category"] = category
    return body


def test_product_search_matches_sku(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    tag = _tag()
    sku = f"SKU-{tag}"
    r = client.post(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        json=_product_body(sku, "Widget"),
    )
    assert r.status_code == 200

    resp = client.get(
        f"{PREFIX}/products/", headers=superuser_token_headers, params={"q": tag}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["data"][0]["sku"] == sku


def test_product_search_matches_model_name_case_insensitive(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    tag = _tag()
    sku = f"MDL-{uuid.uuid4().hex[:8]}"
    model_name = f"Grundfos-{tag} CR"
    r = client.post(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        json=_product_body(sku, model_name),
    )
    assert r.status_code == 200

    resp = client.get(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        params={"q": f"grundfos-{tag}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["data"][0]["sku"] == sku


def test_product_search_count_matches_filtered_rows_not_table_total(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    tag = _tag()
    for i in range(3):
        r = client.post(
            f"{PREFIX}/products/",
            headers=superuser_token_headers,
            json=_product_body(f"CNT-{tag}-{i}", "Widget"),
        )
        assert r.status_code == 200
    # An unrelated product must not be swept in.
    other = client.post(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        json=_product_body(f"OTHER-{uuid.uuid4().hex[:8]}", "Unrelated"),
    )
    assert other.status_code == 200

    resp = client.get(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        params={"q": tag, "limit": 2},
    )
    body = resp.json()
    assert body["count"] == 3
    assert len(body["data"]) == 2


def test_product_search_percent_is_literal_not_wildcard(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    tag = _tag()
    r = client.post(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        json=_product_body(f"PCT-{tag}", "Widget"),
    )
    assert r.status_code == 200

    resp = client.get(
        f"{PREFIX}/products/", headers=superuser_token_headers, params={"q": "%"}
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


def test_product_search_blank_q_behaves_like_no_filter(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    unfiltered = client.get(f"{PREFIX}/products/", headers=superuser_token_headers)
    blank = client.get(
        f"{PREFIX}/products/", headers=superuser_token_headers, params={"q": "   "}
    )
    assert unfiltered.status_code == blank.status_code == 200
    assert unfiltered.json()["count"] == blank.json()["count"]


# --- Products (brand / category / tracking_mode) --------------------------------


def test_product_filter_by_brand(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    tag = _tag()
    r = client.post(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        json=_product_body(f"BRD-{tag}", "Widget", brand=f"Acme-{tag}"),
    )
    assert r.status_code == 200
    other = client.post(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        json=_product_body(
            f"BRD-other-{uuid.uuid4().hex[:8]}", "Widget", brand="Unrelated"
        ),
    )
    assert other.status_code == 200

    resp = client.get(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        params={"brand": f"acme-{tag}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["data"][0]["sku"] == f"BRD-{tag}"


def test_product_filter_by_category(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    tag = _tag()
    r = client.post(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        json=_product_body(f"CAT-{tag}", "Widget", category=f"Screen-{tag}"),
    )
    assert r.status_code == 200
    other = client.post(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        json=_product_body(
            f"CAT-other-{uuid.uuid4().hex[:8]}", "Widget", category="Battery"
        ),
    )
    assert other.status_code == 200

    resp = client.get(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        params={"category": f"screen-{tag}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["data"][0]["sku"] == f"CAT-{tag}"


def test_product_filter_by_tracking_mode(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    tag = _tag()
    serialized = client.post(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        json=_product_body(
            f"TRK-ser-{tag}", "Widget", tracking_mode="SERIALIZED"
        ),
    )
    assert serialized.status_code == 200
    quantity = client.post(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        json=_product_body(f"TRK-qty-{tag}", "Widget", tracking_mode="QUANTITY"),
    )
    assert quantity.status_code == 200

    resp = client.get(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        params={"q": tag, "tracking_mode": "SERIALIZED"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["data"][0]["sku"] == f"TRK-ser-{tag}"


def test_product_filters_compose_with_search(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    tag = _tag()
    r = client.post(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        json=_product_body(
            f"CMB-{tag}",
            "Widget",
            brand=f"Acme-{tag}",
            tracking_mode="SERIALIZED",
        ),
    )
    assert r.status_code == 200

    matching = client.get(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        params={"q": tag, "brand": f"acme-{tag}", "tracking_mode": "SERIALIZED"},
    )
    assert matching.status_code == 200
    assert matching.json()["count"] == 1

    contradictory = client.get(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        params={"q": tag, "brand": f"acme-{tag}", "tracking_mode": "QUANTITY"},
    )
    assert contradictory.status_code == 200
    assert contradictory.json()["count"] == 0


def test_product_filter_count_matches_filtered_rows_not_table_total(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    tag = _tag()
    brand = f"Acme-{tag}"
    for i in range(3):
        r = client.post(
            f"{PREFIX}/products/",
            headers=superuser_token_headers,
            json=_product_body(f"BCT-{tag}-{i}", "Widget", brand=brand),
        )
        assert r.status_code == 200
    other = client.post(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        json=_product_body(
            f"BCT-other-{uuid.uuid4().hex[:8]}", "Widget", brand="Unrelated"
        ),
    )
    assert other.status_code == 200

    resp = client.get(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        params={"brand": brand, "limit": 2},
    )
    body = resp.json()
    assert body["count"] == 3
    assert len(body["data"]) == 2


def test_product_filter_percent_is_literal_not_wildcard(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    tag = _tag()
    r = client.post(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        json=_product_body(f"PCTB-{tag}", "Widget", brand=f"Brand-{tag}"),
    )
    assert r.status_code == 200

    resp = client.get(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        params={"brand": "%"},
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


def test_product_filter_blank_behaves_like_no_filter(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    unfiltered = client.get(f"{PREFIX}/products/", headers=superuser_token_headers)
    blank = client.get(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        params={"brand": "   ", "category": "  "},
    )
    assert unfiltered.status_code == blank.status_code == 200
    assert unfiltered.json()["count"] == blank.json()["count"]


def test_product_filter_rejects_unknown_tracking_mode(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    resp = client.get(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        params={"tracking_mode": "BOGUS"},
    )
    assert resp.status_code == 422


# --- Customers (name) -----------------------------------------------------------


def test_customer_search_matches_name_case_insensitive(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    tag = _tag()
    name = f"Acme-{tag} Trading Co."
    r = client.post(
        f"{PREFIX}/customers/", headers=superuser_token_headers, json={"name": name}
    )
    assert r.status_code == 200

    resp = client.get(
        f"{PREFIX}/customers/",
        headers=superuser_token_headers,
        params={"q": f"acme-{tag}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["data"][0]["name"] == name


def test_customer_search_count_reflects_filter(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    tag = _tag()
    for i in range(2):
        r = client.post(
            f"{PREFIX}/customers/",
            headers=superuser_token_headers,
            json={"name": f"Cust-{tag}-{i}"},
        )
        assert r.status_code == 200
    other = client.post(
        f"{PREFIX}/customers/",
        headers=superuser_token_headers,
        json={"name": f"Unrelated-{uuid.uuid4().hex[:8]}"},
    )
    assert other.status_code == 200

    resp = client.get(
        f"{PREFIX}/customers/", headers=superuser_token_headers, params={"q": tag}
    )
    assert resp.json()["count"] == 2


# --- Suppliers (name) ------------------------------------------------------------


def test_supplier_search_matches_name_case_insensitive(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    tag = _tag()
    name = f"Bright-{tag} Ltd"
    r = client.post(
        f"{PREFIX}/suppliers/", headers=superuser_token_headers, json={"name": name}
    )
    assert r.status_code == 200

    resp = client.get(
        f"{PREFIX}/suppliers/",
        headers=superuser_token_headers,
        params={"q": f"bright-{tag}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["data"][0]["name"] == name


def test_supplier_search_count_reflects_filter(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    tag = _tag()
    for i in range(2):
        r = client.post(
            f"{PREFIX}/suppliers/",
            headers=superuser_token_headers,
            json={"name": f"Sup-{tag}-{i}"},
        )
        assert r.status_code == 200

    resp = client.get(
        f"{PREFIX}/suppliers/", headers=superuser_token_headers, params={"q": tag}
    )
    assert resp.json()["count"] == 2


# --- Projects (code OR name) ------------------------------------------------------


def test_project_search_matches_code(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    tag = _tag()
    cust = client.post(
        f"{PREFIX}/customers/",
        headers=superuser_token_headers,
        json={"name": f"ProjCust-{tag}"},
    )
    cid = cust.json()["id"]
    code = f"PRJ-{tag}"
    r = client.post(
        f"{PREFIX}/projects/",
        headers=superuser_token_headers,
        json={"code": code, "name": "Some project", "customer_id": cid},
    )
    assert r.status_code == 200

    resp = client.get(
        f"{PREFIX}/projects/", headers=superuser_token_headers, params={"q": tag}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["data"][0]["code"] == code


def test_project_search_matches_name(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    tag = _tag()
    cust = client.post(
        f"{PREFIX}/customers/",
        headers=superuser_token_headers,
        json={"name": f"ProjCust2-{tag}"},
    )
    cid = cust.json()["id"]
    name = f"Renovation-{tag}"
    r = client.post(
        f"{PREFIX}/projects/",
        headers=superuser_token_headers,
        json={"code": f"CODE-{uuid.uuid4().hex[:8]}", "name": name, "customer_id": cid},
    )
    assert r.status_code == 200

    resp = client.get(
        f"{PREFIX}/projects/", headers=superuser_token_headers, params={"q": tag}
    )
    body = resp.json()
    assert body["count"] == 1
    assert body["data"][0]["name"] == name


def test_project_search_combines_with_skip_limit(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    tag = _tag()
    cust = client.post(
        f"{PREFIX}/customers/",
        headers=superuser_token_headers,
        json={"name": f"ProjCust3-{tag}"},
    )
    cid = cust.json()["id"]
    for i in range(3):
        r = client.post(
            f"{PREFIX}/projects/",
            headers=superuser_token_headers,
            json={"code": f"PG-{tag}-{i}", "name": "Multi", "customer_id": cid},
        )
        assert r.status_code == 200

    resp = client.get(
        f"{PREFIX}/projects/",
        headers=superuser_token_headers,
        params={"q": tag, "skip": 1, "limit": 1},
    )
    body = resp.json()
    assert body["count"] == 3
    assert len(body["data"]) == 1


# --- Projects (customer_id, status) ---------------------------------------------


def test_project_filter_by_customer(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    tag = _tag()
    cust_a = client.post(
        f"{PREFIX}/customers/",
        headers=superuser_token_headers,
        json={"name": f"ProjCustA-{tag}"},
    ).json()
    cust_b = client.post(
        f"{PREFIX}/customers/",
        headers=superuser_token_headers,
        json={"name": f"ProjCustB-{tag}"},
    ).json()
    r = client.post(
        f"{PREFIX}/projects/",
        headers=superuser_token_headers,
        json={"code": f"CID-A-{tag}", "name": "For A", "customer_id": cust_a["id"]},
    )
    assert r.status_code == 200
    other = client.post(
        f"{PREFIX}/projects/",
        headers=superuser_token_headers,
        json={"code": f"CID-B-{tag}", "name": "For B", "customer_id": cust_b["id"]},
    )
    assert other.status_code == 200

    resp = client.get(
        f"{PREFIX}/projects/",
        headers=superuser_token_headers,
        params={"customer_id": cust_a["id"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["data"][0]["code"] == f"CID-A-{tag}"


def test_project_filter_by_status(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    tag = _tag()
    cust = client.post(
        f"{PREFIX}/customers/",
        headers=superuser_token_headers,
        json={"name": f"ProjCustStatus-{tag}"},
    ).json()
    active_code = f"ST-ACTIVE-{tag}"
    closed_code = f"ST-CLOSED-{tag}"
    r_active = client.post(
        f"{PREFIX}/projects/",
        headers=superuser_token_headers,
        json={"code": active_code, "name": "Active one", "customer_id": cust["id"]},
    )
    assert r_active.status_code == 200
    r_closed = client.post(
        f"{PREFIX}/projects/",
        headers=superuser_token_headers,
        json={"code": closed_code, "name": "Closed one", "customer_id": cust["id"]},
    )
    assert r_closed.status_code == 200
    closed_id = r_closed.json()["id"]
    patch = client.patch(
        f"{PREFIX}/projects/{closed_id}",
        headers=superuser_token_headers,
        json={"status": "CLOSED"},
    )
    assert patch.status_code == 200

    resp = client.get(
        f"{PREFIX}/projects/",
        headers=superuser_token_headers,
        params={"status": "ACTIVE", "q": tag},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["data"][0]["code"] == active_code

    resp_closed = client.get(
        f"{PREFIX}/projects/",
        headers=superuser_token_headers,
        params={"status": "CLOSED", "q": tag},
    )
    body_closed = resp_closed.json()
    assert body_closed["count"] == 1
    assert body_closed["data"][0]["code"] == closed_code


def test_project_filters_compose_with_search(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    tag = _tag()
    cust_a = client.post(
        f"{PREFIX}/customers/",
        headers=superuser_token_headers,
        json={"name": f"ProjCustCompose-{tag}"},
    ).json()
    cust_b = client.post(
        f"{PREFIX}/customers/",
        headers=superuser_token_headers,
        json={"name": f"ProjCustCompose2-{tag}"},
    ).json()
    r = client.post(
        f"{PREFIX}/projects/",
        headers=superuser_token_headers,
        json={
            "code": f"CMP-{tag}",
            "name": f"Composed-{tag}",
            "customer_id": cust_a["id"],
        },
    )
    assert r.status_code == 200
    # Same search term, wrong customer — must be excluded.
    other = client.post(
        f"{PREFIX}/projects/",
        headers=superuser_token_headers,
        json={
            "code": f"CMP-other-{uuid.uuid4().hex[:8]}",
            "name": f"Composed-{tag}",
            "customer_id": cust_b["id"],
        },
    )
    assert other.status_code == 200

    resp = client.get(
        f"{PREFIX}/projects/",
        headers=superuser_token_headers,
        params={"q": tag, "customer_id": cust_a["id"], "status": "ACTIVE"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["data"][0]["code"] == f"CMP-{tag}"


def test_project_filter_count_matches_filtered_rows_not_table_total(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    tag = _tag()
    cust = client.post(
        f"{PREFIX}/customers/",
        headers=superuser_token_headers,
        json={"name": f"ProjCustCount-{tag}"},
    ).json()
    for i in range(3):
        r = client.post(
            f"{PREFIX}/projects/",
            headers=superuser_token_headers,
            json={
                "code": f"CNT-{tag}-{i}",
                "name": "Count me",
                "customer_id": cust["id"],
            },
        )
        assert r.status_code == 200
    other = client.post(
        f"{PREFIX}/projects/",
        headers=superuser_token_headers,
        json={
            "code": f"CNT-other-{uuid.uuid4().hex[:8]}",
            "name": "Not counted",
            "customer_id": cust["id"],
        },
    )
    assert other.status_code == 200

    resp = client.get(
        f"{PREFIX}/projects/",
        headers=superuser_token_headers,
        params={"customer_id": cust["id"], "q": tag, "limit": 2},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 3
    assert len(body["data"]) == 2


def test_project_filter_rejects_unknown_status(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    resp = client.get(
        f"{PREFIX}/projects/",
        headers=superuser_token_headers,
        params={"status": "BOGUS"},
    )
    assert resp.status_code == 422
