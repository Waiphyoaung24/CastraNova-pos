# CastraNova-POS Part 4 (4.1 + 4.2) + Pre-work Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Each task is TDD: write the failing test, watch it fail, write minimal code, watch it pass, commit.

**Goal:** Close the open-signup security bug, kill the persistent Alembic autogenerate drift, then build the Stock-on-Hand dashboard (FR-012) and the role-tiered customer/project detail dashboards (FR-020) — financial fields **absent** (not blanked) for `YGN_STAFF`.

**Architecture:** Read-only aggregation endpoints over the existing append-only ledgers + cached state columns. Stock-on-Hand totals are computed in a **single annotation pass** using correlated `func.coalesce(func.sum(...), 0).scalar_subquery()` (the InvenTree `annotate_total_stock` pattern, ported to SQLAlchemy) — never a per-row model property (N+1 trap). Role-tiering uses **two distinct Pydantic response schemas per dashboard** (`…StaffPublic` vs `…AdminPublic`); the route validates `data` against the schema for the caller's role and returns it, so redacted fields are physically absent from the JSON (spec §6.5 / S7). This is strictly safer than per-field redaction (InvenTree pitfall #6).

**Tech Stack:** FastAPI, SQLModel/SQLAlchemy (`func.sum`, `func.coalesce`, `scalar_subquery`, `case`), Postgres, Alembic, pytest. Frontend: TanStack Router + generated SDK (`bun run generate-client`).

**Reference:**
- System design spec: `docs/superpowers/specs/2026-05-23-castranova-pos-system-design.md` (§4.2, §5 Flow F, §6.1, §6.5, §8, FR-012, FR-020).
- Aggregation join reference (reuse the join shapes): `backend/app/crud.py` → `channel_margin_report()` (≈ line 2274). Scope its joins by `customer_id` / `project_id` instead of a date window.
- InvenTree (domain reference only, Django): `annotate_total_stock` in `src/backend/InvenTree/part/filters.py`; the lessons are **(a)** one canonical in-stock predicate reused everywhere, **(b)** `coalesce(sum, 0)` on every total, **(c)** all totals annotated once at the query layer.

**Conventions (match the repo):**
- Models in `backend/app/models.py`: `XBase`/`XPublic` split; money is `Decimal` + `sa_column=Column(Numeric(12, 2))`.
- All DB access in `backend/app/crud.py`; functions keyword-only: `def fn(*, session: Session, ...)`.
- Routes: one file per resource in `backend/app/api/routes/`, registered in `backend/app/api/main.py`. Deps: `SessionDep`, `CurrentUser`, `get_current_user`, `get_admin`, `AdminUser` from `app.api.deps`.
- Tests under `backend/tests/` mirroring `app/`. Fixtures from `conftest.py`: `db`, `client`, `superuser_token_headers`, `normal_user_token_headers`, `staff_token_headers`.
- Run one test: `cd backend && uv run pytest <path>::<test> -v`. Full suite: `cd backend && uv run pytest -q`. Lint/type: `cd backend && uv run ruff check . && uv run mypy app`.
- **This work is high-risk (role-tiering on financial data).** Per CLAUDE.md §5, the Review stage must run `requesting-code-review` **plus** `ecc:database-reviewer` + `ecc:security-reviewer` before the PR (Task 7).
- **Commit cadence:** one commit per task. Work on branch `dev` (current).

---

## File Structure

| File | Created/Modified | Responsibility |
|---|---|---|
| `backend/app/api/routes/users.py` | Modify | Remove the unauthenticated `POST /users/signup` route |
| `backend/app/models.py` | Modify | Remove unused `UserRegister`; add `foreign_key=` to movement FK fields + partial-index `__table_args__`; add dashboard response schemas |
| `frontend/src/routes/signup.tsx`, `frontend/src/hooks/useAuth.ts`, `frontend/src/routes/login.tsx` | Modify/Delete | Remove the public signup page, `signUpMutation`, and the login-page link |
| `backend/app/alembic/versions/*_m022_rename_notificationlog_index.py` | Create | Rename `ix_notification_log_target_user_id` → `ix_notificationlog_target_user_id` |
| `backend/app/api/routes/dashboards.py` | Create | `GET /dashboards/stock-on-hand` + per-product batch drill-down |
| `backend/app/crud.py` | Modify | `stock_on_hand()` aggregation; `get_customer_dashboard()`; `get_project_dashboard()` |
| `backend/app/api/routes/customers.py` | Modify | `GET /customers/{id}/dashboard` (role dispatch) |
| `backend/app/api/routes/projects.py` | Modify | `GET /projects/{id}/dashboard` (role dispatch) |
| `backend/tests/api/routes/test_dashboards.py` | Create | Stock-on-Hand correctness + filters + perf |
| `backend/tests/api/routes/test_customer_dashboard.py` | Create | Role redaction (raw HTTP) + aggregation correctness |
| `backend/tests/api/routes/test_project_dashboard.py` | Create | Role redaction (raw HTTP) + aggregation correctness |
| `backend/tests/api/routes/test_users.py` | Modify | Regression: `/users/signup` returns 404 |

---

# Pre-work

### Task 0: Close the open `POST /users/signup` self-registration (FR-004)

The template's signup route lets anyone self-register; `UserBase` defaults `role=BKK_ADMIN`, so this is unauthenticated admin-account creation. Users are admin-provisioned via the existing `POST /users/` (superuser-guarded). Remove the route end-to-end. The frontend has a `/signup` page wired to it (`useAuth.ts` `signUpMutation`, `routes/signup.tsx`, a link in `routes/login.tsx`) — remove those too, then regenerate the SDK.

**Files:**
- Modify: `backend/app/api/routes/users.py` (delete `register_user`, line ≈145–158)
- Modify: `backend/app/models.py` (delete `UserRegister`, line ≈139) and `backend/app/api/routes/users.py` import of `UserRegister`
- Modify: `backend/tests/api/routes/test_users.py` (replace any signup-success test with a 404 regression test)
- Modify/Delete (frontend): `frontend/src/hooks/useAuth.ts`, `frontend/src/routes/signup.tsx`, `frontend/src/routes/login.tsx`

