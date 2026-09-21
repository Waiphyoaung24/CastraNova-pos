# Project Pull Return Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let staff and admin put stock from a project pull back into inventory, and let admin cancel a waiting pull whose stock was already taken.

**Architecture:** A return appends `RETURNED` movements tagged with `project_pull_id` that reverse the pull's own `PROJECT_OUT` movements — units walk `PROJECT_OUT -> IN_STOCK`, parts re-credit the exact batches at the exact cost. No new tables: what is still returnable is read from the ledgers, and idempotency rides on movement keys derived from the request key. Project COGS queries net the returns out in the month they happen.

**Tech Stack:** FastAPI, SQLModel/SQLAlchemy 2.0, PostgreSQL, pytest; React + TanStack Query, shadcn/ui, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-21-pull-return-design.md`

## Global Constraints

- All DB access in `backend/app/crud.py`; routes never call `session.exec`.
- Ledgers are append-only (m021 trigger): never UPDATE/DELETE a movement, cost line — only insert.
- No Alembic migration. `alembic check` must stay clean at head `m039`.
- mypy strict; ruff clean on touched lines (26 pre-existing errors are the baseline).
- Same-key replay by a different user → **409** "Idempotency key was already used by a different user." (`_assert_replay_actor`, crud.py:218).
- Lock order: pull `FOR UPDATE` → units by `Unit.id` → batches by `(received_at, id)`.
- Keep `populate_existing=True` on the batch re-lock (identity-map staleness).
- Frontend: never hand-edit `src/client/`; regenerate with `bun run generate-client`.
- E2E: always `E2E_SKIP_DB_RESET=1` and `VITE_API_URL` set.
- Backend tests truncate the dev DB — after running them, restore with `python -m app.initial_data` and `python -m app.seed_demo` before E2E.
- Commit only the files you touched (the working tree has unrelated CRLF churn): `git add <paths>`, never `git add -A`.
- Branch: `git checkout -b feat/pull-return` from `dev`. PR targets `dev`.

## Review Focus

1. **A unit returned from pull A, then pulled again by pull B.** Pull A must show 0 returnable for it; returning it against A must 409, not walk B's unit back. (Task 3 test `test_unit_repulled_elsewhere_not_returnable_on_old_pull`.)
2. **Double submit / retry with the same key.** Second call returns 200 with the same pull and no extra movement or batch credit. (Task 3 `test_replay_same_key_no_double_credit`.)
3. **Legacy pull fulfilled SHORT at fulfill time** (deducted only what was handed out). Returnable is what actually moved, not the requested qty. (Task 3 `test_legacy_short_pull_returnable_is_what_moved`.)
4. **A SHORT pull that was then cancelled** still holds deducted stock; Return must work on CANCELLED. (Task 3 `test_return_on_cancelled_short_pull`.)
5. **Product deactivated after the pull.** Return must still work (no `_require_active_product` on the return path). (Task 3 `test_return_works_for_deactivated_product`.)

---

## File Structure

| File | Change |
|---|---|
| `backend/app/core/state_machine.py` | add edge `(PROJECT_OUT, RETURNED) -> IN_STOCK`, rewrite comment |
| `backend/app/models.py` | `ProjectPullReturnLine`, `ProjectPullReturnCreate`; `returnable_qty` on `ProjectPullLinePublic`; `event_type` on `ProjectConsumptionRowPublic` |
| `backend/app/crud.py` | generalise `_return_unit_line`/`_return_part_line` movers; `pull_line_returnable`; `_return_pull_lines`; `return_project_pull`; cancel restores stock; PART-dup guard in create; COGS netting at 7 sites + consumed-items list |
| `backend/app/api/routes/project_pulls.py` | `POST /{pull_id}/returns`; `returnable_qty` in `_to_public` |
| `backend/tests/api/routes/test_project_pull_returns.py` | new |
| `backend/tests/api/routes/test_project_pulls.py` | flip `test_cancel_deducted_pending_pull_409`; add dup-PART test |
| `backend/tests/crud/test_pull_return_concurrency.py` | new |
| `backend/tests/api/routes/test_margin_report.py`, `test_project_dashboard.py` | netting tests |
| `frontend/src/lib/pull-return.ts` (+ `.test.ts`) | new — draft logic |
| `frontend/src/components/pos/PullReturnDialog.tsx` | new |
| `frontend/src/components/pos/PullFulfillPanel.tsx`, `PullQueue.tsx`, `routes/_layout/pulls.tsx` | wire Return + Cancel |
| `frontend/src/routes/_layout/project.$projectId.tsx` | show RETURNED rows |
| `frontend/tests/pull-return.spec.ts` | new E2E; flip "no Cancel" assertion in `pulls.spec.ts` |

---

### Task 1: Generalise the sale-return movers (refactor, no behaviour change)

**Files:**
- Modify: `backend/app/crud.py:2825-3008` (`_return_unit_line`, `_return_part_line`)
- Test: existing `backend/tests/api/routes/test_sale_returns.py`, `backend/tests/crud/test_return_concurrency.py`

**Interfaces:**
- Produces:
  - `_reverse_unit_out(*, session: Session, unit: Unit, back_to: uuid.UUID, idempotency_key: uuid.UUID, actor_user_id: uuid.UUID, sale_id: uuid.UUID | None = None, project_pull_id: uuid.UUID | None = None) -> Decimal` — caller holds `unit` FOR UPDATE.
  - `_reverse_part_out(*, session: Session, source: PartMovement, already_returned: int, quantity: int, idempotency_key: uuid.UUID, actor_user_id: uuid.UUID, from_location_id: uuid.UUID, to_location_id: uuid.UUID) -> Decimal` — the RETURNED movement copies `product_id`, `sale_id`, `project_pull_id` from `source`.

- [ ] **Step 1: Baseline — run the sale-return suites green before touching anything**

Run (from `backend/`): `uv run pytest tests/api/routes/test_sale_returns.py tests/crud/test_return_concurrency.py -q`
Expected: all PASS. Record the count.

- [ ] **Step 2: Extract `_reverse_unit_out` from `_return_unit_line`**

Replace the body of `_return_unit_line` from the `try: new_state = assert_unit_transition(...)` down to `return unit.purchase_cost_thb` with the lookup + a call; add the new function above it:

```python
def _reverse_unit_out(
    *,
    session: Session,
    unit: Unit,
    back_to: uuid.UUID,
    idempotency_key: uuid.UUID,
    actor_user_id: uuid.UUID,
    sale_id: uuid.UUID | None = None,
    project_pull_id: uuid.UUID | None = None,
) -> Decimal:
    """Walk a SOLD or PROJECT_OUT unit back to IN_STOCK at ``back_to`` and
    return its cost. The caller holds ``unit`` FOR UPDATE and picks
    ``back_to`` (where the unit stood before it left)."""
    try:
        new_state = assert_unit_transition(unit.current_state, MovementType.RETURNED)
    except IllegalTransition:
        raise HTTPException(
            status_code=409,
            detail=f"Unit cannot be returned from {unit.current_state.value}",
        )
    session.add(
        UnitMovement(
            unit_id=unit.id,
            event_type=MovementType.RETURNED,
            from_location_id=unit.current_location_id,
            to_location_id=back_to,
            sale_id=sale_id,
            project_pull_id=project_pull_id,
            actor_user_id=actor_user_id,
            idempotency_key=idempotency_key,
        )
    )
    unit.current_state = new_state
    unit.current_location_id = back_to
    unit.updated_at = get_datetime_utc()
    session.add(unit)
    return unit.purchase_cost_thb
```

`_return_unit_line` keeps its quantity check, unit lock, and SOLD lookup, then ends with:

```python
    return _reverse_unit_out(
        session=session,
        unit=unit,
        back_to=back_to,
        idempotency_key=uuid.uuid5(ret.idempotency_key, f"unit:{sale_line.id}"),
        actor_user_id=actor_user_id,
        sale_id=sale_line.sale_id,
    )
