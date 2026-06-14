import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, col, select

from app import crud
from app.core.config import settings
from app.models import (
    CostLine,
    CustomerCreate,
    Location,
    MovementType,
    PartMovement,
    ProductCreate,
    ProjectCreate,
    ProjectPull,
    ProjectPullState,
    ReceivePiece,
    SaleLineInput,
    SaleLineKind,
    SupplierCreate,
    TrackingMode,
    Unit,
    UnitMovement,
    UnitState,
)
from tests.utils.utils import assert_no_financial_keys

PREFIX = settings.API_V1_STR


@pytest.fixture
def pull_ctx(
    db: Session,
) -> Iterator[dict[str, Any]]:
    """A project (+customer), a SERIALIZED product with one IN_STOCK unit, and a
    QUANTITY product stocked 3@10 + 4@12. Yields ids needed to build pull lines."""
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    admin = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert admin is not None
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Proj Cust")
    )
    project = crud.create_project(
        session=db,
        project_in=ProjectCreate(
            code=f"PRJ-{uuid.uuid4().hex[:8]}",
            name="Site A",
            customer_id=customer.id,
        ),
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name="Acme")
    )
    serialized = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"SER-{uuid.uuid4().hex[:8]}",
            model_name="Compressor",
            tracking_mode=TrackingMode.SERIALIZED,
            retail_price_thb="500.00",
            repair_price_thb="50.00",
        ),
    )
    part = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"QTY-{uuid.uuid4().hex[:8]}",
            model_name="Bolt",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="10.00",
            repair_price_thb="2.00",
        ),
    )
    units = crud.receive_serialized(
        session=db,
        product_id=serialized.id,
        supplier_id=supplier.id,
        pieces=[
            ReceivePiece(supplier_serial="S1", purchase_cost_thb=Decimal("100.00"))
        ],
        idempotency_key=uuid.uuid4(),
        received_by_user_id=admin.id,
    )
    barcode = units[0].castranova_barcode
    for qty, cost in ((3, "10.00"), (4, "12.00")):
        crud.receive_quantity(
            session=db,
            product_id=part.id,
            supplier_id=supplier.id,
            received_qty=qty,
            purchase_cost_thb=Decimal(cost),
            idempotency_key=uuid.uuid4(),
            received_by_user_id=admin.id,
        )
    yield {
        "project_id": project.id,
        "customer_id": customer.id,
        "serialized_product_id": serialized.id,
        "part_product_id": part.id,
        "barcode": barcode,
        "supplier_id": supplier.id,
        "admin_id": admin.id,
    }


def _create_body(ctx: dict[str, Any], *, part_qty: int = 2) -> dict[str, Any]:
    return {
        "project_id": str(ctx["project_id"]),
        "admin_notes": "Pull for site A",
        "lines": [
            {
                "line_kind": "UNIT",
                "product_id": str(ctx["serialized_product_id"]),
                "unit_serial": ctx["barcode"],
            },
            {
                "line_kind": "PART",
                "product_id": str(ctx["part_product_id"]),
                "requested_qty": part_qty,
            },
        ],
    }


def _create(
    client: TestClient,
    headers: dict[str, str],
    ctx: dict[str, Any],
    *,
    part_qty: int = 2,
) -> dict[str, Any]:
    r = client.post(
        f"{PREFIX}/project-pulls",
        headers=headers,
        json=_create_body(ctx, part_qty=part_qty),
    )
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def test_admin_creates_pull_pending(
    client: TestClient, superuser_token_headers: dict[str, str], pull_ctx: dict[str, Any]
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx)
    assert pull["state"] == "PENDING"
    assert len(pull["lines"]) == 2
    assert all(line["line_state"] == "PENDING" for line in pull["lines"])


def test_staff_cannot_create_pull_403(
    client: TestClient, staff_token_headers: dict[str, str], pull_ctx: dict[str, Any]
) -> None:
    r = client.post(
        f"{PREFIX}/project-pulls",
        headers=staff_token_headers,
        json=_create_body(pull_ctx),
    )
    assert r.status_code == 403


