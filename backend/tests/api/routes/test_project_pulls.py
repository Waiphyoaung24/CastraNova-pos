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
    LineState,
    Location,
    MovementType,
    PartBatch,
    PartMovement,
    ProductCreate,
    ProjectCreate,
    ProjectPull,
    ProjectPullLine,
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
from app.services import notify
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


def _legacy_pull(db: Session, ctx: dict[str, Any], *, part_qty: int = 2) -> ProjectPull:
    """A PENDING pull whose stock was NOT deducted at create — the shape every
    pull had before create started deducting. Inserted directly so the
    at-fulfill deduction path stays covered for rows that predate the change."""
    pull = ProjectPull(
        project_id=ctx["project_id"],
        customer_id=ctx["customer_id"],
        created_by_user_id=ctx["admin_id"],
    )
    db.add(pull)
    db.flush()
    db.add(
        ProjectPullLine(
            project_pull_id=pull.id,
            line_kind=SaleLineKind.UNIT,
            product_id=ctx["serialized_product_id"],
            unit_serial=ctx["barcode"],
        )
    )
    db.add(
        ProjectPullLine(
            project_pull_id=pull.id,
            line_kind=SaleLineKind.PART,
            product_id=ctx["part_product_id"],
            requested_qty=part_qty,
        )
    )
    db.commit()
    db.refresh(pull)
    return pull


def _line_ids(db: Session, pull_id: uuid.UUID) -> dict[str, str]:
    return {
        ln.line_kind.value: str(ln.id)
        for ln in crud.list_project_pull_lines(session=db, pull_id=pull_id)
    }


def _part_moves(db: Session, ctx: dict[str, Any]) -> list[PartMovement]:
    return list(
        db.exec(
            select(PartMovement).where(
                PartMovement.product_id == ctx["part_product_id"],
                PartMovement.event_type == MovementType.PROJECT_OUT,
            )
        ).all()
    )


def _unit(db: Session, ctx: dict[str, Any]) -> Unit:
    unit = db.exec(
        select(Unit).where(Unit.castranova_barcode == ctx["barcode"])
    ).first()
    assert unit is not None
    return unit


def test_create_deducts_stock_and_stays_pending(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    pull_ctx: dict[str, Any],
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx, part_qty=2)
    assert pull["state"] == "PENDING"
    assert pull["stock_deducted"] is True
    assert len(pull["lines"]) == 2
    # Lines still wait for the hand-out even though the stock is already gone.
    assert all(line["line_state"] == "PENDING" for line in pull["lines"])
    assert all(line["fulfilled_qty"] == 0 for line in pull["lines"])

    db.expire_all()
    unit = _unit(db, pull_ctx)
    assert unit.current_state == UnitState.PROJECT_OUT
    umoves = db.exec(
        select(UnitMovement).where(
            UnitMovement.unit_id == unit.id,
            UnitMovement.event_type == MovementType.PROJECT_OUT,
        )
    ).all()
    assert len(umoves) == 1
    assert umoves[0].project_pull_id == uuid.UUID(pull["id"])
    assert umoves[0].actor_user_id == pull_ctx["admin_id"]

    pmoves = _part_moves(db, pull_ctx)
    assert len(pmoves) == 1 and pmoves[0].quantity == 2
    assert pmoves[0].project_pull_id == uuid.UUID(pull["id"])
    assert pmoves[0].actor_user_id == pull_ctx["admin_id"]
    cost_lines = db.exec(
        select(CostLine).where(CostLine.part_movement_id == pmoves[0].id)
    ).all()
    assert sum(c.quantity for c in cost_lines) == 2
    assert sum(c.total_cost_thb for c in cost_lines) == Decimal("20.00")


def test_create_insufficient_part_stock_409_nothing_written(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    pull_ctx: dict[str, Any],
) -> None:
    before = len(db.exec(select(ProjectPull)).all())
    r = client.post(
        f"{PREFIX}/project-pulls",
        headers=superuser_token_headers,
        json=_create_body(pull_ctx, part_qty=100),  # only 7 in stock
    )
    assert r.status_code == 409, r.text
    db.expire_all()
    assert len(db.exec(select(ProjectPull)).all()) == before
    assert _part_moves(db, pull_ctx) == []
    # The unit line came first; the whole txn rolled back so it is untouched.
    assert _unit(db, pull_ctx).current_state == UnitState.IN_STOCK


def test_create_unit_not_in_stock_409_nothing_written(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    pull_ctx: dict[str, Any],
) -> None:
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
    before = len(db.exec(select(ProjectPull)).all())
    r = client.post(
        f"{PREFIX}/project-pulls",
        headers=superuser_token_headers,
        json=_create_body(pull_ctx, part_qty=2),
    )
    assert r.status_code == 409, r.text
    db.expire_all()
    assert len(db.exec(select(ProjectPull)).all()) == before
    assert _part_moves(db, pull_ctx) == []
    assert _unit(db, pull_ctx).current_state == UnitState.SOLD