```

The `IllegalTransition` try/except that used to sit before the SOLD lookup moves into `_reverse_unit_out` — delete it from `_return_unit_line`.

- [ ] **Step 3: Extract `_reverse_part_out` from `_return_part_line`**

Keep in `_return_part_line` only the `assert sale_line.product_id`, the `sold = ...` lookup and its 409. Everything from `consumed = session.exec(...)` to `return restored` moves into:

```python
def _reverse_part_out(
    *,
    session: Session,
    source: PartMovement,
    already_returned: int,
    quantity: int,
    idempotency_key: uuid.UUID,
    actor_user_id: uuid.UUID,
    from_location_id: uuid.UUID,
    to_location_id: uuid.UUID,
) -> Decimal:
    """Roll back ``quantity`` of a consuming movement (SOLD or PROJECT_OUT)
    onto the exact batches it drew, at the exact cost, and return the cost
    restored. <keep the existing docstring paragraph about reverse FIFO>"""
```

Inside it, change `CostLine.part_movement_id == sold.id` → `CostLine.part_movement_id == source.id`, and the movement constructor to:

```python
    movement = PartMovement(
        product_id=source.product_id,
        event_type=MovementType.RETURNED,
        quantity=quantity,
        from_location_id=from_location_id,
        to_location_id=to_location_id,
        sale_id=source.sale_id,
        project_pull_id=source.project_pull_id,
        actor_user_id=actor_user_id,
        idempotency_key=idempotency_key,
    )
```

Everything else (the skip/plan loop, the `populate_existing=True` re-lock with its comment, crediting batches, writing cost lines) moves verbatim. `_return_part_line` ends with:

```python
    return _reverse_part_out(
        session=session,
        source=sold,
        already_returned=already_returned,
        quantity=quantity,
        idempotency_key=uuid.uuid5(ret.idempotency_key, f"part:{sale_line.id}"),
        actor_user_id=actor_user_id,
        from_location_id=from_location_id,
        to_location_id=to_location_id,
    )
```

- [ ] **Step 4: Run the same suites — must be identical**

Run: `uv run pytest tests/api/routes/test_sale_returns.py tests/crud/test_return_concurrency.py -q`
Expected: same count, all PASS. Then `uv run mypy app/crud.py`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/crud.py
git commit -m "refactor(returns): extract unit/part reversal movers from sale returns"
```

---

### Task 2: Returnable qty per pull line + one PART line per product

**Files:**
- Modify: `backend/app/crud.py` (`create_project_pull` ~3530; add `pull_line_returnable` after `pull_stock_deducted` ~3605)
- Modify: `backend/app/models.py:1791` (`ProjectPullLinePublic`)
- Modify: `backend/app/api/routes/project_pulls.py:23-37` (`_to_public`)
- Test: `backend/tests/api/routes/test_project_pulls.py`

**Interfaces:**
- Produces: `pull_line_returnable(*, session: Session, pull_id: uuid.UUID, lines: Sequence[ProjectPullLine]) -> dict[uuid.UUID, int]`; `ProjectPullLinePublic.returnable_qty: int`.

- [ ] **Step 1: Write the failing tests** (append to `test_project_pulls.py`)

```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/api/routes/test_project_pulls.py -k "two_part_lines or returnable" -v`
Expected: dup test FAILS (200), returnable tests FAIL (`KeyError: 'returnable_qty'`).

- [ ] **Step 3: Implement**

In `create_project_pull`, before `pull = ProjectPull(...)`:

```python
    # Movements carry the pull but not the line, so a return nets PART stock
    # per product. Two PART lines for one product would make that ambiguous.
    part_products = [ln.product_id for ln in pull_in.lines if ln.line_kind == SaleLineKind.PART]
    if len(part_products) != len(set(part_products)):
        raise HTTPException(
            status_code=422, detail="One PART line per product; merge the quantities"
        )
```

In `models.py`, add to `ProjectPullLinePublic` after `line_state`:

```python
    # Still out and can come back: PROJECT_OUT minus RETURNED for this line.
    returnable_qty: int = 0
```

In `crud.py` after `pull_stock_deducted`:

```python
def pull_line_returnable(
    *, session: Session, pull_id: uuid.UUID, lines: Sequence[ProjectPullLine]
) -> dict[uuid.UUID, int]:
    """Per line, how much of this pull is still out and can come back:
    PROJECT_OUT minus RETURNED, read from the ledgers (never a flag).

    Movements carry the pull but not the line, so PART lines net per product.
    Create allows one PART line per product; a legacy pull that repeats one
    gets the whole product balance on its first line (by id)."""
    events = (MovementType.PROJECT_OUT, MovementType.RETURNED)

    part_net: dict[uuid.UUID, int] = {}
    for product_id, event, qty in session.exec(
        select(PartMovement.product_id, PartMovement.event_type, func.sum(PartMovement.quantity))
        .where(
            PartMovement.project_pull_id == pull_id,
            col(PartMovement.event_type).in_(events),
        )
        .group_by(col(PartMovement.product_id), col(PartMovement.event_type))
    ).all():
        sign = -1 if event == MovementType.RETURNED else 1
        part_net[product_id] = part_net.get(product_id, 0) + sign * int(qty)

    unit_net: dict[str, int] = {}
    for barcode, event, n in session.exec(
        select(Unit.castranova_barcode, UnitMovement.event_type, func.count())
        .join(Unit, col(UnitMovement.unit_id) == col(Unit.id))
        .where(
            UnitMovement.project_pull_id == pull_id,
            col(UnitMovement.event_type).in_(events),
        )
        .group_by(col(Unit.castranova_barcode), col(UnitMovement.event_type))
    ).all():
        sign = -1 if event == MovementType.RETURNED else 1
        unit_net[barcode] = unit_net.get(barcode, 0) + sign * int(n)

    out: dict[uuid.UUID, int] = {}
    for line in sorted(lines, key=lambda ln: str(ln.id)):
        if line.line_kind == SaleLineKind.UNIT:
            out[line.id] = max(0, unit_net.get(line.unit_serial or "", 0))
        else:
            out[line.id] = max(0, part_net.pop(line.product_id, 0))
    return out
```

In `_to_public` (routes), after `lines = ...`:

```python
    # ponytail: 3 grouped queries per pull on top of the existing per-line
    # product lookups; batch across pulls if the 100-row list gets slow.
    returnable = crud.pull_line_returnable(session=session, pull_id=pull.id, lines=lines)
```

and add `"returnable_qty": returnable[line.id],` to the `update={...}` dict.

- [ ] **Step 4: Run to verify they pass, plus the whole pull suite**

Run: `uv run pytest tests/api/routes/test_project_pulls.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/crud.py backend/app/models.py backend/app/api/routes/project_pulls.py backend/tests/api/routes/test_project_pulls.py
git commit -m "feat(pulls): expose returnable qty per line; one PART line per product"
```

---

### Task 3: Return items from a pull (crud + route + state edge)

**Files:**
- Modify: `backend/app/core/state_machine.py:16-25`
- Modify: `backend/app/models.py` (after `ProjectPullFulfill` ~1789)
- Modify: `backend/app/crud.py` (after `fulfill_project_pull`)
- Modify: `backend/app/api/routes/project_pulls.py` (new route after fulfill)
- Test: create `backend/tests/api/routes/test_project_pull_returns.py`

**Interfaces:**
- Consumes: `_reverse_unit_out`, `_reverse_part_out` (Task 1); `pull_line_returnable` (Task 2).
- Produces:
  - `ProjectPullReturnLine(line_id: uuid.UUID, quantity: int)`, `ProjectPullReturnCreate(idempotency_key: uuid.UUID, lines: list[ProjectPullReturnLine])`
  - `_return_pull_lines(*, session: Session, pull: ProjectPull, lines: Sequence[ProjectPullLine], qty_by_line: dict[uuid.UUID, int], key: uuid.UUID, actor_user_id: uuid.UUID) -> None` (no commit)
  - `return_project_pull(*, session: Session, pull_id: uuid.UUID, payload: ProjectPullReturnCreate, actor_user_id: uuid.UUID) -> ProjectPull`
  - `POST /api/v1/project-pulls/{pull_id}/returns` → `ProjectPullPublic`; SDK method `ProjectPullsService.returnProjectPull({ pullId, requestBody })`.