def test_create_tracking_mismatch_400_no_orphan_pull(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    pull_ctx: dict[str, Any],
) -> None:
    # UNIT line pointing at the QUANTITY product -> 400, whole create rolls back.
    before = len(db.exec(select(ProjectPull)).all())
    r = client.post(
        f"{PREFIX}/project-pulls",
        headers=superuser_token_headers,
        json={
            "project_id": str(pull_ctx["project_id"]),
            "lines": [
                {
                    "line_kind": "UNIT",
                    "product_id": str(pull_ctx["part_product_id"]),
                    "unit_serial": "CN-DOESNOTMATTER",
                }
            ],
        },
    )
    assert r.status_code == 400
    db.expire_all()
    assert len(db.exec(select(ProjectPull)).all()) == before  # no orphan pull


def test_fulfill_absent_lines_default_to_requested(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    pull_ctx: dict[str, Any],
) -> None:
    # Empty fulfill body -> UNIT defaults to 1, PART defaults to requested_qty.
    pull = _create(client, superuser_token_headers, pull_ctx, part_qty=2)
    r = client.post(
        f"{PREFIX}/project-pulls/{pull['id']}/fulfill",
        headers=staff_token_headers,
        json={"lines": []},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["state"] == "FULFILLED"
    part_line = next(ln for ln in out["lines"] if ln["line_kind"] == "PART")
    assert part_line["fulfilled_qty"] == 2


def test_staff_queue_lists_pending(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    pull_ctx: dict[str, Any],
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx)
    r = client.get(
        f"{PREFIX}/project-pulls?state=PENDING", headers=staff_token_headers
    )
    assert r.status_code == 200, r.text
    ids = [p["id"] for p in r.json()]
    assert pull["id"] in ids


def test_staff_can_read_pull(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    pull_ctx: dict[str, Any],
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx)
    r = client.get(
        f"{PREFIX}/project-pulls/{pull['id']}", headers=staff_token_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == pull["id"]


def test_staff_pull_carries_display_labels(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    pull_ctx: dict[str, Any],
) -> None:
    # Staff can't list projects (admin-only), so the pull payload must carry the
    # project/customer display labels itself. No financial keys may leak.
    pull = _create(client, superuser_token_headers, pull_ctx)
    r = client.get(
        f"{PREFIX}/project-pulls?state=PENDING", headers=staff_token_headers
    )
    assert r.status_code == 200, r.text
    row = next(p for p in r.json() if p["id"] == pull["id"])
    assert row["project_name"] == "Site A"
    assert row["project_code"].startswith("PRJ-")
    assert row["customer_name"] == "Proj Cust"
    assert_no_financial_keys(row)


def test_fulfill_all_marks_fulfilled(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
    pull_ctx: dict[str, Any],
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx, part_qty=2)
    line_ids = {ln["line_kind"]: ln["id"] for ln in pull["lines"]}
    r = client.post(
        f"{PREFIX}/project-pulls/{pull['id']}/fulfill",
        headers=staff_token_headers,
        json={
            "lines": [
                {"line_id": line_ids["UNIT"], "fulfilled_qty": 1},
                {"line_id": line_ids["PART"], "fulfilled_qty": 2},
            ]
        },
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["state"] == "FULFILLED"
    assert all(ln["line_state"] == "FULFILLED" for ln in out["lines"])

    db.expire_all()
    staff = crud.get_user_by_email(session=db, email="staff@example.com")
    assert staff is not None
    pull_row = db.get(ProjectPull, uuid.UUID(pull["id"]))
    assert pull_row is not None
    assert pull_row.fulfilled_by_user_id == staff.id
    assert pull_row.fulfilled_at is not None

    # UNIT line: unit flipped to PROJECT_OUT + a PROJECT_OUT unit_movement.
    unit = db.exec(
        select(Unit).where(Unit.castranova_barcode == pull_ctx["barcode"])
    ).first()
    assert unit is not None and unit.current_state == UnitState.PROJECT_OUT
    umoves = db.exec(
        select(UnitMovement).where(
            UnitMovement.unit_id == unit.id,
            UnitMovement.event_type == MovementType.PROJECT_OUT,
        )
    ).all()
    assert len(umoves) == 1
    assert umoves[0].project_pull_id == pull_row.id
    assert umoves[0].actor_user_id == staff.id

    # PART line: one PROJECT_OUT part_movement + balanced cost_lines.
    pmoves = db.exec(
        select(PartMovement).where(
            PartMovement.product_id == pull_ctx["part_product_id"],
            PartMovement.event_type == MovementType.PROJECT_OUT,
        )
    ).all()
    assert len(pmoves) == 1 and pmoves[0].quantity == 2
    assert pmoves[0].project_pull_id == pull_row.id
    cost_lines = db.exec(
        select(CostLine).where(CostLine.part_movement_id == pmoves[0].id)
    ).all()
    assert sum(c.quantity for c in cost_lines) == 2
    assert sum(c.total_cost_thb for c in cost_lines) == Decimal("20.00")


def test_partial_part_marks_line_and_pull_short(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
    pull_ctx: dict[str, Any],
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx, part_qty=5)
    line_ids = {ln["line_kind"]: ln["id"] for ln in pull["lines"]}
    r = client.post(
        f"{PREFIX}/project-pulls/{pull['id']}/fulfill",
        headers=staff_token_headers,
        json={
            "lines": [
                {"line_id": line_ids["UNIT"], "fulfilled_qty": 1},
                {"line_id": line_ids["PART"], "fulfilled_qty": 3},  # < 5 requested
            ]
        },
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["state"] == "SHORT"
    part_line = next(ln for ln in out["lines"] if ln["line_kind"] == "PART")
    assert part_line["line_state"] == "SHORT"
    assert part_line["fulfilled_qty"] == 3

    db.expire_all()
    pmoves = db.exec(
        select(PartMovement).where(
            PartMovement.product_id == pull_ctx["part_product_id"],
            PartMovement.event_type == MovementType.PROJECT_OUT,
        )
    ).all()
    assert len(pmoves) == 1 and pmoves[0].quantity == 3
    cost_lines = db.exec(
        select(CostLine).where(CostLine.part_movement_id == pmoves[0].id)
    ).all()
    assert sum(c.quantity for c in cost_lines) == 3


def test_unit_race_line_short(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
    pull_ctx: dict[str, Any],
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx, part_qty=2)
    line_ids = {ln["line_kind"]: ln["id"] for ln in pull["lines"]}
    # Pre-sell the unit so it is SOLD (lost the race).
    crud.create_sale(
        session=db,
        customer_id=pull_ctx["customer_id"],
        lines=[
            SaleLineInput(
                line_kind=SaleLineKind.UNIT, castranova_barcode=pull_ctx["barcode"]
            )
        ],
        idempotency_key=uuid.uuid4(),
        created_by_user_id=pull_ctx["admin_id"],
    )
    r = client.post(
        f"{PREFIX}/project-pulls/{pull['id']}/fulfill",
        headers=staff_token_headers,
        json={
            "lines": [
                {"line_id": line_ids["UNIT"], "fulfilled_qty": 1},
                {"line_id": line_ids["PART"], "fulfilled_qty": 2},
            ]
        },
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["state"] == "SHORT"
    unit_line = next(ln for ln in out["lines"] if ln["line_kind"] == "UNIT")
    assert unit_line["line_state"] == "SHORT"
    assert unit_line["fulfilled_qty"] == 0

    db.expire_all()
    unit = db.exec(
        select(Unit).where(Unit.castranova_barcode == pull_ctx["barcode"])
    ).first()
    assert unit is not None and unit.current_state == UnitState.SOLD
    assert not db.exec(
        select(UnitMovement).where(
            UnitMovement.unit_id == unit.id,
            UnitMovement.event_type == MovementType.PROJECT_OUT,
        )
    ).all()


def test_refulfill_is_idempotent(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
    pull_ctx: dict[str, Any],
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx, part_qty=2)
    line_ids = {ln["line_kind"]: ln["id"] for ln in pull["lines"]}
    body = {
        "lines": [
            {"line_id": line_ids["UNIT"], "fulfilled_qty": 1},
            {"line_id": line_ids["PART"], "fulfilled_qty": 2},
        ]
    }
    client.post(
        f"{PREFIX}/project-pulls/{pull['id']}/fulfill",
        headers=staff_token_headers,
        json=body,
    )
    db.expire_all()
    # Scope counts to this test's product so sibling tests (session-scoped db)
    # don't float the baseline.
    pid = pull_ctx["part_product_id"]
    cost_q = (
        select(CostLine)
        .join(PartMovement, col(CostLine.part_movement_id) == col(PartMovement.id))
        .where(PartMovement.product_id == pid)
    )
    pmove_q = select(PartMovement).where(
        PartMovement.product_id == pid,
        PartMovement.event_type == MovementType.PROJECT_OUT,
    )
    cost_before = len(db.exec(cost_q).all())
    pmoves_before = len(db.exec(pmove_q).all())
    r2 = client.post(
        f"{PREFIX}/project-pulls/{pull['id']}/fulfill",
        headers=staff_token_headers,
        json=body,
    )
    assert r2.status_code == 200
    assert r2.json()["state"] == "FULFILLED"
    db.expire_all()
    assert len(db.exec(cost_q).all()) == cost_before
    assert len(db.exec(pmove_q).all()) == pmoves_before


def test_cancel_pending_pull(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    pull_ctx: dict[str, Any],
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx)
    r = client.post(
        f"{PREFIX}/project-pulls/{pull['id']}/cancel",
        headers=superuser_token_headers,
        json={},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["state"] == "CANCELLED"
    assert all(ln["line_state"] == "CANCELLED" for ln in out["lines"])
    db.expire_all()
    assert not db.exec(
        select(PartMovement).where(
            PartMovement.product_id == pull_ctx["part_product_id"],
            PartMovement.event_type == MovementType.PROJECT_OUT,
        )
    ).all()


def test_cancel_short_pull(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    pull_ctx: dict[str, Any],
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx, part_qty=5)
    line_ids = {ln["line_kind"]: ln["id"] for ln in pull["lines"]}
    client.post(
        f"{PREFIX}/project-pulls/{pull['id']}/fulfill",
        headers=staff_token_headers,
        json={
            "lines": [
                {"line_id": line_ids["UNIT"], "fulfilled_qty": 1},
                {"line_id": line_ids["PART"], "fulfilled_qty": 3},
            ]
        },
    )
    r = client.post(
        f"{PREFIX}/project-pulls/{pull['id']}/cancel",
        headers=superuser_token_headers,
        json={},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["state"] == "CANCELLED"
    # Cancel only flips still-PENDING lines; lines whose stock already moved keep
    # their settled state.
    unit_line = next(ln for ln in out["lines"] if ln["line_kind"] == "UNIT")
    part_line = next(ln for ln in out["lines"] if ln["line_kind"] == "PART")
    assert unit_line["line_state"] == "FULFILLED"
    assert part_line["line_state"] == "SHORT"


def test_staff_cannot_cancel_403(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    pull_ctx: dict[str, Any],
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx)
    r = client.post(
        f"{PREFIX}/project-pulls/{pull['id']}/cancel",
        headers=staff_token_headers,
        json={},
    )
    assert r.status_code == 403


def test_cancel_fulfilled_pull_409(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    pull_ctx: dict[str, Any],
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx, part_qty=2)
    line_ids = {ln["line_kind"]: ln["id"] for ln in pull["lines"]}
    client.post(
        f"{PREFIX}/project-pulls/{pull['id']}/fulfill",
        headers=staff_token_headers,
        json={
            "lines": [
                {"line_id": line_ids["UNIT"], "fulfilled_qty": 1},
                {"line_id": line_ids["PART"], "fulfilled_qty": 2},
            ]
        },
    )
    r = client.post(
        f"{PREFIX}/project-pulls/{pull['id']}/cancel",
        headers=superuser_token_headers,
        json={},
    )
    assert r.status_code == 409


def test_insufficient_stock_409_nothing_written(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
    pull_ctx: dict[str, Any],
) -> None:
    # requested 7 (all stock), fulfill 100 -> capped to 7 but only 7 in stock is
    # fine; instead request beyond stock: requested 100, fulfill 100 -> 409.
    pull = _create(client, superuser_token_headers, pull_ctx, part_qty=100)
    line_ids = {ln["line_kind"]: ln["id"] for ln in pull["lines"]}
    r = client.post(
        f"{PREFIX}/project-pulls/{pull['id']}/fulfill",
        headers=staff_token_headers,
        json={
            "lines": [
                {"line_id": line_ids["UNIT"], "fulfilled_qty": 1},
                {"line_id": line_ids["PART"], "fulfilled_qty": 100},  # only 7 in stock
            ]
        },
    )
    assert r.status_code == 409
    db.expire_all()
    pull_row = db.get(ProjectPull, uuid.UUID(pull["id"]))
    assert pull_row is not None and pull_row.state == ProjectPullState.PENDING
    assert not db.exec(
        select(PartMovement).where(
            PartMovement.product_id == pull_ctx["part_product_id"],
            PartMovement.event_type == MovementType.PROJECT_OUT,
        )
    ).all()
    # The unit must not have been consumed either (whole txn rolled back).
    unit = db.exec(
        select(Unit).where(Unit.castranova_barcode == pull_ctx["barcode"])
    ).first()
    assert unit is not None and unit.current_state == UnitState.IN_STOCK


def test_dual_audit_admin_recovered_via_join(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
    pull_ctx: dict[str, Any],
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx, part_qty=2)
    line_ids = {ln["line_kind"]: ln["id"] for ln in pull["lines"]}
    client.post(
        f"{PREFIX}/project-pulls/{pull['id']}/fulfill",
        headers=staff_token_headers,
        json={
            "lines": [
                {"line_id": line_ids["UNIT"], "fulfilled_qty": 1},
                {"line_id": line_ids["PART"], "fulfilled_qty": 2},
            ]
        },
    )
    db.expire_all()
    staff = crud.get_user_by_email(session=db, email="staff@example.com")
    assert staff is not None
    pmove = db.exec(
        select(PartMovement).where(
            PartMovement.product_id == pull_ctx["part_product_id"],
            PartMovement.event_type == MovementType.PROJECT_OUT,
        )
    ).first()
    assert pmove is not None
    # Movement actor is the staff fulfiller.
    assert pmove.actor_user_id == staff.id
    # The admin creator is recovered by joining via project_pull_id.
    pull_row = db.get(ProjectPull, pmove.project_pull_id)
    assert pull_row is not None
    assert pull_row.created_by_user_id == pull_ctx["admin_id"]


def test_fulfill_unauthenticated_401(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    pull_ctx: dict[str, Any],
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx, part_qty=2)
    r = client.post(
        f"{PREFIX}/project-pulls/{pull['id']}/fulfill", json={"lines": []}
    )
    assert r.status_code == 401


def _assert_pull_untouched(db: Session, pull_id: str, part_product_id: uuid.UUID) -> None:
    db.expire_all()
    pull_row = db.get(ProjectPull, uuid.UUID(pull_id))
    assert pull_row is not None and pull_row.state == ProjectPullState.PENDING
    assert not db.exec(
        select(PartMovement).where(
            PartMovement.product_id == part_product_id,
            PartMovement.event_type == MovementType.PROJECT_OUT,
        )
    ).all()


def test_fulfill_unknown_line_id_422(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
    pull_ctx: dict[str, Any],
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx, part_qty=2)
    r = client.post(
        f"{PREFIX}/project-pulls/{pull['id']}/fulfill",
        headers=staff_token_headers,
        json={"lines": [{"line_id": str(uuid.uuid4()), "fulfilled_qty": 1}]},
    )
    assert r.status_code == 422
    _assert_pull_untouched(db, pull["id"], pull_ctx["part_product_id"])


def test_fulfill_duplicate_line_id_422(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
    pull_ctx: dict[str, Any],
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx, part_qty=2)
    part_id = next(ln["id"] for ln in pull["lines"] if ln["line_kind"] == "PART")
    r = client.post(
        f"{PREFIX}/project-pulls/{pull['id']}/fulfill",
        headers=staff_token_headers,
        json={
            "lines": [
                {"line_id": part_id, "fulfilled_qty": 1},
                {"line_id": part_id, "fulfilled_qty": 2},
            ]
        },
    )
    assert r.status_code == 422
    _assert_pull_untouched(db, pull["id"], pull_ctx["part_product_id"])