- [ ] **Step 1: Write the failing regression test.** In `backend/tests/api/routes/test_users.py` add (and delete any existing test that asserts signup succeeds, e.g. `test_register_user`):

```python
def test_signup_route_removed(client: TestClient) -> None:
    # FR-004: user creation is admin-only; the open signup route must not exist.
    r = client.post(
        f"{settings.API_V1_STR}/users/signup",
        json={"email": "intruder@example.com", "password": "changethis123"},
    )
    assert r.status_code == 404
```

- [ ] **Step 2: Run it — expect FAIL.** `cd backend && uv run pytest tests/api/routes/test_users.py::test_signup_route_removed -v` → FAIL (route still returns 200/400, not 404). Also grep the test file for an existing `signup`/`register` success test and delete it so it doesn't fail after removal.

- [ ] **Step 3: Remove the backend route + schema.** In `users.py` delete the entire `register_user` function and its `@router.post("/signup", …)` decorator, and remove `UserRegister` from the `app.models` import line. In `models.py` delete the `class UserRegister(SQLModel): …` block. Confirm nothing else imports `UserRegister`: `cd backend && grep -rn "UserRegister" app` → only stale hits resolved.

- [ ] **Step 4: Run backend checks.** `cd backend && uv run pytest tests/api/routes/test_users.py -v` → PASS, and `uv run ruff check . && uv run mypy app` → clean (removes the now-unused import).

- [ ] **Step 5: Remove the frontend signup surface.** Delete `frontend/src/routes/signup.tsx`. In `frontend/src/hooks/useAuth.ts` remove the `UserRegister` import, the `signUpMutation` definition, and any `signUp` returned from the hook. In `frontend/src/routes/login.tsx` remove the “Sign up” `RouterLink` block (≈ line 134). Then regenerate the SDK so the removed operation drops out of the client:

```bash
cd frontend && bun run generate-client
```