- [ ] **Step 1: Write the failing tests** — new file `test_project_pull_returns.py`

```python
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


def test_unit_return_on_unfulfilled_unit_line_409(
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/api/routes/test_project_pull_returns.py -q`
Expected: FAIL — 404/405 on the unknown route.

- [ ] **Step 3: State machine edge**

In `state_machine.py`, replace the comment + sale edge with:

```python
    # Returns (m035 sale, 2026-09-21 project pull): the only edges back out of
    # a terminal-looking state. Nothing else may resurrect a unit — never add
    # a RETURNED edge from ADJUSTED_OUT or MAINTENANCE_OUT.
    (UnitState.SOLD, MovementType.RETURNED): UnitState.IN_STOCK,
    (UnitState.PROJECT_OUT, MovementType.RETURNED): UnitState.IN_STOCK,
```

- [ ] **Step 4: Models** (after `ProjectPullFulfill`)

```python
class ProjectPullReturnLine(SQLModel):
    line_id: uuid.UUID
    quantity: int = Field(gt=0, le=1_000_000)


class ProjectPullReturnCreate(SQLModel):
    # Movement keys are uuid5(idempotency_key, "<kind>:<line_id>"), so a
    # replay finds its own movements — no header row needed.
    idempotency_key: uuid.UUID
    lines: list[ProjectPullReturnLine] = Field(min_length=1, max_length=200)
```

Import both in `crud.py` and the routes file.

- [ ] **Step 5: crud** (after `fulfill_project_pull`)

```python
def _return_pull_lines(
    *,
    session: Session,
    pull: ProjectPull,
    lines: Sequence[ProjectPullLine],
    qty_by_line: dict[uuid.UUID, int],
    key: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> None:
    """Put pulled stock back by appending RETURNED movements that reverse this
    pull's own PROJECT_OUT ones: units walk back to where they left from,
    parts re-credit the exact batches, newest first. The caller holds the pull
    FOR UPDATE (the serialization point) and commits."""
    returnable = pull_line_returnable(session=session, pull_id=pull.id, lines=lines)
    for line_id, qty in qty_by_line.items():
        if qty > returnable[line_id]:
            raise HTTPException(
                status_code=409,
                detail=f"Over-return: {returnable[line_id]} returnable, requested {qty}",
            )
    ygn = session.exec(select(Location).where(Location.code == "YGN_WH")).first()
    customer_loc = session.exec(
        select(Location).where(Location.code == "CUSTOMER")
    ).first()
    if not ygn or not customer_loc:
        raise HTTPException(status_code=500, detail="Locations not seeded")

    by_id = {ln.id: ln for ln in lines}
    wanted = [by_id[lid] for lid, qty in qty_by_line.items() if qty > 0]

    # All units in one id-ordered lock, same order as _move_pull_stock.
    unit_lines = [ln for ln in wanted if ln.line_kind == SaleLineKind.UNIT]
    serials = [ln.unit_serial for ln in unit_lines if ln.unit_serial]
    units = {
        u.castranova_barcode: u
        for u in session.exec(
            select(Unit)
            .where(col(Unit.castranova_barcode).in_(serials))
            .order_by(col(Unit.id))
            .with_for_update()
        ).all()
    } if serials else {}
    for line in unit_lines:
        unit = units[line.unit_serial or ""]
        # The PROJECT_OUT movement's key is deterministic (see _move_pull_stock).
        out = session.exec(
            select(UnitMovement).where(
                UnitMovement.idempotency_key == uuid.uuid5(pull.id, f"unit:{line.id}")
            )
        ).first()
        _reverse_unit_out(
            session=session,
            unit=unit,
            back_to=(out.from_location_id if out and out.from_location_id else ygn.id),
            idempotency_key=uuid.uuid5(key, f"unit:{line.id}"),
            actor_user_id=actor_user_id,
            project_pull_id=pull.id,
        )

    # PART lines in product order, same as _move_pull_stock, so batch locks
    # are taken in one global order.
    part_lines = sorted(
        (ln for ln in wanted if ln.line_kind == SaleLineKind.PART),
        key=lambda ln: str(ln.product_id),
    )
    for line in part_lines:
        out_part = session.exec(
            select(PartMovement).where(
                PartMovement.idempotency_key == uuid.uuid5(pull.id, f"part:{line.id}")
            )
        ).first()
        if out_part is None:
            raise HTTPException(
                status_code=409, detail="Original consumption movement not found"
            )
        _reverse_part_out(
            session=session,
            source=out_part,
            already_returned=max(0, out_part.quantity - returnable[line.id]),
            quantity=qty_by_line[line.id],
            idempotency_key=uuid.uuid5(key, f"part:{line.id}"),
            actor_user_id=actor_user_id,
            from_location_id=customer_loc.id,
            to_location_id=ygn.id,
        )


def _pull_return_replay(
    *, session: Session, keys: list[uuid.UUID]
) -> UnitMovement | PartMovement | None:
    unit_hit = session.exec(
        select(UnitMovement).where(col(UnitMovement.idempotency_key).in_(keys))
    ).first()
    if unit_hit is not None:
        return unit_hit
    return session.exec(
        select(PartMovement).where(col(PartMovement.idempotency_key).in_(keys))
    ).first()


def _replayed_pull(
    *, hit: UnitMovement | PartMovement, pull: ProjectPull, actor_user_id: uuid.UUID
) -> ProjectPull:
    _assert_replay_actor(stored_user_id=hit.actor_user_id, caller_user_id=actor_user_id)
    if hit.project_pull_id != pull.id:
        raise HTTPException(
            status_code=409,
            detail="Idempotency key already used for a different request",
        )
    return pull


def return_project_pull(
    *,
    session: Session,
    pull_id: uuid.UUID,
    payload: ProjectPullReturnCreate,
    actor_user_id: uuid.UUID,
) -> ProjectPull:
    """Staff or admin puts items from a pull back into stock (design
    2026-09-21). FULFILLED / SHORT / CANCELLED pulls only — a waiting pull is
    undone with cancel. The pull's state and hand-out record are unchanged;
    only stock and Project COGS move. Idempotent on idempotency_key."""
    pull = session.exec(
        select(ProjectPull).where(ProjectPull.id == pull_id).with_for_update()
    ).first()
    if not pull:
        raise HTTPException(status_code=404, detail="Project pull not found")

    # Checked AFTER the pull lock: a concurrent same-key request on this pull
    # has committed by now, so its movements are visible here.
    keys = [
        uuid.uuid5(payload.idempotency_key, f"{kind}:{ln.line_id}")
        for ln in payload.lines
        for kind in ("unit", "part")
    ]
    hit = _pull_return_replay(session=session, keys=keys)
    if hit is not None:
        return _replayed_pull(hit=hit, pull=pull, actor_user_id=actor_user_id)

    if pull.state == ProjectPullState.PENDING:
        raise HTTPException(
            status_code=409,
            detail="This request is still waiting — use Cancel to put its stock back",
        )

    lines = session.exec(
        select(ProjectPullLine)
        .where(ProjectPullLine.project_pull_id == pull.id)
        .order_by(col(ProjectPullLine.id))
    ).all()
    payload_ids = [ln.line_id for ln in payload.lines]
    if len(payload_ids) != len(set(payload_ids)):
        raise HTTPException(status_code=422, detail="Duplicate line_id in payload")
    if set(payload_ids) - {ln.id for ln in lines}:
        raise HTTPException(status_code=422, detail="Unknown line_id for this pull")

    try:
        _return_pull_lines(
            session=session,
            pull=pull,
            lines=lines,
            qty_by_line={ln.line_id: ln.quantity for ln in payload.lines},
            key=payload.idempotency_key,
            actor_user_id=actor_user_id,
        )
        session.commit()
    except IntegrityError:
        # A same-key request on ANOTHER pull won the race (different lock).
        session.rollback()
        winner = _pull_return_replay(session=session, keys=keys)
        if winner is None:
            raise
        return _replayed_pull(hit=winner, pull=pull, actor_user_id=actor_user_id)
    session.refresh(pull)
    return pull
```