def test_fulfill_deducted_pull_moves_no_stock(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
    pull_ctx: dict[str, Any],
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx, part_qty=2)
    line_ids = {ln["line_kind"]: ln["id"] for ln in pull["lines"]}
    db.expire_all()
    pmoves_before = len(_part_moves(db, pull_ctx))
    umoves_before = len(db.exec(select(UnitMovement)).all())
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
    assert r.json()["state"] == "FULFILLED"
    db.expire_all()
    assert len(_part_moves(db, pull_ctx)) == pmoves_before
    assert len(db.exec(select(UnitMovement)).all()) == umoves_before


def test_legacy_pull_deducts_at_fulfill(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
    pull_ctx: dict[str, Any],
) -> None:
    pull = _legacy_pull(db, pull_ctx, part_qty=2)
    r = client.get(f"{PREFIX}/project-pulls/{pull.id}", headers=staff_token_headers)
    assert r.status_code == 200, r.text
    assert r.json()["stock_deducted"] is False
    assert _part_moves(db, pull_ctx) == []

    r = client.post(
        f"{PREFIX}/project-pulls/{pull.id}/fulfill",
        headers=staff_token_headers,
        json={"lines": []},
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "FULFILLED"
    assert r.json()["stock_deducted"] is True
    db.expire_all()
    staff = crud.get_user_by_email(session=db, email="staff@example.com")
    assert staff is not None
    pmoves = _part_moves(db, pull_ctx)
    assert len(pmoves) == 1 and pmoves[0].quantity == 2
    assert pmoves[0].actor_user_id == staff.id
    assert _unit(db, pull_ctx).current_state == UnitState.PROJECT_OUT


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


def test_full_fulfill_schedules_fulfilled_notification(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    pull_ctx: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # FR-018: a fully-fulfilled pull schedules the FULFILLED notification and not
    # the SHORT one. TestClient runs background tasks after the response.
    calls: dict[str, list[uuid.UUID]] = {"fulfilled": [], "short": []}
    monkeypatch.setattr(
        notify,
        "notify_pull_fulfilled_bg",
        lambda *, pull_id: calls["fulfilled"].append(pull_id),
    )
    monkeypatch.setattr(
        notify,
        "notify_pull_short_bg",
        lambda *, pull_id: calls["short"].append(pull_id),
    )
    pull = _create(client, superuser_token_headers, pull_ctx, part_qty=2)
    r = client.post(
        f"{PREFIX}/project-pulls/{pull['id']}/fulfill",
        headers=staff_token_headers,
        json={"lines": []},
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "FULFILLED"
    assert calls["fulfilled"] == [uuid.UUID(pull["id"])]
    assert calls["short"] == []


def test_short_fulfill_does_not_schedule_fulfilled_notification(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    pull_ctx: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # FR-018: a short pull keeps firing SHORT only — never the FULFILLED event.
    calls: dict[str, list[uuid.UUID]] = {"fulfilled": [], "short": []}
    monkeypatch.setattr(
        notify,
        "notify_pull_fulfilled_bg",
        lambda *, pull_id: calls["fulfilled"].append(pull_id),
    )
    monkeypatch.setattr(
        notify,
        "notify_pull_short_bg",
        lambda *, pull_id: calls["short"].append(pull_id),
    )
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
    assert r.json()["state"] == "SHORT"
    assert calls["short"] == [uuid.UUID(pull["id"])]
    assert calls["fulfilled"] == []


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
    ids = [p["id"] for p in r.json()["data"]]
    assert pull["id"] in ids


def test_list_filters_by_project(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    pull_ctx: dict[str, Any],
) -> None:
    # Project history: staff and admin list one project's pulls, any state.
    pull = _create(client, superuser_token_headers, pull_ctx)
    other = crud.create_project(
        session=db,
        project_in=ProjectCreate(
            code=f"PRJ-{uuid.uuid4().hex[:8]}",
            name="Site B",
            customer_id=pull_ctx["customer_id"],
        ),
    )
    r = client.get(
        f"{PREFIX}/project-pulls?project_id={pull_ctx['project_id']}",
        headers=staff_token_headers,
    )
    assert r.status_code == 200, r.text
    assert [p["id"] for p in r.json()["data"]] == [pull["id"]]
    assert r.json()["count"] == 1
    r = client.get(
        f"{PREFIX}/project-pulls?project_id={other.id}",
        headers=staff_token_headers,
    )
    assert r.json() == {"data": [], "count": 0}


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
    row = next(p for p in r.json()["data"] if p["id"] == pull["id"])
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
    # Stock moved at create, so the movement actor is the admin creator; the
    # staff hand-out is recorded on the pull (fulfilled_by_user_id above).
    assert umoves[0].actor_user_id == pull_ctx["admin_id"]

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
    # All 5 left stock at create; the short hand-out does not put 2 back.
    assert len(pmoves) == 1 and pmoves[0].quantity == 5
    cost_lines = db.exec(
        select(CostLine).where(CostLine.part_movement_id == pmoves[0].id)
    ).all()
    assert sum(c.quantity for c in cost_lines) == 5


def test_legacy_unit_race_line_short(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
    pull_ctx: dict[str, Any],
) -> None:
    # Only an undeducted (legacy) pull can lose its unit to a sale: a created
    # pull already holds the unit as PROJECT_OUT.
    pull_row = _legacy_pull(db, pull_ctx, part_qty=2)
    pull = {"id": str(pull_row.id)}
    line_ids = _line_ids(db, pull_row.id)
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


def test_cancel_deducted_pending_pull_restores_stock(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    pull_ctx: dict[str, Any],
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx, part_qty=5)
    r = client.post(
        f"{PREFIX}/project-pulls/{pull['id']}/cancel",
        headers=superuser_token_headers,
        json={},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "CANCELLED"
    assert all(ln["returnable_qty"] == 0 for ln in body["lines"])
    assert all(ln["line_state"] == "CANCELLED" for ln in body["lines"])
    db.expire_all()
    assert _unit(db, pull_ctx).current_state == UnitState.IN_STOCK
    batches = db.exec(
        select(PartBatch)
        .where(PartBatch.product_id == pull_ctx["part_product_id"])
        .order_by(col(PartBatch.received_at), col(PartBatch.id))
    ).all()
    assert [b.remaining_qty for b in batches] == [3, 4]  # all back
    # Cancel twice is still idempotent: no second reversal.
    again = client.post(
        f"{PREFIX}/project-pulls/{pull['id']}/cancel",
        headers=superuser_token_headers,
        json={},
    )
    assert again.status_code == 200
    rets = db.exec(
        select(PartMovement).where(
            PartMovement.project_pull_id == uuid.UUID(pull["id"]),
            PartMovement.event_type == MovementType.RETURNED,
        )
    ).all()
    assert len(rets) == 1


def test_cancel_legacy_pending_pull(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    pull_ctx: dict[str, Any],
) -> None:
    pull = {"id": str(_legacy_pull(db, pull_ctx).id)}
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


def test_legacy_insufficient_stock_409_nothing_written(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
    pull_ctx: dict[str, Any],
) -> None:
    # A created pull can never request beyond stock (create 409s); only a legacy
    # undeducted pull can still hit insufficient stock at fulfill.
    pull_row = _legacy_pull(db, pull_ctx, part_qty=100)
    pull = {"id": str(pull_row.id)}
    line_ids = _line_ids(db, pull_row.id)
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
    # Movement actor is the admin who created (and thereby deducted) the pull.
    assert pmove.actor_user_id == pull_ctx["admin_id"]
    # The staff hand-out is recovered by joining via project_pull_id.
    pull_row = db.get(ProjectPull, pmove.project_pull_id)
    assert pull_row is not None
    assert pull_row.created_by_user_id == pull_ctx["admin_id"]
    assert pull_row.fulfilled_by_user_id == staff.id


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
    for ln in crud.list_project_pull_lines(session=db, pull_id=pull_row.id):
        assert ln.line_state == LineState.PENDING and ln.fulfilled_qty == 0
    # Exactly the create-time deduction, nothing more.
    assert (
        len(
            db.exec(
                select(PartMovement).where(
                    PartMovement.product_id == part_product_id,
                    PartMovement.event_type == MovementType.PROJECT_OUT,
                )
            ).all()
        )
        == 1
    )


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


def test_create_rejects_two_part_lines_for_one_product_422(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    pull_ctx: dict[str, Any],
) -> None:
    before = len(db.exec(select(ProjectPull)).all())
    part = {
        "line_kind": "PART",
        "product_id": str(pull_ctx["part_product_id"]),
        "requested_qty": 1,
    }
    r = client.post(
        f"{PREFIX}/project-pulls",
        headers=superuser_token_headers,
        json={"project_id": str(pull_ctx["project_id"]), "lines": [part, part]},
    )
    assert r.status_code == 422, r.text
    db.expire_all()
    assert len(db.exec(select(ProjectPull)).all()) == before


def test_new_pull_lines_are_fully_returnable(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    pull_ctx: dict[str, Any],
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx, part_qty=2)
    by_kind = {ln["line_kind"]: ln for ln in pull["lines"]}
    assert by_kind["UNIT"]["returnable_qty"] == 1
    assert by_kind["PART"]["returnable_qty"] == 2


def test_legacy_pending_pull_has_nothing_returnable(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    pull_ctx: dict[str, Any],
) -> None:
    pull = _legacy_pull(db, pull_ctx)
    r = client.get(
        f"{PREFIX}/project-pulls/{pull.id}", headers=superuser_token_headers
    )
    assert r.status_code == 200, r.text
    assert all(ln["returnable_qty"] == 0 for ln in r.json()["lines"])