Verify the app still type-checks: `cd frontend && bun run build` (or the repo's tsc/biome check) → no references to `registerUser`/`signUp` remain.

- [ ] **Step 6: Commit.**

```bash
git add backend/app/api/routes/users.py backend/app/models.py backend/tests/api/routes/test_users.py frontend/src
git commit -m "fix(security): remove unauthenticated /users/signup self-registration (FR-004)"
```

---

### Task 1: Align movement-model FK declarations to kill autogenerate drift

`UnitMovement.service_ticket_id`, `UnitMovement.project_pull_id`, `PartMovement.service_ticket_id`, `PartMovement.project_pull_id` are declared as bare `Field(default=None)` with **no** `foreign_key=`. The DB FKs (`fk_unitmovement_project_pull_id`, etc.) + partial indexes were wired manually in M012, so every `alembic revision --autogenerate` wants to DROP them. Mirror how `sale_id` is declared (`foreign_key="sale.id"`, which is drift-free) and declare the partial indexes in `__table_args__` so the model matches the live DB exactly. **No schema migration is produced by this task** — it only makes the model match the DB. The success gate is an empty autogenerate diff.

**Files:**
- Modify: `backend/app/models.py` (`UnitMovement` ≈ line 523–526 and its `__table_args__`; `PartMovement` ≈ line 676–679 and its `__table_args__`)

- [ ] **Step 1: Make the four FK fields declare their target.** Change each bare field to mirror `sale_id`. The existing DB FK matches on (column, referred table, referred column), so naming is irrelevant to the diff:

```python
# UnitMovement (≈ line 524-525)
    service_ticket_id: uuid.UUID | None = Field(
        default=None, foreign_key="serviceticket.id"
    )
    project_pull_id: uuid.UUID | None = Field(
        default=None, foreign_key="projectpull.id"
    )
```

```python
# PartMovement (≈ line 677-678)
    service_ticket_id: uuid.UUID | None = Field(
        default=None, foreign_key="serviceticket.id"
    )
    project_pull_id: uuid.UUID | None = Field(
        default=None, foreign_key="projectpull.id"
    )
```

- [ ] **Step 2: Declare the M012 partial indexes in `__table_args__`.** So autogenerate doesn't try to drop the partial (sparse-nullable) indexes. Add to each movement model's existing `__table_args__` tuple (import `Index`, `text` from sqlalchemy at top of models.py if not already imported):

```python
# In UnitMovement.__table_args__  (keep existing UniqueConstraint/Index entries; append)
        Index(
            "ix_unitmovement_project_pull_id", "project_pull_id",
            unique=False, postgresql_where=text("project_pull_id IS NOT NULL"),
        ),
```

```python
# In PartMovement.__table_args__  (append)
        Index(
            "ix_partmovement_project_pull_id", "project_pull_id",
            unique=False, postgresql_where=text("project_pull_id IS NOT NULL"),
        ),
```

(There is no partial index on `service_ticket_id` in M012, so do not add one for it.)

- [ ] **Step 3: Verify the model now matches the DB — the drift-dead gate.** Apply head first, then probe:

```bash
cd backend && uv run alembic upgrade head
uv run alembic revision --autogenerate -m "drift probe DELETE ME"
```

Open the generated file in `app/alembic/versions/`. **`upgrade()` and `downgrade()` must contain only `pass` / no `op.*` operations** for the `project_pull_id`/`service_ticket_id` FKs and the two partial indexes. (The notificationlog index rename is handled in Task 2 and *may still appear here* — that is expected and fine for this task.) If FK drops still appear, the `foreign_key=` target string is wrong (check table name casing: SQLModel table names are lowercased class names — `serviceticket`, `projectpull`). Iterate until those FK/index ops are gone.

- [ ] **Step 4: Delete the probe migration** (it must not be committed):

```bash
rm app/alembic/versions/*drift_probe_delete_me*.py
```

- [ ] **Step 5: Run the suite — nothing broke.** `cd backend && uv run pytest -q` → all green; `uv run ruff check . && uv run mypy app` → clean.

- [ ] **Step 6: Commit.**

```bash
git add backend/app/models.py
git commit -m "fix(models): declare movement FK targets + partial indexes to end autogenerate drift"
```

---

### Task 2: Migration M022 — rename the notificationlog index to match the model

The DB index is `ix_notification_log_target_user_id` (manual string in M007/M019); the model's `index=True` on `notificationlog.target_user_id` generates `ix_notificationlog_target_user_id`. Rename the DB index so the names match and autogenerate is fully clean.

**Files:**
- Create: `backend/app/alembic/versions/<hash>_m022_rename_notificationlog_index.py`

- [ ] **Step 1: Autogenerate the rename.** With Task 1 already applied:

```bash
cd backend && uv run alembic revision --autogenerate -m "M022 rename notificationlog target_user_id index"
```

The generated migration should contain a `drop_index('ix_notification_log_target_user_id', …)` + `create_index(op.f('ix_notificationlog_target_user_id'), …)` (or Alembic may render it as two ops). If autogenerate instead emits the partial-index/FK ops, Task 1 was incomplete — go back. Edit the file so `upgrade()` does exactly the rename and `downgrade()` reverses it. A hand-written form (preferred for clarity):

```python
def upgrade():
    op.drop_index("ix_notification_log_target_user_id", table_name="notificationlog")
    op.create_index(
        op.f("ix_notificationlog_target_user_id"),
        "notificationlog", ["target_user_id"], unique=False,
    )


def downgrade():
    op.drop_index(op.f("ix_notificationlog_target_user_id"), table_name="notificationlog")
    op.create_index(
        "ix_notification_log_target_user_id",
        "notificationlog", ["target_user_id"], unique=False,
    )
```

- [ ] **Step 2: Apply it.** `cd backend && uv run alembic upgrade head` → succeeds.

- [ ] **Step 3: Final drift gate — empty autogenerate.** This is the proof the drift is dead:

```bash
cd backend && uv run alembic revision --autogenerate -m "final drift probe DELETE ME"
```

Open the file: **`upgrade()` and `downgrade()` must be empty (only `pass`).** Then delete it: `rm app/alembic/versions/*final_drift_probe_delete_me*.py`. If anything remains, fix Task 1/2 before proceeding.

- [ ] **Step 4: Run the suite.** `cd backend && uv run pytest -q` → green.

- [ ] **Step 5: Commit.**

```bash
git add backend/app/alembic/versions/*m022*notificationlog*.py
git commit -m "fix(db): M022 rename notificationlog index to match model (autogenerate clean)"
```

---

# Part 4.1 — Stock-on-Hand dashboard (FR-012)

### Task 3: `stock_on_hand()` aggregation + `/dashboards/stock-on-hand` route

Server-side aggregation, both roles. QUANTITY rows → `sum(part_batch.remaining_qty)` per product; SERIALIZED rows → count of `unit` rows with `current_state == IN_STOCK`. Filterable by `category`, `supplier`, `customer`. **No cost/COGS fields** in this view (quantities aren't financial → single schema, no role-tiering). One annotation pass; correlated scalar subqueries; `coalesce(…, 0)` on every total.

**Files:**
- Modify: `backend/app/models.py` (add `StockOnHandRow`, `StockOnHandResponse`, `BatchDrillRow` public schemas)
- Modify: `backend/app/crud.py` (add `stock_on_hand()`, `stock_on_hand_batches()`)
- Create: `backend/app/api/routes/dashboards.py`
- Modify: `backend/app/api/main.py` (register `dashboards.router`)
- Create: `backend/tests/api/routes/test_dashboards.py`

- [ ] **Step 1: Write the failing tests.** Create `backend/tests/api/routes/test_dashboards.py`. Use the existing receive flows to seed stock (mirror `test_receipts_quantity.py` / `test_receipts_serialized.py` for the request shapes).

```python
import uuid
from fastapi.testclient import TestClient
from sqlmodel import Session
from app.core.config import settings


def test_stock_on_hand_sums_quantity_batches(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    # Seed: one QUANTITY product with two batches (qty 8 + 12) via the receive API,
    # one SERIALIZED product with 2 received units. (Use helpers mirroring the
    # receipts tests; create product+supplier, then POST /receipts/quantity twice
    # and /receipts/serialized once.)
    sku_qty, prod_qty_id = _seed_quantity_with_batches(client, staff_token_headers, db, [8, 12])
    sku_ser, prod_ser_id = _seed_serialized_units(client, staff_token_headers, db, 2)

    r = client.get(
        f"{settings.API_V1_STR}/dashboards/stock-on-hand", headers=staff_token_headers
    )
    assert r.status_code == 200
    rows = {row["sku"]: row for row in r.json()["rows"]}
    assert rows[sku_qty]["tracking_mode"] == "QUANTITY"
    assert rows[sku_qty]["quantity_on_hand"] == 20      # 8 + 12, coalesced
    assert rows[sku_ser]["tracking_mode"] == "SERIALIZED"
    assert rows[sku_ser]["quantity_on_hand"] == 2       # IN_STOCK unit count
    # No financial fields leak into the on-hand view:
    assert "cost" not in str(rows[sku_qty]).lower()


def test_stock_on_hand_filter_by_category(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    sku_a, _ = _seed_quantity_with_batches(client, staff_token_headers, db, [5], category="compressor")
    sku_b, _ = _seed_quantity_with_batches(client, staff_token_headers, db, [5], category="fan")
    r = client.get(
        f"{settings.API_V1_STR}/dashboards/stock-on-hand?category=compressor",
        headers=staff_token_headers,
    )
    skus = {row["sku"] for row in r.json()["rows"]}
    assert sku_a in skus and sku_b not in skus


def test_stock_on_hand_requires_auth(client: TestClient) -> None:
    r = client.get(f"{settings.API_V1_STR}/dashboards/stock-on-hand")
    assert r.status_code == 401


def test_batch_drilldown_lists_active_batches(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    sku, prod_id = _seed_quantity_with_batches(client, staff_token_headers, db, [8, 12])
    r = client.get(
        f"{settings.API_V1_STR}/dashboards/stock-on-hand/{prod_id}/batches",
        headers=staff_token_headers,
    )
    assert r.status_code == 200
    qtys = sorted(b["remaining_qty"] for b in r.json())
    assert qtys == [8, 12]
```

Write the two `_seed_*` helpers at the top of the test module (create supplier + product via admin headers, then receive via staff headers). Keep them local to this file.

- [ ] **Step 2: Run — expect FAIL.** `cd backend && uv run pytest tests/api/routes/test_dashboards.py -v` → FAIL (route/schema missing).

- [ ] **Step 3: Add the response schemas** in `models.py` (near the other `*Public` report schemas):

```python
class StockOnHandRow(SQLModel):
    product_id: uuid.UUID
    sku: str
    model_name: str
    category: str | None
    tracking_mode: TrackingMode
    quantity_on_hand: int


class StockOnHandResponse(SQLModel):
    rows: list[StockOnHandRow]


class BatchDrillRow(SQLModel):
    batch_no: str
    remaining_qty: int
    received_at: datetime
    # No purchase_cost_thb: COGS stays admin-only; this view is both-roles.
```

- [ ] **Step 4: Implement the aggregation** in `crud.py`. Use the InvenTree-derived pattern: one canonical in-stock predicate per mode, correlated scalar subqueries, `coalesce(…, 0)`. Reuse imports already present (`select`, `func`, `col`, `case` — add `case` to the sqlalchemy import if absent).

```python
def stock_on_hand(
    *,
    session: Session,
    category: str | None = None,
    supplier_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
) -> StockOnHandResponse:
    """On-hand totals per product (FR-012). QUANTITY = sum(remaining_qty);
    SERIALIZED = count of IN_STOCK units. Single set-based pass; no per-row
    queries; coalesced so products with zero stock return 0 (InvenTree pattern)."""
    # QUANTITY total: correlated sum of remaining_qty, optionally supplier-scoped.
    qty_pred = [
        col(PartBatch.product_id) == col(Product.id),
        PartBatch.remaining_qty > 0,
    ]
    if supplier_id is not None:
        qty_pred.append(col(PartBatch.supplier_id) == supplier_id)
    qty_subq = (
        select(func.coalesce(func.sum(PartBatch.remaining_qty), 0))
        .where(*qty_pred)
        .correlate(Product)
        .scalar_subquery()
    )
    # SERIALIZED total: correlated count of IN_STOCK units, optionally supplier-scoped.
    unit_pred = [
        col(Unit.product_id) == col(Product.id),
        Unit.current_state == UnitState.IN_STOCK,
    ]
    if supplier_id is not None:
        unit_pred.append(col(Unit.supplier_id) == supplier_id)
    unit_subq = (
        select(func.coalesce(func.count(Unit.id), 0))
        .where(*unit_pred)
        .correlate(Product)
        .scalar_subquery()
    )
    on_hand = case(
        (Product.tracking_mode == TrackingMode.SERIALIZED, unit_subq),
        else_=qty_subq,
    )
    stmt = select(
        Product.id, Product.sku, Product.model_name,
        Product.category, Product.tracking_mode,
        on_hand.label("quantity_on_hand"),
    ).where(Product.is_active == True)  # noqa: E712
    if category is not None:
        stmt = stmt.where(Product.category == category)
    stmt = stmt.order_by(col(Product.sku))
    rows = [
        StockOnHandRow(
            product_id=r[0], sku=r[1], model_name=r[2],
            category=r[3], tracking_mode=r[4], quantity_on_hand=int(r[5] or 0),
        )
        for r in session.exec(stmt).all()
    ]
    # customer filter: restrict to products this customer has ever transacted.
    if customer_id is not None:
        rows = _filter_rows_by_customer(session=session, rows=rows, customer_id=customer_id)
    return StockOnHandResponse(rows=rows)


def stock_on_hand_batches(
    *, session: Session, product_id: uuid.UUID
) -> list[BatchDrillRow]:
    """Per-product active batch drill-down (FR-012), oldest-first."""
    batches = session.exec(
        select(PartBatch)
        .where(col(PartBatch.product_id) == product_id, PartBatch.remaining_qty > 0)
        .order_by(col(PartBatch.received_at), col(PartBatch.id))
    ).all()
    return [
        BatchDrillRow(
            batch_no=b.batch_no, remaining_qty=b.remaining_qty, received_at=b.received_at
        )
        for b in batches
    ]
```

For the `customer` filter, add a small helper that collects product ids appearing in that customer's `sale_line` (via `sale`) and `service_ticket_part` (via `service_ticket`), then keeps only matching rows:

```python
def _filter_rows_by_customer(
    *, session: Session, rows: list[StockOnHandRow], customer_id: uuid.UUID
) -> list[StockOnHandRow]:
    sold = session.exec(
        select(SaleLine.product_id)
        .join(Sale, col(SaleLine.sale_id) == col(Sale.id))
        .where(col(Sale.customer_id) == customer_id, col(SaleLine.product_id).is_not(None))
    ).all()
    serviced = session.exec(
        select(ServiceTicketPart.product_id)
        .join(ServiceTicket, col(ServiceTicketPart.service_ticket_id) == col(ServiceTicket.id))
        .where(col(ServiceTicket.customer_id) == customer_id)
    ).all()
    allowed = {pid for pid in [*sold, *serviced] if pid is not None}
    return [row for row in rows if row.product_id in allowed]
```

- [ ] **Step 5: Add the route** — create `backend/app/api/routes/dashboards.py`:

```python
import uuid

from fastapi import APIRouter, Depends

from app import crud
from app.api.deps import SessionDep, get_current_user
from app.models import BatchDrillRow, StockOnHandResponse

router = APIRouter(prefix="/dashboards", tags=["dashboards"])


@router.get(
    "/stock-on-hand",
    response_model=StockOnHandResponse,
    dependencies=[Depends(get_current_user)],
)
def get_stock_on_hand(
    session: SessionDep,
    category: str | None = None,
    supplier: uuid.UUID | None = None,
    customer: uuid.UUID | None = None,
) -> StockOnHandResponse:
    return crud.stock_on_hand(
        session=session, category=category, supplier_id=supplier, customer_id=customer
    )


@router.get(
    "/stock-on-hand/{product_id}/batches",
    response_model=list[BatchDrillRow],
    dependencies=[Depends(get_current_user)],
)
def get_stock_on_hand_batches(
    session: SessionDep, product_id: uuid.UUID
) -> list[BatchDrillRow]:
    return crud.stock_on_hand_batches(session=session, product_id=product_id)
```

Register it in `backend/app/api/main.py`: add `dashboards` to the `from app.api.routes import (...)` block and `api_router.include_router(dashboards.router)`.

- [ ] **Step 6: Run — expect PASS.** `cd backend && uv run pytest tests/api/routes/test_dashboards.py -v` → PASS. Then `uv run ruff check . && uv run mypy app` → clean.

- [ ] **Step 7: Add the performance test** (proves the single-pass aggregation stays flat, per spec §6.1: P95 < 10s at 500 SKUs / 5000 batches). Keep it lightweight but meaningful — assert query count does not scale per-row, the real InvenTree lesson. Append to `test_dashboards.py`:

```python
def test_stock_on_hand_is_single_pass_not_n_plus_one(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    # Seed 50 QUANTITY products with a batch each (scaled-down stand-in for 500).
    for i in range(50):
        _seed_quantity_with_batches(
            client, staff_token_headers, db, [5], sku=f"PERF-{i:03d}"
        )
    from sqlalchemy import event
    from app.core.db import engine

    counter = {"n": 0}

    def _count(conn, cursor, statement, params, context, executemany):
        counter["n"] += 1

    event.listen(engine, "before_cursor_execute", _count)
    try:
        r = client.get(
            f"{settings.API_V1_STR}/dashboards/stock-on-hand", headers=staff_token_headers
        )
    finally:
        event.remove(engine, "before_cursor_execute", _count)
    assert r.status_code == 200
    assert len(r.json()["rows"]) >= 50
    # One aggregation query (+ a small constant for auth/session), NOT one per product.
    assert counter["n"] < 15
```

If `_seed_*` doesn't accept `sku=`/`category=` kwargs yet, extend the helpers. Run it → PASS. (If the count is borderline because of auth/session round-trips, tighten the listener to count only SELECTs against `product`/`partbatch`; the invariant is "not O(products)".)

- [ ] **Step 8: Commit.**

```bash
git add backend/app/models.py backend/app/crud.py backend/app/api/routes/dashboards.py backend/app/api/main.py backend/tests/api/routes/test_dashboards.py
git commit -m "feat(dashboards): stock-on-hand aggregation + batch drill-down (Task 4.1, FR-012)"
```

---

# Part 4.2 — Role-tiered customer & project dashboards (FR-020, S7)

### Task 4: Customer dashboard schemas + `get_customer_dashboard()` crud

Two response schemas: `CustomerDashboardStaffPublic` (transactions + projects, **no** cost/margin/budget) and `CustomerDashboardAdminPublic` (extends staff + lifetime sale/maintenance/project revenue·COGS·margin). Admin financial fields are **required** (non-optional `Decimal`) so a staff payload can never validate as the admin schema (the union-dispatch safety property). The crud computes everything; the route (Task 5) picks the schema by role.

**Files:**
- Modify: `backend/app/models.py` (schemas)
- Modify: `backend/app/crud.py` (`get_customer_dashboard()`)

- [ ] **Step 1: Write the failing crud test.** Create `backend/tests/api/routes/test_customer_dashboard.py` with a crud-level test first (route tests come in Task 5). Seed one customer with one completed sale (1 serialized unit) so revenue/COGS are known.

```python
import uuid
from sqlmodel import Session
from app import crud
from app.models import CustomerDashboardAdminPublic


def test_customer_dashboard_admin_aggregates_lifetime_sale(db: Session) -> None:
    # Seed a customer + a sale of one serialized unit priced 1200 cost 900 (use the
    # same helpers as test_sales_serialized.py to receive + sell).
    customer_id, expected_rev, expected_cogs = _seed_customer_with_one_sale(db)
    data = crud.get_customer_dashboard(session=db, customer_id=customer_id)
    admin = CustomerDashboardAdminPublic.model_validate(data)
    assert admin.lifetime_sale_revenue_thb == expected_rev
    assert admin.lifetime_sale_cogs_thb == expected_cogs
    assert admin.lifetime_sale_margin_thb == expected_rev - expected_cogs
```

- [ ] **Step 2: Run — expect FAIL.** `cd backend && uv run pytest tests/api/routes/test_customer_dashboard.py -v` → FAIL.

- [ ] **Step 3: Add the schemas** in `models.py`:

```python
class TransactionSummaryPublic(SQLModel):
    kind: str            # "SALE" | "MAINTENANCE" | "PROJECT_PULL"
    reference_id: uuid.UUID
    occurred_at: datetime


class ProjectSummaryStaffPublic(SQLModel):
    id: uuid.UUID
    code: str
    name: str
    status: ProjectStatus
    # No budget / consumed_cost — staff redaction.


class ProjectSummaryAdminPublic(ProjectSummaryStaffPublic):
    budget_thb: Decimal | None
    consumed_cost_thb: Decimal


class CustomerDashboardStaffPublic(SQLModel):
    customer: CustomerPublic
    transactions: list[TransactionSummaryPublic]
    active_projects: list[ProjectSummaryStaffPublic]
    closed_projects: list[ProjectSummaryStaffPublic]


class CustomerDashboardAdminPublic(CustomerDashboardStaffPublic):
    # Financial fields are REQUIRED so a staff payload cannot upcast to admin.
    lifetime_sale_revenue_thb: Decimal
    lifetime_sale_cogs_thb: Decimal
    lifetime_sale_margin_thb: Decimal
    lifetime_maintenance_revenue_thb: Decimal
    lifetime_maintenance_cogs_thb: Decimal
    lifetime_maintenance_margin_thb: Decimal
    lifetime_project_cogs_thb: Decimal
    # admin sees budget-bearing project rows:
    active_projects: list[ProjectSummaryAdminPublic]
    closed_projects: list[ProjectSummaryAdminPublic]
```

- [ ] **Step 4: Implement `get_customer_dashboard()`** in `crud.py`. Reuse the join shapes from `channel_margin_report()` but scope by `customer_id` (no date window). Return a plain dict carrying **all** fields (admin superset); the route validates against the role-appropriate schema, which drops extra keys for staff.

```python
def get_customer_dashboard(*, session: Session, customer_id: uuid.UUID) -> dict:
    """Lifetime per-channel revenue/COGS for one customer (FR-020). Returns the
    admin superset as a dict; the route validates it against the staff or admin
    schema so redacted fields are absent from the staff JSON (spec §6.5)."""
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")

    # SALE lifetime (all sales for this customer).
    sale_rev, sale_cogs = session.exec(
        select(
            func.coalesce(func.sum(Sale.total_thb), Decimal("0")),
            func.coalesce(func.sum(Sale.total_cogs_thb), Decimal("0")),
        ).where(col(Sale.customer_id) == customer_id)
    ).one()

    # MAINTENANCE lifetime (parts of this customer's closed tickets).
    maint_rev = session.exec(
        select(
            func.coalesce(
                func.sum(ServiceTicketPart.quantity * ServiceTicketPart.unit_price_thb),
                Decimal("0"),
            )
        )
        .join(ServiceTicket, col(ServiceTicketPart.service_ticket_id) == col(ServiceTicket.id))
        .where(col(ServiceTicket.customer_id) == customer_id,
               col(ServiceTicket.closed_at).is_not(None))
    ).one()
    maint_cogs = session.exec(
        select(func.coalesce(func.sum(CostLine.total_cost_thb), Decimal("0")))
        .join(PartMovement, col(CostLine.part_movement_id) == col(PartMovement.id))
        .join(ServiceTicket, col(PartMovement.service_ticket_id) == col(ServiceTicket.id))
        .where(PartMovement.event_type == MovementType.MAINTENANCE_OUT,
               col(ServiceTicket.customer_id) == customer_id)
    ).one()

    # PROJECT lifetime COGS (cost-only) via this customer's pulls.
    proj_part_cogs = session.exec(
        select(func.coalesce(func.sum(CostLine.total_cost_thb), Decimal("0")))
        .join(PartMovement, col(CostLine.part_movement_id) == col(PartMovement.id))
        .join(ProjectPull, col(PartMovement.project_pull_id) == col(ProjectPull.id))
        .where(PartMovement.event_type == MovementType.PROJECT_OUT,
               col(ProjectPull.customer_id) == customer_id)
    ).one()
    proj_unit_cogs = session.exec(
        select(func.coalesce(func.sum(Unit.purchase_cost_thb), Decimal("0")))
        .select_from(UnitMovement)
        .join(ProjectPull, col(UnitMovement.project_pull_id) == col(ProjectPull.id))
        .join(Unit, col(UnitMovement.unit_id) == col(Unit.id))
        .where(UnitMovement.event_type == MovementType.PROJECT_OUT,
               col(ProjectPull.customer_id) == customer_id)
    ).one()

    projects = session.exec(
        select(Project).where(col(Project.customer_id) == customer_id)
    ).all()
    active = [p for p in projects if p.status == ProjectStatus.ACTIVE]
    closed = [p for p in projects if p.status == ProjectStatus.CLOSED]

    def _project_row(p: Project) -> dict:
        consumed = _project_consumed_cost(session=session, project_id=p.id)
        return {"id": p.id, "code": p.code, "name": p.name, "status": p.status,
                "budget_thb": p.budget_thb, "consumed_cost_thb": consumed}

    transactions = _customer_transactions(session=session, customer_id=customer_id)

    return {
        "customer": customer,
        "transactions": transactions,
        "active_projects": [_project_row(p) for p in active],
        "closed_projects": [_project_row(p) for p in closed],
        "lifetime_sale_revenue_thb": _q(sale_rev),
        "lifetime_sale_cogs_thb": _q(sale_cogs),
        "lifetime_sale_margin_thb": _q(sale_rev - sale_cogs),
        "lifetime_maintenance_revenue_thb": _q(maint_rev),
        "lifetime_maintenance_cogs_thb": _q(maint_cogs),
        "lifetime_maintenance_margin_thb": _q(maint_rev - maint_cogs),
        "lifetime_project_cogs_thb": _q(proj_part_cogs + proj_unit_cogs),
    }
```

Add the two small helpers (used here and by Task 6):

```python
def _project_consumed_cost(*, session: Session, project_id: uuid.UUID) -> Decimal:
    """Total FIFO part cost + pulled-unit cost consumed by a project (cost-only)."""
    part_cogs = session.exec(
        select(func.coalesce(func.sum(CostLine.total_cost_thb), Decimal("0")))
        .join(PartMovement, col(CostLine.part_movement_id) == col(PartMovement.id))
        .join(ProjectPull, col(PartMovement.project_pull_id) == col(ProjectPull.id))
        .where(PartMovement.event_type == MovementType.PROJECT_OUT,
               col(ProjectPull.project_id) == project_id)
    ).one()
    unit_cogs = session.exec(
        select(func.coalesce(func.sum(Unit.purchase_cost_thb), Decimal("0")))
        .select_from(UnitMovement)
        .join(ProjectPull, col(UnitMovement.project_pull_id) == col(ProjectPull.id))
        .join(Unit, col(UnitMovement.unit_id) == col(Unit.id))
        .where(UnitMovement.event_type == MovementType.PROJECT_OUT,
               col(ProjectPull.project_id) == project_id)
    ).one()
    return _q(part_cogs + unit_cogs)


def _customer_transactions(*, session: Session, customer_id: uuid.UUID) -> list[dict]:
    """Non-financial transaction list (sales + closed tickets + pulls), newest-first."""
    out: list[dict] = []
    for s in session.exec(select(Sale).where(col(Sale.customer_id) == customer_id)).all():
        out.append({"kind": "SALE", "reference_id": s.id, "occurred_at": s.sold_at})
    for t in session.exec(
        select(ServiceTicket).where(col(ServiceTicket.customer_id) == customer_id,
                                    col(ServiceTicket.closed_at).is_not(None))
    ).all():
        out.append({"kind": "MAINTENANCE", "reference_id": t.id, "occurred_at": t.closed_at})
    for pull in session.exec(
        select(ProjectPull).where(col(ProjectPull.customer_id) == customer_id)
    ).all():
        out.append({"kind": "PROJECT_PULL", "reference_id": pull.id,
                    "occurred_at": pull.created_at})
    out.sort(key=lambda r: r["occurred_at"], reverse=True)
    return out
```

(`_q` already exists near `channel_margin_report`. If `HTTPException` isn't imported in crud.py, it is — it's used throughout.)

- [ ] **Step 5: Run — expect PASS.** `cd backend && uv run pytest tests/api/routes/test_customer_dashboard.py -v` → PASS; `uv run ruff check . && uv run mypy app` → clean.

- [ ] **Step 6: Commit.**

```bash
git add backend/app/models.py backend/app/crud.py backend/tests/api/routes/test_customer_dashboard.py
git commit -m "feat(dashboards): customer dashboard schemas + lifetime aggregation crud (Task 4.2, FR-020)"
```

---

### Task 5: Customer dashboard route with role dispatch + raw-HTTP redaction tests

**Files:**
- Modify: `backend/app/api/routes/customers.py`
- Modify: `backend/tests/api/routes/test_customer_dashboard.py`

- [ ] **Step 1: Write the failing redaction tests** (raw HTTP — assert keys absent, not DOM):

```python
from app.core.config import settings


def test_customer_dashboard_staff_has_no_financial_keys(
    client, staff_token_headers, db
) -> None:
    customer_id, _, _ = _seed_customer_with_one_sale(db)
    r = client.get(
        f"{settings.API_V1_STR}/customers/{customer_id}/dashboard",
        headers=staff_token_headers,
    )
    assert r.status_code == 200
    body = r.json()
    blob = str(body).lower()
    for forbidden in ("revenue", "cogs", "margin", "budget", "consumed_cost"):
        assert forbidden not in blob, f"staff dashboard leaked {forbidden}"
    assert "transactions" in body and "active_projects" in body


def test_customer_dashboard_admin_has_financial_keys(
    client, superuser_token_headers, db
) -> None:
    customer_id, expected_rev, expected_cogs = _seed_customer_with_one_sale(db)
    r = client.get(
        f"{settings.API_V1_STR}/customers/{customer_id}/dashboard",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["lifetime_sale_revenue_thb"] == f"{expected_rev:.2f}"
    assert "lifetime_sale_cogs_thb" in body


def test_customer_dashboard_404(client, superuser_token_headers) -> None:
    import uuid
    r = client.get(
        f"{settings.API_V1_STR}/customers/{uuid.uuid4()}/dashboard",
        headers=superuser_token_headers,
    )
    assert r.status_code == 404
```

- [ ] **Step 2: Run — expect FAIL.** `cd backend && uv run pytest tests/api/routes/test_customer_dashboard.py -k dashboard -v` → FAIL (route missing).

- [ ] **Step 3: Add the route** to `customers.py`. Import the new symbols and `CurrentUser`, `UserRole`:

```python
from app.api.deps import CurrentUser
from app.models import (
    CustomerDashboardAdminPublic,
    CustomerDashboardStaffPublic,
    UserRole,
)


@router.get(
    "/{customer_id}/dashboard",
    response_model=CustomerDashboardAdminPublic | CustomerDashboardStaffPublic,
)
def get_customer_dashboard(
    customer_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> CustomerDashboardAdminPublic | CustomerDashboardStaffPublic:
    data = crud.get_customer_dashboard(session=session, customer_id=customer_id)
    if current_user.role == UserRole.BKK_ADMIN:
        return CustomerDashboardAdminPublic.model_validate(data)
    return CustomerDashboardStaffPublic.model_validate(data)
```

> Note: the bootstrap superuser has `role=BKK_ADMIN`, so `superuser_token_headers` exercises the admin branch. `staff_token_headers` exercises the staff branch.

- [ ] **Step 4: Run — expect PASS.** `cd backend && uv run pytest tests/api/routes/test_customer_dashboard.py -v` → PASS; `uv run ruff check . && uv run mypy app` → clean.

- [ ] **Step 5: Commit.**

```bash
git add backend/app/api/routes/customers.py backend/tests/api/routes/test_customer_dashboard.py
git commit -m "feat(dashboards): role-tiered customer dashboard route (Task 4.2, FR-020/S7)"
```

---

### Task 6: Project dashboard (schemas + crud + route + redaction tests)

Mirror the customer dashboard for projects: admin sees `budget_thb` + `consumed_cost_thb`; staff sees neither.

**Files:**
- Modify: `backend/app/models.py` (schemas)
- Modify: `backend/app/crud.py` (`get_project_dashboard()`)
- Modify: `backend/app/api/routes/projects.py` (route)
- Create: `backend/tests/api/routes/test_project_dashboard.py`

- [ ] **Step 1: Write the failing redaction + aggregation tests.**

```python
import uuid
from app.core.config import settings


def test_project_dashboard_staff_redacts_budget_and_cost(
    client, staff_token_headers, db
) -> None:
    project_id = _seed_project_with_one_pull(db)  # local helper
    r = client.get(
        f"{settings.API_V1_STR}/projects/{project_id}/dashboard",
        headers=staff_token_headers,
    )
    assert r.status_code == 200
    blob = str(r.json()).lower()
    for forbidden in ("budget", "consumed_cost", "cogs"):
        assert forbidden not in blob


def test_project_dashboard_admin_shows_budget_and_consumed_cost(
    client, superuser_token_headers, db
) -> None:
    project_id = _seed_project_with_one_pull(db)
    r = client.get(
        f"{settings.API_V1_STR}/projects/{project_id}/dashboard",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert "budget_thb" in body and "consumed_cost_thb" in body


def test_project_dashboard_404(client, superuser_token_headers) -> None:
    r = client.get(
        f"{settings.API_V1_STR}/projects/{uuid.uuid4()}/dashboard",
        headers=superuser_token_headers,
    )
    assert r.status_code == 404
```

- [ ] **Step 2: Run — expect FAIL.** `cd backend && uv run pytest tests/api/routes/test_project_dashboard.py -v` → FAIL.

- [ ] **Step 3: Add the schemas** in `models.py`:

```python
class ProjectDashboardStaffPublic(SQLModel):
    project: ProjectPublic
    pulls: list[TransactionSummaryPublic]   # reuse: kind="PROJECT_PULL"
    # No budget / consumed_cost — staff redaction.


class ProjectDashboardAdminPublic(ProjectDashboardStaffPublic):
    budget_thb: Decimal | None
    consumed_cost_thb: Decimal
```

- [ ] **Step 4: Implement `get_project_dashboard()`** in `crud.py` (reuses `_project_consumed_cost` from Task 4):

```python
def get_project_dashboard(*, session: Session, project_id: uuid.UUID) -> dict:
    """Project detail with budget + consumed cost (FR-020). Returns admin superset;
    the route picks the role schema so staff never receive budget/cost keys."""
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    pulls = session.exec(
        select(ProjectPull).where(col(ProjectPull.project_id) == project_id)
    ).all()
    pull_rows = [
        {"kind": "PROJECT_PULL", "reference_id": p.id, "occurred_at": p.created_at}
        for p in sorted(pulls, key=lambda p: p.created_at, reverse=True)
    ]
    return {
        "project": project,
        "pulls": pull_rows,
        "budget_thb": project.budget_thb,
        "consumed_cost_thb": _project_consumed_cost(session=session, project_id=project_id),
    }
```

- [ ] **Step 5: Add the route** to `projects.py` (it currently has a router-level `get_admin` dependency — the dashboard must be reachable by staff, so set the dependency **on this route** explicitly and dispatch by role). Check the top of `projects.py`: if `router = APIRouter(..., dependencies=[Depends(get_admin)])`, the new route would inherit admin-only and staff would get 403. Fix by removing the router-level dependency and instead adding `dependencies=[Depends(get_admin)]` to each existing write route (`create_project`, `update_project`, `read_projects` per spec §8 — projects CRUD is admin-only), while the dashboard route uses `CurrentUser` + role dispatch:

```python
from app.api.deps import CurrentUser, SessionDep, get_admin
from app.models import (
    ProjectDashboardAdminPublic,
    ProjectDashboardStaffPublic,
    UserRole,
)


@router.get(
    "/{project_id}/dashboard",
    response_model=ProjectDashboardAdminPublic | ProjectDashboardStaffPublic,
)
def get_project_dashboard(
    project_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> ProjectDashboardAdminPublic | ProjectDashboardStaffPublic:
    data = crud.get_project_dashboard(session=session, project_id=project_id)
    if current_user.role == UserRole.BKK_ADMIN:
        return ProjectDashboardAdminPublic.model_validate(data)
    return ProjectDashboardStaffPublic.model_validate(data)
```

After moving the guard, re-run the existing `tests/api/routes/test_master_data.py` project tests to confirm the admin-only writes still 403 for staff.

- [ ] **Step 6: Run — expect PASS.** `cd backend && uv run pytest tests/api/routes/test_project_dashboard.py tests/api/routes/test_master_data.py -v` → PASS; `uv run ruff check . && uv run mypy app` → clean.

- [ ] **Step 7: Commit.**

```bash
git add backend/app/models.py backend/app/crud.py backend/app/api/routes/projects.py backend/tests/api/routes/test_project_dashboard.py
git commit -m "feat(dashboards): role-tiered project dashboard (Task 4.2, FR-020/S7)"
```

---

### Task 7: SDK regen + full suite + high-risk review gate

**Files:** none new — verification + review.

- [ ] **Step 1: Regenerate the frontend SDK** so the new dashboard endpoints + schemas are available and the removed signup operation is gone:

```bash
cd frontend && bun run generate-client
```

Confirm the generated `types.gen.ts` contains `StockOnHandResponse`, `CustomerDashboardAdminPublic`/`…StaffPublic`, `ProjectDashboard…Public`, and no longer references `registerUser`.

- [ ] **Step 2: Full backend suite + lint/type.** `cd backend && uv run pytest -q` → all green (target ≥ 80% coverage on `crud.py` + routes per Definition of Done). `uv run ruff check . && uv run mypy app` → clean.

- [ ] **Step 3: High-risk review (CLAUDE.md §5).** This PR touches role-tiering on financial data — run all three:
  - `superpowers:requesting-code-review` (orchestrator)
  - `ecc:database-reviewer` agent — focus: the aggregation queries (correlated subqueries, join correctness, no row-multiplication, index usage) and the M022 migration.
  - `ecc:security-reviewer` agent — focus: confirm **no** cost/margin/budget keys can reach a `YGN_STAFF` caller on any of the three dashboards (re-derive from the response schemas, not the tests), and that `/users/signup` is gone.
  Address any findings, re-run the suite, commit fixes.

- [ ] **Step 4: Open the PR** (one feature branch → `master`), per `create-pr`. Title: `feat(part4): stock-on-hand + role-tiered customer/project dashboards (FR-012, FR-020) + signup/drift fixes`. Body summarizes: security fix (signup), drift fix (M022 + model FKs), 4.1, 4.2, and the review sign-off.

- [ ] **Step 5: Commit any SDK changes.**

```bash
git add frontend/src/client
git commit -m "chore(sdk): regenerate client for Part 4 dashboards"
```

---

## Out of scope (still deferred — do NOT build here)
- **FR-015 SKU-search `cost_line` history** + **search/low-stock list exports** role-tiering (parked in `memory/deferred-security-hardening.md`).
- **Part 4.3** sync-review queue (M020) and **Part 4.4** AI integration — AI is deferred/locked per the current round's decision.

## Definition of Done (this round)
- `POST /users/signup` returns 404; no frontend signup surface; SDK regenerated.
- `alembic revision --autogenerate` produces an **empty** diff (drift dead).
- `GET /dashboards/stock-on-hand` returns correct QUANTITY sums + SERIALIZED counts, filterable, single-pass (perf test green).
- `GET /customers/{id}/dashboard` and `GET /projects/{id}/dashboard` dispatch by role; staff JSON has **no** revenue/cogs/margin/budget/consumed_cost keys (raw-HTTP tests green).
- Full suite green; `ruff` + `mypy` clean; database + security review signed off.
```