Note `test_key_reused_on_other_pull_409` hits the pre-check path: the derived key exists and its `project_pull_id` is pull A.

- [ ] **Step 6: Route** (after `fulfill_project_pull` in `project_pulls.py`)

```python
# Open to staff + admin like fulfill (shared-team access, decision D3). No
# cost fields on this surface, so no staff redaction variant.
@router.post(
    "/{pull_id}/returns",
    response_model=ProjectPullPublic,
    dependencies=[Depends(get_current_user)],
)
def return_project_pull(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    pull_id: uuid.UUID,
    payload: ProjectPullReturnCreate,
) -> ProjectPullPublic:
    pull = crud.return_project_pull(
        session=session, pull_id=pull_id, payload=payload, actor_user_id=current_user.id
    )
    return _to_public(session=session, pull=pull)
```

- [ ] **Step 7: Run to verify they pass**

Run: `uv run pytest tests/api/routes/test_project_pull_returns.py tests/api/routes/test_project_pulls.py tests/api/routes/test_sale_returns.py -q`
Expected: all PASS. Then `uv run mypy app`.

- [ ] **Step 8: Commit**

```bash
git add backend/app/core/state_machine.py backend/app/models.py backend/app/crud.py backend/app/api/routes/project_pulls.py backend/tests/api/routes/test_project_pull_returns.py
git commit -m "feat(pulls): return items from a pull back to stock"
```

---

### Task 4: Cancel a waiting pull puts its stock back

**Files:**
- Modify: `backend/app/crud.py` `cancel_project_pull` (~3828-3876)
- Modify: `backend/tests/api/routes/test_project_pulls.py:737-756`

**Interfaces:**
- Consumes: `_return_pull_lines`, `pull_line_returnable` (Tasks 2-3).

- [ ] **Step 1: Replace `test_cancel_deducted_pending_pull_409` with the failing test**

```python
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
```

Add `PartBatch` to the file's `app.models` import.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/api/routes/test_project_pulls.py -k cancel -v`
Expected: the new test FAILS with 409.

- [ ] **Step 3: Implement** — in `cancel_project_pull`, replace the whole `if pull.state == ProjectPullState.PENDING and pull_stock_deducted(...)` 409 block with:

```python
    # Stock left at create: put every line's balance back before the flip,
    # in this same transaction. Deterministic key — a cancel happens once
    # (the CANCELLED early-return above makes a repeat a no-op).
    if pull.state == ProjectPullState.PENDING and pull_stock_deducted(
        session=session, pull_id=pull.id
    ):
        pull_lines = session.exec(
            select(ProjectPullLine)
            .where(ProjectPullLine.project_pull_id == pull.id)
            .order_by(col(ProjectPullLine.id))
        ).all()
        _return_pull_lines(
            session=session,
            pull=pull,
            lines=pull_lines,
            qty_by_line=pull_line_returnable(
                session=session, pull_id=pull.id, lines=pull_lines
            ),
            key=uuid.uuid5(pull.id, "cancel"),
            actor_user_id=actor_user_id,
        )
```

Update the docstring: "Admin cancels a PENDING or SHORT pull (Flow D.3). A PENDING pull whose stock already left gets it back via RETURNED movements; a SHORT pull's given-out stock stays out (return it explicitly)."

- [ ] **Step 4: Run to verify**

Run: `uv run pytest tests/api/routes/test_project_pulls.py tests/api/routes/test_project_pull_returns.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/crud.py backend/tests/api/routes/test_project_pulls.py
git commit -m "feat(pulls): cancelling a waiting pull puts its stock back"
```

---

### Task 5: Concurrency — pull returns racing sales (mandatory, FIFO)

**Files:**
- Create: `backend/tests/crud/test_pull_return_concurrency.py`

**Interfaces:**
- Consumes: `crud.return_project_pull`, `ProjectPullReturnCreate` (Task 3).

- [ ] **Step 1: Write the test**

```python
"""Pull returns racing sales on the same product (design 2026-09-21).

A pull return re-credits batches via _reverse_part_out, which re-locks in
(received_at, id) order — the same order consume_quantity_fifo takes. Any
divergence shows up here as an "error:" result (DeadlockDetected), never a
silent pass. Mirrors test_return_concurrency.py.
"""

import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.core.db import engine
from app.models import (
    CustomerCreate,
    Location,
    MovementType,
    PartBatch,
    PartMovement,
    ProductCreate,
    ProjectCreate,
    ProjectPullCreate,
    ProjectPullLineCreate,
    ProjectPullReturnCreate,
    ProjectPullReturnLine,
    SaleLineInput,
    SaleLineKind,
    SupplierCreate,
    TrackingMode,
)

PULLS = 4
PULL_QTY = 3
RECEIVED = 20  # 8@10 + 12@12; 4 pulls of 3 cross the batch boundary


@pytest.fixture
def pulled(db: Session) -> Iterator[tuple[str, uuid.UUID, uuid.UUID, list[tuple[uuid.UUID, uuid.UUID]]]]:
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert user is not None
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"PRET-{uuid.uuid4().hex[:8]}",
            model_name="Bearing",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="50.00",
            repair_price_thb="10.00",
        ),
    )
    supplier = crud.create_supplier(session=db, supplier_in=SupplierCreate(name="Acme"))
    for qty, cost in ((8, "10.00"), (12, "12.00")):
        crud.receive_quantity(
            session=db,
            product_id=product.id,
            supplier_id=supplier.id,
            received_qty=qty,
            purchase_cost_thb=Decimal(cost),
            idempotency_key=uuid.uuid4(),
            received_by_user_id=user.id,
        )
    customer = crud.create_customer(session=db, customer_in=CustomerCreate(name="Conc Pull"))
    project = crud.create_project(
        session=db,
        project_in=ProjectCreate(code=f"PRJ-{uuid.uuid4().hex[:8]}", name="Site", customer_id=customer.id),
    )
    pulls: list[tuple[uuid.UUID, uuid.UUID]] = []
    for _ in range(PULLS):
        pull = crud.create_project_pull(
            session=db,
            pull_in=ProjectPullCreate(
                project_id=project.id,
                lines=[
                    ProjectPullLineCreate(
                        line_kind=SaleLineKind.PART, product_id=product.id, requested_qty=PULL_QTY
                    )
                ],
            ),
            created_by_user_id=user.id,
        )
        crud.fulfill_project_pull(session=db, pull_id=pull.id, fulfill_lines=[], actor_user_id=user.id)
        line = crud.list_project_pull_lines(session=db, pull_id=pull.id)[0]
        pulls.append((pull.id, line.id))
    db.commit()
    yield product.sku, customer.id, user.id, pulls


def _return_once(pull_id: uuid.UUID, line_id: uuid.UUID, actor: uuid.UUID) -> str:
    with Session(engine) as session:
        try:
            crud.return_project_pull(
                session=session,
                pull_id=pull_id,
                payload=ProjectPullReturnCreate(
                    idempotency_key=uuid.uuid4(),
                    lines=[ProjectPullReturnLine(line_id=line_id, quantity=PULL_QTY)],
                ),
                actor_user_id=actor,
            )
            return "ok"
        except HTTPException as exc:
            session.rollback()
            return "conflict" if exc.status_code == 409 else f"error:{exc.detail}"
        except Exception as exc:  # deadlock / 500 / anything unexpected
            session.rollback()
            return f"error:{exc!r}"


def _sell_once(customer_id: uuid.UUID, sku: str, actor: uuid.UUID) -> str:
    with Session(engine) as session:
        try:
            crud.create_sale(
                session=session,
                customer_id=customer_id,
                created_by_user_id=actor,
                idempotency_key=uuid.uuid4(),
                lines=[SaleLineInput(line_kind=SaleLineKind.PART, sku=sku, quantity=PULL_QTY)],
            )
            return "ok"
        except HTTPException as exc:
            session.rollback()
            return "conflict" if exc.status_code == 409 else f"error:{exc.detail}"
        except Exception as exc:
            session.rollback()
            return f"error:{exc!r}"


def test_concurrent_pull_returns_and_sales_neither_deadlock_nor_corrupt_stock(
    db: Session,
    pulled: tuple[str, uuid.UUID, uuid.UUID, list[tuple[uuid.UUID, uuid.UUID]]],
) -> None:
    sku, customer_id, actor, pulls = pulled
    jobs = [
        (lambda p=p, ln=ln: _return_once(p, ln, actor)) for p, ln in pulls
    ] + [(lambda: _sell_once(customer_id, sku, actor)) for _ in range(PULLS)]
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        results = list(pool.map(lambda job: job(), jobs))

    errors = [r for r in results if r.startswith("error:")]
    assert not errors, errors
    assert results[:PULLS] == ["ok"] * PULLS  # distinct pulls, all win
    assert all(r in ("ok", "conflict") for r in results[PULLS:])

    db.expire_all()
    product_id = db.exec(select(PartMovement.product_id).where(PartMovement.project_pull_id == pulls[0][0])).first()
    batches = db.exec(select(PartBatch).where(PartBatch.product_id == product_id)).all()
    assert all(0 <= b.remaining_qty <= b.received_qty for b in batches)

    def _moved(event: MovementType) -> int:
        return sum(
            m.quantity
            for m in db.exec(
                select(PartMovement).where(
                    PartMovement.product_id == product_id, PartMovement.event_type == event
                )
            ).all()
        )

    on_hand = sum(b.remaining_qty for b in batches)
    assert on_hand == RECEIVED - _moved(MovementType.PROJECT_OUT) - _moved(MovementType.SOLD) + _moved(MovementType.RETURNED)
```

