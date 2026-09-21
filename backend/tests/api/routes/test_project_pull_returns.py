# ruff: noqa: F811  (pull_ctx is an imported pytest fixture)
import uuid
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session, col, select

from app import crud
from app.core.config import settings
from app.models import (
    CostLine,
    MovementType,
    PartBatch,
    PartMovement,
    Product,
    ProjectPull,
    ProjectPullFulfillLine,
    ProjectPullState,
    UnitMovement,
    UnitState,
)
from tests.api.routes.test_project_pulls import (  # noqa: F401  (pull_ctx is a fixture)
    _create,
    _legacy_pull,
    _line_ids,
    _unit,
    pull_ctx,
)

PREFIX = settings.API_V1_STR


def _settle(db: Session, pull_id: str, ctx: dict[str, Any]) -> None:
    """Hand out everything so the pull is FULFILLED (returns need a settled pull)."""
    crud.fulfill_project_pull(
        session=db, pull_id=uuid.UUID(pull_id), fulfill_lines=[], actor_user_id=ctx["admin_id"]
    )


def _return(
    client: TestClient,
    headers: dict[str, str],
    pull_id: str,
    lines: list[tuple[str, int]],
    key: uuid.UUID | None = None,
) -> Any:
    return client.post(
        f"{PREFIX}/project-pulls/{pull_id}/returns",
        headers=headers,
        json={
            "idempotency_key": str(key or uuid.uuid4()),
            "lines": [{"line_id": lid, "quantity": q} for lid, q in lines],
        },
    )


def _batches(db: Session, ctx: dict[str, Any]) -> list[int]:
    """remaining_qty per batch, oldest first (3@10 then 4@12 in pull_ctx)."""
    return [
        b.remaining_qty
        for b in db.exec(
            select(PartBatch)
            .where(PartBatch.product_id == ctx["part_product_id"])
            .order_by(col(PartBatch.received_at), col(PartBatch.id))
        ).all()
    ]


def test_unit_return_round_trip(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session, pull_ctx: dict[str, Any]
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx)
    _settle(db, pull["id"], pull_ctx)
    ids = _line_ids(db, uuid.UUID(pull["id"]))
    r = _return(client, superuser_token_headers, pull["id"], [(ids["UNIT"], 1)])
    assert r.status_code == 200, r.text
    unit_line = next(ln for ln in r.json()["lines"] if ln["line_kind"] == "UNIT")
    assert unit_line["returnable_qty"] == 0
    db.expire_all()
    unit = _unit(db, pull_ctx)
    assert unit.current_state == UnitState.IN_STOCK
    ret = db.exec(
        select(UnitMovement).where(
            UnitMovement.unit_id == unit.id, UnitMovement.event_type == MovementType.RETURNED
        )
    ).one()
    assert ret.project_pull_id == uuid.UUID(pull["id"]) and ret.sale_id is None
    out = db.exec(
        select(UnitMovement).where(
            UnitMovement.unit_id == unit.id, UnitMovement.event_type == MovementType.PROJECT_OUT
        )
    ).one()
    assert ret.to_location_id == out.from_location_id  # back where it left from
    # Pull history is untouched: still FULFILLED, still "given out 1".
    assert r.json()["state"] == "FULFILLED"
    assert unit_line["fulfilled_qty"] == 1


def test_part_partial_returns_restore_exact_batches(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session, pull_ctx: dict[str, Any]
) -> None:
    # 5 out of 3@10 + 4@12 draws 3@10 + 2@12 → batches [0, 2].
    pull = _create(client, superuser_token_headers, pull_ctx, part_qty=5)
    _settle(db, pull["id"], pull_ctx)
    assert _batches(db, pull_ctx) == [0, 2]
    ids = _line_ids(db, uuid.UUID(pull["id"]))

    # Return 3: newest batch first → 2@12, then 1@10.
    r = _return(client, superuser_token_headers, pull["id"], [(ids["PART"], 3)])
    assert r.status_code == 200, r.text
    db.expire_all()
    assert _batches(db, pull_ctx) == [1, 4]
    ret = db.exec(
        select(PartMovement).where(
            PartMovement.project_pull_id == uuid.UUID(pull["id"]),
            PartMovement.event_type == MovementType.RETURNED,
        )
    ).one()
    restored = db.exec(select(CostLine).where(CostLine.part_movement_id == ret.id)).all()
    assert sum(c.total_cost_thb for c in restored) == Decimal("34.00")  # 2*12 + 1*10

    # Return the last 2: skips what came back already → both from batch 1.
    r = _return(client, superuser_token_headers, pull["id"], [(ids["PART"], 2)])
    assert r.status_code == 200, r.text
    db.expire_all()
    assert _batches(db, pull_ctx) == [3, 4]
    part_line = next(ln for ln in r.json()["lines"] if ln["line_kind"] == "PART")
    assert part_line["returnable_qty"] == 0


