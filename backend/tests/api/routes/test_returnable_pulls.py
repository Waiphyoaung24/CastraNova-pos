"""GET /project-pulls/returnable — the Returns page's project-request source."""

# ruff: noqa: F811  (pull_ctx is an imported pytest fixture)
import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.models import (
    ProjectPullCreate,
    ProjectPullLineCreate,
    ProjectPullReturnCreate,
    ProjectPullReturnLine,
    SaleLineInput,
    SaleLineKind,
)
from tests.api.routes.test_project_pulls import (  # noqa: F401  (pull_ctx is a fixture)
    _create,
    _line_ids,
    pull_ctx,
)
from tests.utils.utils import assert_no_financial_keys

PREFIX = settings.API_V1_STR


def _settle(db: Session, pull_id: str, ctx: dict[str, Any]) -> None:
    crud.fulfill_project_pull(
        session=db, pull_id=uuid.UUID(pull_id), fulfill_lines=[], actor_user_id=ctx["admin_id"]
    )


def _part_pull(db: Session, ctx: dict[str, Any], *, qty: int) -> uuid.UUID:
    """A settled pull with only a PART line (the shared unit can be pulled once)."""
    pull = crud.create_project_pull(
        session=db,
        pull_in=ProjectPullCreate(
            project_id=ctx["project_id"],
            lines=[
                ProjectPullLineCreate(
                    line_kind=SaleLineKind.PART, product_id=ctx["part_product_id"], requested_qty=qty
                )
            ],
        ),
        created_by_user_id=ctx["admin_id"],
    )
    crud.fulfill_project_pull(session=db, pull_id=pull.id, fulfill_lines=[], actor_user_id=ctx["admin_id"])
    return pull.id


def _sku(db: Session, product_id: uuid.UUID) -> str:
    product = crud.get_product(session=db, product_id=product_id)
    assert product is not None
    return product.sku


def test_sku_lists_settled_pulls(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session, pull_ctx: dict[str, Any]
) -> None:
    first = _create(client, superuser_token_headers, pull_ctx, part_qty=2)  # UNIT + PART
    _settle(db, first["id"], pull_ctx)
    second = _part_pull(db, pull_ctx, qty=1)

    r = client.get(
        f"{PREFIX}/project-pulls/returnable",
        headers=superuser_token_headers,
        params={"sku": _sku(db, pull_ctx["part_product_id"])},
    )
    assert r.status_code == 200, r.text
    pulls = r.json()["pulls"]
    # Same-second created_at ties make the order random on Windows, so assert
    # membership; the query orders by created_at desc for the picker.
    assert {p["pull_id"] for p in pulls} == {first["id"], str(second)}
    by_id = {p["pull_id"]: p for p in pulls}
    line = by_id[first["id"]]["lines"][0]
    assert line["line_kind"] == "PART"
    assert line["quantity_out"] == 2 and line["quantity_returnable"] == 2
    assert by_id[first["id"]]["project_code"] and by_id[first["id"]]["customer_name"] == "Proj Cust"
    # Only the PART line matches a SKU lookup — the UNIT line is another product.
    assert all(ln["line_kind"] == "PART" for p in pulls for ln in p["lines"])


def test_barcode_resolves_a_pulled_unit(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session, pull_ctx: dict[str, Any]
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx)
    _settle(db, pull["id"], pull_ctx)
    r = client.get(
        f"{PREFIX}/project-pulls/returnable",
        headers=superuser_token_headers,
        params={"castranova_barcode": pull_ctx["barcode"]},
    )
    assert r.status_code == 200, r.text
    pulls = r.json()["pulls"]
    assert len(pulls) == 1 and pulls[0]["pull_id"] == pull["id"]
    line = pulls[0]["lines"][0]
    assert line["line_kind"] == "UNIT" and line["quantity_returnable"] == 1


def test_fully_returned_line_disappears(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session, pull_ctx: dict[str, Any]
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx, part_qty=2)
    _settle(db, pull["id"], pull_ctx)
    ids = _line_ids(db, uuid.UUID(pull["id"]))
    crud.return_project_pull(
        session=db,
        pull_id=uuid.UUID(pull["id"]),
        payload=ProjectPullReturnCreate(
            idempotency_key=uuid.uuid4(),
            lines=[ProjectPullReturnLine(line_id=uuid.UUID(ids["PART"]), quantity=2)],
        ),
        actor_user_id=pull_ctx["admin_id"],
    )
    r = client.get(
        f"{PREFIX}/project-pulls/returnable",
        headers=superuser_token_headers,
        params={"sku": _sku(db, pull_ctx["part_product_id"])},
    )
    assert r.status_code == 200
    assert r.json()["pulls"] == []


def test_pending_pull_not_offered(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session, pull_ctx: dict[str, Any]
) -> None:
    _create(client, superuser_token_headers, pull_ctx)  # stays PENDING: undo via Cancel
    r = client.get(
        f"{PREFIX}/project-pulls/returnable",
        headers=superuser_token_headers,
        params={"sku": _sku(db, pull_ctx["part_product_id"])},
    )
    assert r.status_code == 200
    assert r.json()["pulls"] == []


def test_unit_returned_then_sold_offers_sale_not_pull(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session, pull_ctx: dict[str, Any]
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx)
    _settle(db, pull["id"], pull_ctx)
    ids = _line_ids(db, uuid.UUID(pull["id"]))
    crud.return_project_pull(
        session=db,
        pull_id=uuid.UUID(pull["id"]),
        payload=ProjectPullReturnCreate(
            idempotency_key=uuid.uuid4(),
            lines=[ProjectPullReturnLine(line_id=uuid.UUID(ids["UNIT"]), quantity=1)],
        ),
        actor_user_id=pull_ctx["admin_id"],
    )
    crud.create_sale(
        session=db,
        customer_id=pull_ctx["customer_id"],
        created_by_user_id=pull_ctx["admin_id"],
        idempotency_key=uuid.uuid4(),
        lines=[SaleLineInput(line_kind=SaleLineKind.UNIT, castranova_barcode=pull_ctx["barcode"])],
    )
    pulls = client.get(
        f"{PREFIX}/project-pulls/returnable",
        headers=superuser_token_headers,
        params={"castranova_barcode": pull_ctx["barcode"]},
    ).json()["pulls"]
    sales = client.get(
        f"{PREFIX}/sales/returnable",
        headers=superuser_token_headers,
        params={"castranova_barcode": pull_ctx["barcode"]},
    ).json()["sales"]
    assert pulls == [] and len(sales) == 1


def test_requires_exactly_one_selector(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    none = client.get(f"{PREFIX}/project-pulls/returnable", headers=superuser_token_headers)
    both = client.get(
        f"{PREFIX}/project-pulls/returnable",
        headers=superuser_token_headers,
        params={"sku": "X", "castranova_barcode": "Y"},
    )
    assert none.status_code == 422 and both.status_code == 422
    unknown = client.get(
        f"{PREFIX}/project-pulls/returnable",
        headers=superuser_token_headers,
        params={"sku": f"NOPE-{uuid.uuid4().hex[:6]}"},
    )
    assert unknown.status_code == 404


def test_staff_can_use_lookup_and_sees_no_cost(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
    pull_ctx: dict[str, Any],
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx)
    _settle(db, pull["id"], pull_ctx)
    r = client.get(
        f"{PREFIX}/project-pulls/returnable",
        headers=staff_token_headers,
        params={"sku": _sku(db, pull_ctx["part_product_id"])},
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["pulls"]) == 1
    assert_no_financial_keys(r.json())
    assert "unit_price_thb" not in r.text and "cost" not in r.text