- [ ] **Step 2: Run it 3 times** (Windows clock ties can reorder; a real deadlock fails every time)

Run: `for i in 1 2 3; do uv run pytest tests/crud/test_pull_return_concurrency.py -q; done`
Expected: PASS ×3. If it fails with `DeadlockDetected`, stop and use superpowers:systematic-debugging — check both lock orders; do not loosen the test.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/crud/test_pull_return_concurrency.py
git commit -m "test(pulls): pull returns racing sales keep FIFO stock consistent"
```

---

### Task 6: Project COGS nets returns (7 sums + consumed-items list)

**Files:**
- Modify: `backend/app/crud.py` — `_channel_rows` (~4367-4386), `_product_rows` (~4560-4592), `_customer_rows` (~4685-4715), `_project_rows` (~4750-4782), `get_customer_dashboard` (~4912-4930), `_project_consumed_costs` (~4978-5010), `_project_consumed_cost` (~5016-5035), `_project_consumed_items` (~5040-5130)
- Modify: `backend/app/models.py:2182` (`ProjectConsumptionRowPublic`)
- Test: `backend/tests/api/routes/test_margin_report.py`, `backend/tests/api/routes/test_project_dashboard.py`

**Interfaces:**
- Produces: `ProjectConsumptionRowPublic.event_type: MovementType` (`PROJECT_OUT` | `RETURNED`).

- [ ] **Step 1: Write the failing tests**

Append to `test_margin_report.py` (it already imports `_clock_at`, `seed`):

```python
_PULL_OUT = datetime(2027, 8, 10, 12, 0, tzinfo=timezone.utc)
_PULL_BACK = datetime(2027, 9, 10, 12, 0, tzinfo=timezone.utc)


def test_pull_return_nets_project_cogs_in_the_return_month(
    db: Session, seed: dict[str, Any]  # noqa: F811
) -> None:
    from app.models import (
        ProjectCreate,
        ProjectPullCreate,
        ProjectPullLineCreate,
        ProjectPullReturnCreate,
        ProjectPullReturnLine,
    )

    admin = seed["admin"]
    part = seed["make_part"]("100.00", "20.00", [(3, "10.00"), (4, "12.00")])
    project = crud.create_project(
        session=db,
        project_in=ProjectCreate(
            code=f"PRJ-{uuid.uuid4().hex[:8]}", name="Site", customer_id=seed["customer"].id
        ),
    )
    with _clock_at(_PULL_OUT):
        pull = crud.create_project_pull(
            session=db,
            pull_in=ProjectPullCreate(
                project_id=project.id,
                lines=[ProjectPullLineCreate(line_kind=SaleLineKind.PART, product_id=part.id, requested_qty=5)],
            ),
            created_by_user_id=admin.id,
        )
        crud.fulfill_project_pull(session=db, pull_id=pull.id, fulfill_lines=[], actor_user_id=admin.id)
    line = crud.list_project_pull_lines(session=db, pull_id=pull.id)[0]
    with _clock_at(_PULL_BACK):
        crud.return_project_pull(
            session=db,
            pull_id=pull.id,
            payload=ProjectPullReturnCreate(
                idempotency_key=uuid.uuid4(),
                lines=[ProjectPullReturnLine(line_id=line.id, quantity=3)],
            ),
            actor_user_id=admin.id,
        )

    def _project_cogs(year: int, month: int) -> Decimal:
        report = crud.margin_report(session=db, year=year, month=month, channel=Channel.PROJECT)
        return report.total_cogs_thb

    # Out in August: 3@10 + 2@12 = 54. Back in September: 2@12 + 1@10 = 34.
    assert _project_cogs(2027, 8) == Decimal("54.00")  # August never changes
    assert _project_cogs(2027, 9) == Decimal("-34.00")

    by_project = crud.margin_report(
        session=db, year=2027, month=9, group_by=MarginDimension.PROJECT, channel=Channel.PROJECT
    )
    assert {r.key: r.cogs_thb for r in by_project.rows}[str(project.id)] == Decimal("-34.00")
```

Append to `test_project_dashboard.py` (reuses its `_seed_project_with_unit_and_multibatch_part`: unit 100.00 + 5 parts drawn 3@10 + 2@12, consumed 154.00):

```python
def test_pull_return_nets_consumed_cost_and_lists_returned_row(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
    db: Session,
) -> None:
    ctx = _seed_project_with_unit_and_multibatch_part(
        client, superuser_token_headers, staff_token_headers, db
    )
    url = f"{PREFIX}/projects/{ctx['project_id']}/dashboard"
    pull = client.get(
        f"{PREFIX}/project-pulls/{ctx['pull_id']}", headers=superuser_token_headers
    ).json()
    part_line = next(ln for ln in pull["lines"] if ln["line_kind"] == "PART")
    unit_line = next(ln for ln in pull["lines"] if ln["line_kind"] == "UNIT")

    # Return 2 parts (newest batch first: 2@12 = 24.00) and the unit (100.00).
    r = client.post(
        f"{PREFIX}/project-pulls/{ctx['pull_id']}/returns",
        headers=staff_token_headers,
        json={
            "idempotency_key": str(uuid.uuid4()),
            "lines": [
                {"line_id": part_line["id"], "quantity": 2},
                {"line_id": unit_line["id"], "quantity": 1},
            ],
        },
    )
    assert r.status_code == 200, r.text
    body = client.get(url, headers=superuser_token_headers).json()

    assert body["consumed_cost_thb"] == "30.00"  # 154 - 24 - 100
    returned = [row for row in body["consumed_items"] if row["event_type"] == "RETURNED"]
    assert sorted(Decimal(row["total_cost_thb"]) for row in returned) == [
        Decimal("24.00"),
        Decimal("100.00"),
    ]
    # The list still reconciles with the aggregate, signed.
    signed = sum(
        (-1 if row["event_type"] == "RETURNED" else 1) * Decimal(row["total_cost_thb"])
        for row in body["consumed_items"]
    )
    assert signed == Decimal(body["consumed_cost_thb"])
```

The existing `test_consumed_items_reconcile_with_consumed_cost` has no returns and must stay green unchanged.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/api/routes/test_margin_report.py -k pull_return tests/api/routes/test_project_dashboard.py -k pull_return -v`
Expected: FAIL — September COGS is `0.00`; `event_type` KeyError.

- [ ] **Step 3: Add the shared sign helper** (just above `_channel_rows`)