def test_over_return_409_nothing_written(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session, pull_ctx: dict[str, Any]
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx, part_qty=2)
    _settle(db, pull["id"], pull_ctx)
    ids = _line_ids(db, uuid.UUID(pull["id"]))
    r = _return(client, superuser_token_headers, pull["id"], [(ids["PART"], 3)])
    assert r.status_code == 409, r.text
    db.expire_all()
    assert _batches(db, pull_ctx) == [1, 4]  # 2 still out, untouched


def test_pending_pull_return_409_use_cancel(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session, pull_ctx: dict[str, Any]
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx)
    ids = _line_ids(db, uuid.UUID(pull["id"]))
    r = _return(client, superuser_token_headers, pull["id"], [(ids["PART"], 1)])
    assert r.status_code == 409, r.text
    assert "Cancel" in r.json()["detail"]


def test_replay_same_key_no_double_credit(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session, pull_ctx: dict[str, Any]
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx, part_qty=4)
    _settle(db, pull["id"], pull_ctx)
    ids = _line_ids(db, uuid.UUID(pull["id"]))
    key = uuid.uuid4()
    first = _return(client, superuser_token_headers, pull["id"], [(ids["PART"], 1)], key)
    second = _return(client, superuser_token_headers, pull["id"], [(ids["PART"], 1)], key)
    assert first.status_code == 200 and second.status_code == 200, second.text
    db.expire_all()
    rets = db.exec(
        select(PartMovement).where(
            PartMovement.project_pull_id == uuid.UUID(pull["id"]),
            PartMovement.event_type == MovementType.RETURNED,
        )
    ).all()
    assert len(rets) == 1


def test_replay_by_other_user_409(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
    pull_ctx: dict[str, Any],
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx)
    _settle(db, pull["id"], pull_ctx)
    ids = _line_ids(db, uuid.UUID(pull["id"]))
    key = uuid.uuid4()
    assert _return(client, superuser_token_headers, pull["id"], [(ids["PART"], 1)], key).status_code == 200
    r = _return(client, staff_token_headers, pull["id"], [(ids["PART"], 1)], key)
    assert r.status_code == 409, r.text
    assert "different user" in r.json()["detail"]


def test_key_reused_on_other_pull_409(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session, pull_ctx: dict[str, Any]
) -> None:
    a = _create(client, superuser_token_headers, pull_ctx, part_qty=1)
    _settle(db, a["id"], pull_ctx)
    ids_a = _line_ids(db, uuid.UUID(a["id"]))
    key = uuid.uuid4()
    assert _return(client, superuser_token_headers, a["id"], [(ids_a["PART"], 1)], key).status_code == 200
    # Same key + same line id against another pull: the derived movement key
    # already exists and belongs to pull A.
    b = _legacy_pull(db, pull_ctx)
    r = _return(client, superuser_token_headers, str(b.id), [(ids_a["PART"], 1)], key)
    assert r.status_code == 409, r.text


def test_staff_can_return(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
    pull_ctx: dict[str, Any],
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx)
    _settle(db, pull["id"], pull_ctx)
    ids = _line_ids(db, uuid.UUID(pull["id"]))
    r = _return(client, staff_token_headers, pull["id"], [(ids["PART"], 1)])
    assert r.status_code == 200, r.text


def test_return_validation_422(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session, pull_ctx: dict[str, Any]
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx)
    _settle(db, pull["id"], pull_ctx)
    ids = _line_ids(db, uuid.UUID(pull["id"]))
    zero = _return(client, superuser_token_headers, pull["id"], [(ids["PART"], 0)])
    dup = _return(client, superuser_token_headers, pull["id"], [(ids["PART"], 1), (ids["PART"], 1)])
    unknown = _return(client, superuser_token_headers, pull["id"], [(str(uuid.uuid4()), 1)])
    empty = _return(client, superuser_token_headers, pull["id"], [])
    assert [zero.status_code, dup.status_code, unknown.status_code, empty.status_code] == [422] * 4


