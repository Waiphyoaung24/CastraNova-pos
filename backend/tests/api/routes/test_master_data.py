import uuid

from fastapi.testclient import TestClient

from app.core.config import settings

PREFIX = settings.API_V1_STR


# --- Supplier (admin write, staff read) ---------------------------------------


def test_staff_can_read_suppliers(
    client: TestClient, staff_token_headers: dict[str, str]
) -> None:
    r = client.get(f"{PREFIX}/suppliers/", headers=staff_token_headers)
    assert r.status_code == 200


def test_staff_cannot_create_supplier(
    client: TestClient, staff_token_headers: dict[str, str]
) -> None:
    r = client.post(
        f"{PREFIX}/suppliers/", headers=staff_token_headers, json={"name": "Acme"}
    )
    assert r.status_code == 403


def test_admin_creates_and_updates_supplier(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.post(
        f"{PREFIX}/suppliers/",
        headers=superuser_token_headers,
        json={"name": "Acme", "country": "TH"},
    )
    assert r.status_code == 200
    sid = r.json()["id"]
    r2 = client.patch(
        f"{PREFIX}/suppliers/{sid}",
        headers=superuser_token_headers,
        json={"contact": "ops@acme.example.com"},
    )
    assert r2.status_code == 200
    assert r2.json()["contact"] == "ops@acme.example.com"


def test_update_missing_supplier_404(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.patch(
        f"{PREFIX}/suppliers/{uuid.uuid4()}",
        headers=superuser_token_headers,
        json={"name": "X"},
    )
    assert r.status_code == 404


# --- Customer (staff inline-create; admin-only update) ------------------------


def test_staff_can_create_customer_inline(
    client: TestClient, staff_token_headers: dict[str, str]
) -> None:
    r = client.post(
        f"{PREFIX}/customers/",
        headers=staff_token_headers,
        json={"name": "Walk-in", "type": "END_CUSTOMER"},
    )
    assert r.status_code == 200
    assert r.json()["type"] == "END_CUSTOMER"


def test_staff_cannot_update_customer(
    client: TestClient,
    staff_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
) -> None:
    created = client.post(
        f"{PREFIX}/customers/",
        headers=superuser_token_headers,
        json={"name": "C1"},
    )
    cid = created.json()["id"]
    r = client.patch(
        f"{PREFIX}/customers/{cid}",
        headers=staff_token_headers,
        json={"notes": "x"},
    )
    assert r.status_code == 403


# --- Project (admin-only) -----------------------------------------------------


def test_staff_cannot_read_projects(
    client: TestClient, staff_token_headers: dict[str, str]
) -> None:
    r = client.get(f"{PREFIX}/projects/", headers=staff_token_headers)
    assert r.status_code == 403


def test_admin_creates_project_and_duplicate_code_409(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    cust = client.post(
        f"{PREFIX}/customers/",
        headers=superuser_token_headers,
        json={"name": "ProjCust"},
    )
    cid = cust.json()["id"]
    code = f"PRJ-{uuid.uuid4().hex[:8]}"
    body = {"code": code, "name": "Proj 1", "customer_id": cid}
    r = client.post(f"{PREFIX}/projects/", headers=superuser_token_headers, json=body)
    assert r.status_code == 200
    r2 = client.post(f"{PREFIX}/projects/", headers=superuser_token_headers, json=body)
    assert r2.status_code == 409


def test_create_project_unknown_customer_404(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    body = {
        "code": f"PRJ-{uuid.uuid4().hex[:8]}",
        "name": "Orphan",
        "customer_id": str(uuid.uuid4()),
    }
    r = client.post(f"{PREFIX}/projects/", headers=superuser_token_headers, json=body)
    assert r.status_code == 404