```python
# Project COGS nets pull returns (design 2026-09-21): a RETURNED movement with
# a project_pull_id gives its cost back, in the month it came back. Every
# project query inner-joins ProjectPull, which already drops sale returns
# (their project_pull_id is NULL).
_PROJECT_COST_EVENTS = (MovementType.PROJECT_OUT, MovementType.RETURNED)


def _project_cost(amount: Any, event_type: Any) -> Any:
    return case((event_type == MovementType.RETURNED, -amount), else_=amount)
```

- [ ] **Step 4: Edit the 14 project COGS queries** — in each of the 7 functions, **only inside the PROJECT block** (the queries that `join(ProjectPull, ...)`), make exactly these two substitutions:

Part leg:
```python
# before
func.coalesce(func.sum(CostLine.total_cost_thb), Decimal("0"))
PartMovement.event_type == MovementType.PROJECT_OUT,
# after
func.coalesce(
    func.sum(_project_cost(col(CostLine.total_cost_thb), col(PartMovement.event_type))),
    Decimal("0"),
)
col(PartMovement.event_type).in_(_PROJECT_COST_EVENTS),
```

Unit leg:
```python
# before
func.coalesce(func.sum(Unit.purchase_cost_thb), Decimal("0"))
UnitMovement.event_type == MovementType.PROJECT_OUT,
# after
func.coalesce(
    func.sum(_project_cost(col(Unit.purchase_cost_thb), col(UnitMovement.event_type))),
    Decimal("0"),
)
col(UnitMovement.event_type).in_(_PROJECT_COST_EVENTS),
```

Sites (function → part-leg line, unit-leg line, as of `dev` @ d541696): `_channel_rows` 4372/4383 · `_product_rows` 4570/4587 · `_customer_rows` 4694/4710 · `_project_rows` 4761/4777 · `get_customer_dashboard` 4917/4927 · `_project_consumed_costs` 4988/5005 · `_project_consumed_cost` 5022/5032. The windowed four keep their `occurred_at` window (so a return lands in its own month); the lifetime three have none — leave it that way. Do **not** touch SALE/MAINTENANCE blocks or `_CONSUMING_EVENTS`.

Verify: `grep -n "MovementType.PROJECT_OUT" backend/app/crud.py` now lists only `_CONSUMING_EVENTS`, `_move_pull_stock`, `pull_line_returnable`, and `_project_consumed_items` (next step).

- [ ] **Step 5: Consumed-items list**

`models.py` `ProjectConsumptionRowPublic`, after `line_kind`:

```python
    # PROJECT_OUT (stock went to the project) or RETURNED (it came back —
    # quantity and cost are the amounts given back, both positive).
    event_type: MovementType
```

In `_project_consumed_items`, in both legs change `... .event_type == MovementType.PROJECT_OUT,` → `col(PartMovement.event_type).in_(_PROJECT_COST_EVENTS),` / `col(UnitMovement.event_type).in_(_PROJECT_COST_EVENTS),`, and pass `event_type=movement.event_type,` (PART) and `event_type=unit_movement.event_type,` (UNIT) to `ProjectConsumptionRowPublic(...)`. Update its docstring's first line to "Every PROJECT_OUT and pull RETURNED movement against this project, newest first".

- [ ] **Step 6: Run the report + dashboard suites**

Run: `uv run pytest tests/api/routes/test_margin_report.py tests/api/routes/test_reports.py tests/api/routes/test_project_dashboard.py tests/api/routes/test_customer_dashboard.py tests/api/routes/test_dashboards.py -q`
Expected: all PASS except the known July-2026 date-dependent failure listed in memory (`dev-known-failing-backend-tests`) — compare failure **names**, not counts.

- [ ] **Step 7: Commit**

```bash
git add backend/app/crud.py backend/app/models.py backend/tests/api/routes/test_margin_report.py backend/tests/api/routes/test_project_dashboard.py
git commit -m "feat(reports): project COGS nets pull returns in the month they come back"
```

---

### Task 7: Frontend — Return dialog, Cancel, returned rows

**Files:**
- Regenerate: `frontend/src/client/*`
- Create: `frontend/src/lib/pull-return.ts`, `frontend/src/lib/pull-return.test.ts`
- Create: `frontend/src/components/pos/PullReturnDialog.tsx`
- Modify: `frontend/src/components/pos/PullFulfillPanel.tsx`, `frontend/src/components/pos/PullQueue.tsx:66-70`, `frontend/src/routes/_layout/pulls.tsx`, `frontend/src/routes/_layout/project.$projectId.tsx:155-235`

**Interfaces:**
- Consumes: `ProjectPullsService.returnProjectPull({ pullId, requestBody })`, `ProjectPullLinePublic.returnable_qty`, `ProjectConsumptionRowPublic.event_type`.
- Produces: `ReturnDraft`, `setReturnQty`, `buildPullReturnPayload`, `canReturnPull`, `returnDraftTotal`.

- [ ] **Step 1: Regenerate the SDK** (backend running with Tasks 2-6)

Run (from `frontend/`): `bun run generate-client`
Expected: `types.gen.ts` gains `ProjectPullReturnCreate`, `returnable_qty`, `event_type`; `sdk.gen.ts` gains `returnProjectPull`. `git diff --stat src/client` shows only those three files.

- [ ] **Step 2: Write the failing unit test** `src/lib/pull-return.test.ts`

```ts
import { describe, expect, it } from "vitest"

import type { ProjectPullLinePublic, ProjectPullPublic } from "@/client/types.gen"
import {
  buildPullReturnPayload,
  canReturnPull,
  returnDraftTotal,
  setReturnQty,
} from "./pull-return"

const KEY = "11111111-1111-1111-1111-111111111111"

function line(over: Partial<ProjectPullLinePublic>): ProjectPullLinePublic {
  return {
    id: "l1",
    line_kind: "PART",
    product_id: "p1",
    product_sku: "SKU",
    model_name: "Bolt",
    unit_serial: null,
    requested_qty: 5,
    fulfilled_qty: 5,
    line_state: "FULFILLED",
    returnable_qty: 3,
    ...over,
  }
}

describe("pull return draft", () => {
  it("clamps to [0, returnable] and floors", () => {
    const l = line({})
    expect(setReturnQty({}, l, 9)).toEqual({ l1: 3 })
    expect(setReturnQty({}, l, -1)).toEqual({ l1: 0 })
    expect(setReturnQty({}, l, 2.7)).toEqual({ l1: 2 })
    expect(setReturnQty({}, l, Number.NaN)).toEqual({ l1: 0 })
  })

  it("sends only lines with something to return", () => {
    expect(buildPullReturnPayload({ l1: 2, l2: 0 }, KEY)).toEqual({
      idempotency_key: KEY,
      lines: [{ line_id: "l1", quantity: 2 }],
    })
    expect(returnDraftTotal({ l1: 2, l2: 0, l3: 1 })).toBe(3)
  })

  it("offers Return only on a settled pull with stock still out", () => {
    const pull = (state: ProjectPullPublic["state"], qty: number) =>
      ({ state, lines: [line({ returnable_qty: qty })] }) as ProjectPullPublic
    expect(canReturnPull(pull("FULFILLED", 1))).toBe(true)
    expect(canReturnPull(pull("CANCELLED", 1))).toBe(true)
    expect(canReturnPull(pull("PENDING", 1))).toBe(false) // use Cancel
    expect(canReturnPull(pull("SHORT", 0))).toBe(false)
  })
})
```

Run: `bun run test:unit -- src/lib/pull-return.test.ts` → FAIL (module not found).

- [ ] **Step 3: Implement `src/lib/pull-return.ts`**