def test_unit_line_over_return_409(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session, pull_ctx: dict[str, Any]
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx)
    _settle(db, pull["id"], pull_ctx)
    ids = _line_ids(db, uuid.UUID(pull["id"]))
    r = _return(client, superuser_token_headers, pull["id"], [(ids["UNIT"], 2)])
    assert r.status_code == 409, r.text


# --- Review Focus -----------------------------------------------------------


def test_unit_repulled_elsewhere_not_returnable_on_old_pull(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session, pull_ctx: dict[str, Any]
) -> None:
    a = _create(client, superuser_token_headers, pull_ctx, part_qty=1)
    _settle(db, a["id"], pull_ctx)
    ids_a = _line_ids(db, uuid.UUID(a["id"]))
    assert _return(client, superuser_token_headers, a["id"], [(ids_a["UNIT"], 1)]).status_code == 200
    b = _create(client, superuser_token_headers, pull_ctx, part_qty=1)  # re-pulls the same unit
    assert b["stock_deducted"] is True
    r = client.get(f"{PREFIX}/project-pulls/{a['id']}", headers=superuser_token_headers)
    unit_line = next(ln for ln in r.json()["lines"] if ln["line_kind"] == "UNIT")
    assert unit_line["returnable_qty"] == 0
    r = _return(client, superuser_token_headers, a["id"], [(ids_a["UNIT"], 1)])
    assert r.status_code == 409, r.text
    db.expire_all()
    assert _unit(db, pull_ctx).current_state == UnitState.PROJECT_OUT  # still B's


def test_legacy_short_pull_returnable_is_what_moved(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session, pull_ctx: dict[str, Any]
) -> None:
    pull = _legacy_pull(db, pull_ctx, part_qty=2)
    ids = _line_ids(db, pull.id)
    crud.fulfill_project_pull(
        session=db,
        pull_id=pull.id,
        fulfill_lines=[
            ProjectPullFulfillLine(line_id=uuid.UUID(ids["UNIT"]), fulfilled_qty=1),
            ProjectPullFulfillLine(line_id=uuid.UUID(ids["PART"]), fulfilled_qty=1),
        ],
        actor_user_id=pull_ctx["admin_id"],
    )
    r = client.get(f"{PREFIX}/project-pulls/{pull.id}", headers=superuser_token_headers)
    part_line = next(ln for ln in r.json()["lines"] if ln["line_kind"] == "PART")
    assert r.json()["state"] == "SHORT"
    assert part_line["returnable_qty"] == 1


def test_return_on_cancelled_short_pull(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session, pull_ctx: dict[str, Any]
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx, part_qty=2)
    ids = _line_ids(db, uuid.UUID(pull["id"]))
    crud.fulfill_project_pull(
        session=db,
        pull_id=uuid.UUID(pull["id"]),
        fulfill_lines=[ProjectPullFulfillLine(line_id=uuid.UUID(ids["PART"]), fulfilled_qty=1)],
        actor_user_id=pull_ctx["admin_id"],
    )
    crud.cancel_project_pull(session=db, pull_id=uuid.UUID(pull["id"]), actor_user_id=pull_ctx["admin_id"])
    row = db.get(ProjectPull, uuid.UUID(pull["id"]))
    assert row is not None and row.state == ProjectPullState.CANCELLED
    r = _return(client, superuser_token_headers, pull["id"], [(ids["PART"], 2)])
    assert r.status_code == 200, r.text


def test_return_works_for_deactivated_product(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session, pull_ctx: dict[str, Any]
) -> None:
    pull = _create(client, superuser_token_headers, pull_ctx)
    _settle(db, pull["id"], pull_ctx)
    product = db.get(Product, pull_ctx["part_product_id"])
    assert product is not None
    product.is_active = False
    db.add(product)
    db.commit()
    ids = _line_ids(db, uuid.UUID(pull["id"]))
    r = _return(client, superuser_token_headers, pull["id"], [(ids["PART"], 1)])
    assert r.status_code == 200, r.text