```ts
import type {
  ProjectPullLinePublic,
  ProjectPullPublic,
  ProjectPullReturnCreate,
} from "@/client/types.gen"

// line_id -> qty to put back into stock. The server re-checks every cap under
// a lock; clamping here only keeps the steppers honest. No cost in here.
export type ReturnDraft = Record<string, number>

/** A waiting pull is undone with Cancel; a settled one returns what's still out. */
export function canReturnPull(pull: ProjectPullPublic): boolean {
  return pull.state !== "PENDING" && pull.lines.some((l) => l.returnable_qty > 0)
}

/** Set a line's return qty, clamped to [0, returnable_qty], floored. */
export function setReturnQty(
  draft: ReturnDraft,
  line: ProjectPullLinePublic,
  qty: number,
): ReturnDraft {
  const clamped = Math.max(
    0,
    Math.min(line.returnable_qty, Math.floor(Number.isFinite(qty) ? qty : 0)),
  )
  return { ...draft, [line.id]: clamped }
}

export function returnDraftTotal(draft: ReturnDraft): number {
  return Object.values(draft).reduce((sum, q) => sum + q, 0)
}

/** Zero lines are dropped — the API rejects quantity 0. */
export function buildPullReturnPayload(
  draft: ReturnDraft,
  idempotencyKey: string,
): ProjectPullReturnCreate {
  return {
    idempotency_key: idempotencyKey,
    lines: Object.entries(draft)
      .filter(([, quantity]) => quantity > 0)
      .map(([line_id, quantity]) => ({ line_id, quantity })),
  }
}
```

Run: `bun run test:unit -- src/lib/pull-return.test.ts` → PASS.

- [ ] **Step 4: `PullReturnDialog.tsx`**

```tsx
import { Minus, Plus } from "lucide-react"
import { useEffect, useState } from "react"

import type { ProjectPullLinePublic, ProjectPullPublic } from "@/client/types.gen"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { type ReturnDraft, returnDraftTotal, setReturnQty } from "@/lib/pull-return"

interface PullReturnDialogProps {
  pull: ProjectPullPublic
  open: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (draft: ReturnDraft) => void
  isPending: boolean
}

function lineLabel(line: ProjectPullLinePublic): string {
  if (line.line_kind === "UNIT") return line.unit_serial ?? "(no serial)"
  return `${line.model_name} (${line.product_sku})`
}

export function PullReturnDialog({ pull, open, onOpenChange, onSubmit, isPending }: PullReturnDialogProps) {
  const [draft, setDraft] = useState<ReturnDraft>({})
  // Fresh draft each time the dialog opens.
  useEffect(() => {
    if (open) setDraft({})
  }, [open])
  const lines = pull.lines.filter((l) => l.returnable_qty > 0)
  const total = returnDraftTotal(draft)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Return items to stock</DialogTitle>
          <DialogDescription>
            Items that came back from the project go back on the shelf at
            their original cost.
          </DialogDescription>
        </DialogHeader>
        <ul className="space-y-2">
          {lines.map((line) => {
            const qty = draft[line.id] ?? 0
            return (
              <li key={line.id} className="flex items-center justify-between gap-2">
                <span className="num text-sm font-medium">{lineLabel(line)}</span>
                <div className="flex items-center gap-1">
                  <Button
                    type="button" variant="outline" size="icon" className="size-11"
                    disabled={isPending || qty <= 0}
                    aria-label={`Return fewer ${lineLabel(line)}`}
                    onClick={() => setDraft((d) => setReturnQty(d, line, qty - 1))}
                  >
                    <Minus />
                  </Button>
                  <span className="num w-16 text-center" aria-live="polite">
                    {qty} / {line.returnable_qty}
                  </span>
                  <Button
                    type="button" variant="outline" size="icon" className="size-11"
                    disabled={isPending || qty >= line.returnable_qty}
                    aria-label={`Return more ${lineLabel(line)}`}
                    onClick={() => setDraft((d) => setReturnQty(d, line, qty + 1))}
                  >
                    <Plus />
                  </Button>
                </div>
              </li>
            )
          })}
        </ul>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
            Close
          </Button>
          <Button type="button" disabled={isPending || total === 0} onClick={() => onSubmit(draft)}>
            {isPending ? "Saving…" : `Return ${total} ${total === 1 ? "item" : "items"}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
```

- [ ] **Step 5: Wire into `PullFulfillPanel.tsx`**

Add props `onReturn: () => void` and `canReturn: boolean`. Directly under the `<Badge variant="outline">This request is {stateWord}</Badge>` branch (the non-PENDING side), render:

```tsx
      {canReturn ? (
        <Button type="button" variant="outline" onClick={onReturn}>
          Return items to stock
        </Button>
      ) : null}
```

- [ ] **Step 6: Wire into `pulls.tsx`**

Add imports `PullReturnDialog`, `buildPullReturnPayload`, `canReturnPull`, `type ReturnDraft`, `ProjectPullReturnCreate`, and `useRef` is already imported. Add state + mutation after `cancelMutation`:

```tsx
  const [returnOpen, setReturnOpen] = useState(false)
  // One key per return attempt: reused on retry so a lost response can't
  // return twice; replaced only after a success.
  const returnKeyRef = useRef<string>(crypto.randomUUID())
  const returnMutation = useMutation<
    ProjectPullPublic,
    ApiError,
    { pullId: string; requestBody: ProjectPullReturnCreate }
  >({
    mutationFn: (vars) => ProjectPullsService.returnProjectPull(vars),
    onSuccess: () => {
      returnKeyRef.current = crypto.randomUUID()
      queryClient.invalidateQueries({ queryKey: ["project-pulls"] })
      showSuccessToast("Items returned to stock.")
      setReturnOpen(false)
    },
    onError: (err: ApiError) =>
      showErrorToast(extractErrorMessage(err), "Items not returned"),
  })
```

Pass to `<PullFulfillPanel ...>`:

```tsx
          canReturn={canReturnPull(selectedPull)}
          onReturn={() => setReturnOpen(true)}
```

and right after the `PullFulfillPanel` element, inside the same branch, wrap both in a fragment and add:

```tsx
          <PullReturnDialog
            pull={selectedPull}
            open={returnOpen}
            onOpenChange={setReturnOpen}
            isPending={returnMutation.isPending}
            onSubmit={(draft: ReturnDraft) =>
              returnMutation.mutate({
                pullId: selectedPull.id,
                requestBody: buildPullReturnPayload(draft, returnKeyRef.current),
              })
            }
          />
```

Also change the cancel toast to `"Request cancelled — stock put back."` and make its `onError` show the server reason: `onError: (err: ApiError) => showErrorToast(extractErrorMessage(err), "Request not cancelled")` (type the mutation `useMutation<ProjectPullPublic, ApiError, string>`).

- [ ] **Step 7: `PullQueue.tsx` — Cancel on any waiting request**

Replace the comment + `cancellable` with:

```tsx
  // Cancel on a waiting request puts its stock back; on a SHORT one it only
  // closes the request (given-out stock stays out — use Return for that).
  const cancellable =
    isAdmin && (pull.state === "PENDING" || pull.state === "SHORT")
```

- [ ] **Step 8: Consumed items — show returns** (`project.$projectId.tsx`, `ConsumedItems`)

Inside the row map, add `const returned = r.event_type === "RETURNED"` and change the qty and cost cells to:

```tsx
                    <TableCell className="num text-right">
                      {returned ? `−${r.quantity}` : r.quantity}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {returned ? "Returned · " : ""}
                      {new Date(r.occurred_at).toLocaleString()}
                    </TableCell>
                    <TableCell className="num text-right">
                      {returned ? `−${formatThb(r.total_cost_thb)}` : formatThb(r.total_cost_thb)}
                    </TableCell>
```

Update the component comment: "one row per PROJECT_OUT or pull RETURNED movement".

- [ ] **Step 9: Typecheck, lint, unit tests**

Run (from `frontend/`): `bun run build` (tsc + vite) then `bunx biome check src/lib/pull-return.ts src/lib/pull-return.test.ts src/components/pos/PullReturnDialog.tsx src/components/pos/PullFulfillPanel.tsx src/components/pos/PullQueue.tsx src/routes/_layout/pulls.tsx "src/routes/_layout/project.\$projectId.tsx"` then `bun run test:unit`.
Expected: build OK, biome clean on these files (don't run repo-wide `biome lint --write` — it churns everything), all vitest PASS.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/client frontend/src/lib/pull-return.ts frontend/src/lib/pull-return.test.ts frontend/src/components/pos/PullReturnDialog.tsx frontend/src/components/pos/PullFulfillPanel.tsx frontend/src/components/pos/PullQueue.tsx frontend/src/routes/_layout/pulls.tsx "frontend/src/routes/_layout/project.\$projectId.tsx"
git commit -m "feat(pulls): return items dialog, cancel puts stock back, returns in consumed items"
```

Note `frontend/src/client/*.gen.ts` already show as modified in the starting tree (CRLF churn): check `git diff src/client` contains only the new schema before staging.

---

### Task 8: E2E + docs

**Files:**
- Create: `frontend/tests/pull-return.spec.ts`
- Modify: `frontend/tests/pulls.spec.ts:274-279`
- Modify: `CLAUDE.md` (Project Status)

- [ ] **Step 1: Flip the old assertion in `pulls.spec.ts`**

At ~274-279, replace the "no Cancel" comment and `toHaveCount(0)` with:

```ts
    // Cancel is offered: cancelling a waiting request now puts its stock back.
    await expect(row.getByRole("button", { name: "Cancel" })).toBeVisible()
```

(Only if that row belongs to an admin session — the spec runs as the superuser, so yes.)

- [ ] **Step 2: Write `pull-return.spec.ts`**

```ts
import { expect, test } from "@playwright/test"

import {
  CustomersService,
  LoginService,
  OpenAPI,
  ProductsService,
  ProjectPullsService,
  ProjectsService,
  ReceiptsService,
  SearchService,
  SuppliersService,
} from "../src/client"
import { firstSuperuser, firstSuperuserPassword } from "./config.ts"

// Browser E2E for pull returns (design 2026-09-21). Same harness as
// pulls.spec.ts: Node-side SDK seeding, random suffixes for the shared dev
// DB. Run with `--workers=1`.

OpenAPI.BASE = `${process.env.VITE_API_URL}`

const rand = () => Math.random().toString(36).slice(2, 10)
const ON_HAND = 5
const REQUESTED = 3

async function onHand(sku: string): Promise<number> {
  return (await SearchService.searchSku({ sku })).total_on_hand
}

/** A part with ON_HAND in stock and a pull that took REQUESTED of it. */
async function seedPull() {
  const r = rand()
  const product = await ProductsService.createProduct({
    requestBody: {
      sku: `PRET-${r}`,
      model_name: `Return Part ${r}`,
      tracking_mode: "QUANTITY",
      retail_price_thb: "200.00",
      repair_price_thb: "80.00",
    },
  })
  const supplier = await SuppliersService.createSupplier({
    requestBody: { name: `Return Supplier ${r}` },
  })
  const customer = await CustomersService.createCustomer({
    requestBody: { name: `Return Customer ${r}` },
  })
  const project = await ProjectsService.createProject({
    requestBody: { code: `PRJ-${r}`, name: `Return Project ${r}`, customer_id: customer.id },
  })
  await ReceiptsService.receiveQuantity({
    requestBody: {
      product_id: product.id,
      supplier_id: supplier.id,
      received_qty: ON_HAND,
      purchase_cost_thb: "60.00",
      idempotency_key: crypto.randomUUID(),
    },
  })
  const pull = await ProjectPullsService.createProjectPull({
    requestBody: {
      project_id: project.id,
      lines: [{ line_kind: "PART", product_id: product.id, requested_qty: REQUESTED }],
    },
  })
  return { r, product, pull }
}

test.describe("Pull returns", () => {
  test.beforeAll(async () => {
    const tok = await LoginService.loginAccessToken({
      formData: { username: firstSuperuser, password: firstSuperuserPassword },
    })
    OpenAPI.TOKEN = tok.access_token
  })

  test("return 2 of 3 from a handed-out pull puts them back on hand", async ({ page }) => {
    const { r, product, pull } = await seedPull()
    await ProjectPullsService.fulfillProjectPull({
      pullId: pull.id,
      requestBody: { lines: [] }, // omitted lines default to full → FULFILLED
    })
    expect(await onHand(product.sku)).toBe(ON_HAND - REQUESTED)

    await page.goto("/pulls")
    // The queue defaults to waiting requests; a done one needs "Show all".
    await page.getByRole("button", { name: "Show all (incl. completed)" }).click()
    await page
      .getByRole("row")
      .filter({ hasText: `Return Project ${r}` })
      .getByRole("button", { name: "Give out parts" })
      .click()

    await page.getByRole("button", { name: "Return items to stock" }).click()
    const dialog = page.getByRole("dialog")
    const more = dialog.getByRole("button", { name: /Return more/ })
    await more.click()
    await more.click()
    await dialog.getByRole("button", { name: "Return 2 items" }).click()
    await expect(page.getByText("Items returned to stock.")).toBeVisible()

    await expect.poll(() => onHand(product.sku)).toBe(ON_HAND - REQUESTED + 2)
  })

  test("cancel a waiting pull puts its stock back", async ({ page }) => {
    const { r, product } = await seedPull()
    expect(await onHand(product.sku)).toBe(ON_HAND - REQUESTED)

    await page.goto("/pulls")
    await page
      .getByRole("row")
      .filter({ hasText: `Return Project ${r}` })
      .getByRole("button", { name: "Cancel" })
      .click()
    await expect(page.getByText("Request cancelled — stock put back.")).toBeVisible()
    await expect.poll(() => onHand(product.sku)).toBe(ON_HAND)
  })
})
```

The desktop layout renders rows (`getByRole("row")`); Playwright's default viewport is desktop, so `useIsMobile` is false.

- [ ] **Step 3: Restore the dev DB after the backend runs, then run E2E**

Run (from `backend/`): `python -m app.initial_data && python -m app.seed_demo` inside the backend container (`docker compose exec backend ...`).
Run (from `frontend/`): `E2E_SKIP_DB_RESET=1 VITE_API_URL=http://localhost:8000 bunx playwright test tests/pull-return.spec.ts tests/pulls.spec.ts tests/pull-fulfill.spec.ts tests/pull-create.spec.ts --workers=1`
Expected: all PASS.

- [ ] **Step 4: Update CLAUDE.md Project Status** — add one bullet after the "Sale returns" bullet:

```markdown
- **Project pull returns** (2026-09-21, no migration): staff and admin can put stock from a settled pull back (`POST /project-pulls/{id}/returns`), and admin Cancel on a waiting pull now puts its stock back instead of 409ing. Returns append `RETURNED` movements with `project_pull_id` that reverse the pull's own `PROJECT_OUT` ones (units via the new `PROJECT_OUT -> IN_STOCK` edge; parts onto the exact batches). What is returnable is read from the ledgers per (pull, product), so create now allows **one PART line per product**. Project COGS nets returns in the month they come back. Design: `docs/superpowers/specs/2026-09-21-pull-return-design.md`.
```

- [ ] **Step 5: Commit**

```bash
git add frontend/tests/pull-return.spec.ts frontend/tests/pulls.spec.ts CLAUDE.md
git commit -m "test(pulls): e2e for returns and cancel-restores-stock; document"
```

---

### Task 9: Review and PR (high-risk path)

- [ ] **Step 1:** Full backend suite: `uv run pytest -q` (from `backend/`). Compare failure names against memory `dev-known-failing-backend-tests`; nothing new may fail. Then restore the dev DB (Task 8 Step 3).
- [ ] **Step 2:** `alembic check` inside the backend container → "No new upgrade operations detected."
- [ ] **Step 3:** Run superpowers:requesting-code-review, **plus** `ecc:database-reviewer` and `ecc:security-reviewer` (CLAUDE.md: mandatory on stock-movement / money changes). Fix findings; re-run affected tests.
- [ ] **Step 4:** Push and open the PR into `dev` with `create-pr`. Wait for CI `test-backend`; the `test-playwright` job has been failing at DB reset since August (not a regression — see memory `no-ci-runs-ever`).
- [ ] **Step 5:** Before releasing to `production`: check prod for legacy pulls with two PART lines for one product (Pulls screen as admin, or `GET /api/v1/project-pulls?limit=500` on `api.castranova.cloud`). If any exist, they still work — their whole product balance is returnable from the first line.
