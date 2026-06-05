# CastraNova-POS Part 4.3 — Sync-Review Queue (M020, FR / 95% smooth-sync) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. Each task is TDD: write the failing test, watch it fail, write minimal code, watch it pass, commit.

**Goal:** Build the backend `sync_review_item` queue (table #24 / M020) that captures offline mutations which replayed `STALE` (>7-day queue cap) or lost a write-`CONFLICT` (409 on replay), and lets a `BKK_ADMIN` triage them. This backs the **95% smooth-sync goal** (`1 − pending_or_intervened / total_sync_events`).

**Architecture (decided with the user, 2026-06-06):**
- **Thin ingest, no hot-path changes.** The future PWA detects STALE (dehydrated mutation older than 7 days by `submittedAt`) and CONFLICT (caught 409 on replay) client-side and `POST`s the item to `POST /sync-review`. The server **does not** touch the FIFO/sale 409-raising paths (`create_sale`, `consume_quantity_fifo`) — auto-capture is deferred to Part 5 when the frontend exists. So this slice is **not** a FIFO/ledger change.
- **Status-only triage.** `POST /sync-review/{id}/resolve` marks an item `RESOLVED` or `DISCARDED` (admin picks, optional note); it records `resolved_by_user_id` + `resolved_at` and **does not re-execute** the held mutation. The queue is a record + measurement + triage tool; manual re-entry (if needed) is a frontend concern.
- **Role-tiering:** ingest is open to any authenticated user (staff devices go offline); **list + resolve are admin-only** (`get_admin`). Payloads may embed prices (e.g. a sale payload) → staff must never read another caller's payload, so there is **no** staff-reachable read route (no `GET /sync-review/{id}`).
- **Idempotent ingest:** `idempotency_key` carries the original mutation's key. Ingest is made replay-safe with a `UNIQUE (idempotency_key)` constraint + the house `get_or_replay` IntegrityError pattern (re-`POST` of the same item returns the existing row, 200). **Deliberate strengthening** of the spec's "index on idempotency_key" (§4.2 indexes table) — rationale: idempotent, race-safe ingest matching every other offline-replayed write in the repo. Flag this for the database reviewer.

**Tech Stack:** FastAPI, SQLModel/SQLAlchemy, Postgres (JSONB), Alembic, pytest.

**Reference:**
- System design spec: `docs/superpowers/specs/2026-05-23-castranova-pos-system-design.md` — table #24 (line 171), indexes (line 190), §6.6 idempotency (line 461), §6.7 offline/STALE/CONFLICT (line 474), §8 routes (line 564), conflict table (line 304).
- Master roadmap: `docs/plans/2026-06-04-castranova-pos-implementation.md` Part 4.3 (line 669).
- **Table-shape template:** `PricingOverrideRequest` (M013) `models.py:790–835` and `StockAdjustment` (M014) `models.py:867–964`.
- **Route template:** `app/api/routes/pricing_overrides.py` (staff POST + admin list + admin action) — copy its dependency patterns exactly.
- **Migration template:** `app/alembic/versions/c9a23e6de5d4_m013_pricing_override_request.py` (enum create + `DROP TYPE IF EXISTS` in `downgrade`, compound index, FK index).
- **JSONB pattern:** `NotificationLog.payload` `models.py:1313` → `Field(sa_column=Column(JSONB, nullable=False))`.
- **`created_at` triple:** `get_datetime_utc` default_factory + `DateTime(timezone=True)` + `server_default=func.now()` (StockAdjustment `models.py:905–909`).

**Conventions (match the repo):**
- Models in `app/models.py`: enums in the `enum.Enum` block (≈ lines 29–110); table + `*Create`/`*Public` split together; UUID PK.
- All DB access in `app/crud.py`; functions keyword-only: `def fn(*, session: Session, ...)`. Routes never call `session.exec` directly.
- Deps from `app.api.deps`: `SessionDep`, `CurrentUser`, `AdminUser`, `get_admin`.
- Current migration head: **`b043d4fbe95f`** (M023). Autogenerate will chain `down_revision` to it.
- Tests under `backend/tests/` mirroring `app/`. Fixtures from `conftest.py`: `db`, `client`, `superuser_token_headers` (role=BKK_ADMIN → admin branch), `staff_token_headers` (YGN_STAFF), `normal_user_token_headers`.
- Run one test: `cd backend && uv run pytest <path>::<test> -v`. Full suite: `cd backend && uv run pytest -q`. Lint/type: `cd backend && uv run ruff check . && uv run mypy app`.
- **Review gate:** this is **role-tiering over potentially-financial payloads** → per CLAUDE.md §5 the Review stage runs `superpowers:requesting-code-review` **plus** `ecc:database-reviewer` + `ecc:security-reviewer` before the PR (Task 5).
- **Commit cadence:** one commit per task. Branch: `dev` (current).

---

## File Structure

| File | Created/Modified | Responsibility |
|---|---|---|
| `backend/app/models.py` | Modify | `SyncReviewReason`/`SyncReviewState` enums; `SyncReviewItem` table; `SyncReviewItemCreate`, `SyncReviewItemPublic`, `SyncReviewResolve` schemas |
| `backend/app/alembic/versions/<hash>_m020_sync_review_item.py` | Create | M020 table + enums + indexes + unique constraint + FK |
| `backend/app/crud.py` | Modify | `create_sync_review_item()`, `list_sync_review_items()`, `resolve_sync_review_item()` |
| `backend/app/api/routes/sync_review.py` | Create | `POST /sync-review` (auth), `GET /sync-review?state=` (admin), `POST /sync-review/{id}/resolve` (admin) |
| `backend/app/api/main.py` | Modify | register `sync_review.router` |
| `backend/tests/api/routes/test_sync_review.py` | Create | ingest, idempotency, role guards, list filter, resolve, 404/409 |
| `frontend/src/client/*` | Regenerate | `bun run generate-client` picks up the new endpoints |

---

### Task 1: M020 model — enums, table, schemas

**Files:**
- Modify: `backend/app/models.py`

- [ ] **Step 1: Add the enums** in the `enum.Enum` block (after `ProjectStatus`, ≈ line 110). `str, enum.Enum` so values serialize as plain strings:

```python
class SyncReviewReason(str, enum.Enum):
    STALE = "STALE"        # offline mutation older than the 7-day queue cap
    CONFLICT = "CONFLICT"  # lost a write-conflict (409) on replay


class SyncReviewState(str, enum.Enum):
    PENDING = "PENDING"
    RESOLVED = "RESOLVED"
    DISCARDED = "DISCARDED"
```

- [ ] **Step 2: Add the table** near the other M01x tables (e.g. after `StockAdjustment`). Mirror the `StockAdjustment` `created_at` triple and `NotificationLog` JSONB pattern. `idempotency_key` is `UNIQUE` (idempotent ingest); FK `resolved_by_user_id → user.id`.

```python
class SyncReviewItem(SQLModel, table=True):
    __tablename__ = "syncreviewitem"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_syncreviewitem_idempotency_key"),
        Index("ix_syncreviewitem_state_created", "state", "created_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    idempotency_key: uuid.UUID = Field(index=False)  # uniqueness via __table_args__
    mutation_kind: str = Field(min_length=1, max_length=64)  # e.g. "sale", "ticket_close"
    payload: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    reason: SyncReviewReason = Field(index=False)
    state: SyncReviewState = Field(default=SyncReviewState.PENDING)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.now()},
    )
    resolved_by_user_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id"
    )
    resolved_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )
    resolution_note: str | None = Field(default=None, max_length=500)
```

> Confirm these are already imported at the top of `models.py` (the explorer verified `Column`, `JSONB`, `DateTime`, `func`, `Index`, `UniqueConstraint`, `Any` are all in use elsewhere in the file). If `mypy` flags a missing name, add it to the existing import line — do not reorder imports.

- [ ] **Step 3: Add the schemas** right after the table:

```python
class SyncReviewItemCreate(SQLModel):
    idempotency_key: uuid.UUID
    mutation_kind: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any]
    reason: SyncReviewReason


class SyncReviewItemPublic(SQLModel):
    id: uuid.UUID
    idempotency_key: uuid.UUID
    mutation_kind: str
    payload: dict[str, Any]
    reason: SyncReviewReason
    state: SyncReviewState
    created_at: datetime
    resolved_by_user_id: uuid.UUID | None
    resolved_at: datetime | None
    resolution_note: str | None


class SyncReviewResolve(SQLModel):
    state: SyncReviewState  # must be RESOLVED or DISCARDED (validated in crud)
    note: str | None = Field(default=None, max_length=500)
```

- [ ] **Step 4: Type-check.** `cd backend && uv run ruff check . && uv run mypy app` → clean. (No test yet — table lands with the migration in Task 2.)

- [ ] **Step 5: Commit.**

```bash
git add backend/app/models.py
git commit -m "feat(sync-review): SyncReviewItem model + enums + schemas (M020, Part 4.3)"
```

---

### Task 2: M020 migration (autogenerate + verify drift-clean)

**Files:**
- Create: `backend/app/alembic/versions/<hash>_m020_sync_review_item.py`

- [ ] **Step 1: Autogenerate.** With Task 1 committed and DB at head:

```bash
cd backend && uv run alembic upgrade head
uv run alembic revision --autogenerate -m "M020 sync_review_item"
```

- [ ] **Step 2: Review the generated file.** It must `op.create_table("syncreviewitem", ...)` with: UUID PK, `idempotency_key` (UNIQUE via `uq_syncreviewitem_idempotency_key`), `mutation_kind`, `payload` as `postgresql.JSONB(astext_type=sa.Text())` NOT NULL, the two native enums (`syncreviewreason`, `syncreviewstate`), `state` defaulting PENDING, `created_at` with `server_default`, the `resolved_by_user_id` FK to `user`, and the compound `ix_syncreviewitem_state_created` index. **Confirm `downgrade()` drops both enum types** — match M013:

```python
    op.execute("DROP TYPE IF EXISTS syncreviewreason")
    op.execute("DROP TYPE IF EXISTS syncreviewstate")
```

If autogenerate emits any *other* table's FK/index churn, the model drift regressed — stop and investigate before editing. Only `syncreviewitem` ops should appear.

- [ ] **Step 3: Apply + drift gate.** `uv run alembic upgrade head` → succeeds. Then prove no residual drift:

```bash
uv run alembic revision --autogenerate -m "drift probe DELETE ME"
```

Open it: `upgrade()`/`downgrade()` must be empty (`pass`). Then `rm app/alembic/versions/*drift_probe_delete_me*.py`.

- [ ] **Step 4: Suite still green.** `cd backend && uv run pytest -q` → all pass; `uv run ruff check . && uv run mypy app` → clean.

- [ ] **Step 5: Commit.**

```bash
git add backend/app/alembic/versions/*m020*sync_review_item*.py
git commit -m "feat(sync-review): M020 migration for sync_review_item (Part 4.3)"
```

---

### Task 3: crud — ingest (idempotent), list (filtered), resolve (status-only)

**Files:**
- Modify: `backend/app/crud.py`
- Create: `backend/tests/api/routes/test_sync_review.py` (crud-level tests first)

- [ ] **Step 1: Write the failing crud tests.** Create `test_sync_review.py`:

```python
import uuid
import pytest
from fastapi import HTTPException
from sqlmodel import Session

from app import crud
from app.models import (
    SyncReviewItemCreate,
    SyncReviewReason,
    SyncReviewState,
)


def _ingest(db: Session, *, reason=SyncReviewReason.STALE, key=None) -> "uuid.UUID":
    data = SyncReviewItemCreate(
        idempotency_key=key or uuid.uuid4(),
        mutation_kind="sale",
        payload={"customer_id": str(uuid.uuid4()), "total_thb": "1200.00"},
        reason=reason,
    )
    return crud.create_sync_review_item(session=db, data=data).id


def test_ingest_creates_pending_item(db: Session) -> None:
    item_id = _ingest(db, reason=SyncReviewReason.CONFLICT)
    item = crud.get_sync_review_item(session=db, item_id=item_id)
    assert item is not None
    assert item.state == SyncReviewState.PENDING
    assert item.reason == SyncReviewReason.CONFLICT
    assert item.resolved_by_user_id is None


def test_ingest_is_idempotent_by_key(db: Session) -> None:
    key = uuid.uuid4()
    first = _ingest(db, key=key)
    second = _ingest(db, key=key)  # replay of the same offline item
    assert first == second  # same row, no duplicate


def test_resolve_marks_resolved_with_actor_and_note(db: Session) -> None:
    item_id = _ingest(db)
    admin_id = uuid.uuid4()
    item = crud.resolve_sync_review_item(
        session=db, item_id=item_id, admin_id=admin_id,
        new_state=SyncReviewState.RESOLVED, note="re-entered manually",
    )
    assert item.state == SyncReviewState.RESOLVED
    assert item.resolved_by_user_id == admin_id
    assert item.resolved_at is not None
    assert item.resolution_note == "re-entered manually"


def test_resolve_rejects_non_pending(db: Session) -> None:
    item_id = _ingest(db)
    admin_id = uuid.uuid4()
    crud.resolve_sync_review_item(
        session=db, item_id=item_id, admin_id=admin_id,
        new_state=SyncReviewState.DISCARDED, note=None,
    )
    with pytest.raises(HTTPException) as exc:  # second resolve → 409
        crud.resolve_sync_review_item(
            session=db, item_id=item_id, admin_id=admin_id,
            new_state=SyncReviewState.RESOLVED, note=None,
        )
    assert exc.value.status_code == 409


def test_resolve_rejects_pending_target_state(db: Session) -> None:
    item_id = _ingest(db)
    with pytest.raises(HTTPException) as exc:  # cannot "resolve" to PENDING
        crud.resolve_sync_review_item(
            session=db, item_id=item_id, admin_id=uuid.uuid4(),
            new_state=SyncReviewState.PENDING, note=None,
        )
    assert exc.value.status_code == 422


def test_list_filters_by_state(db: Session) -> None:
    pending_id = _ingest(db)
    discarded_id = _ingest(db)
    crud.resolve_sync_review_item(
        session=db, item_id=discarded_id, admin_id=uuid.uuid4(),
        new_state=SyncReviewState.DISCARDED, note=None,
    )
    pending = crud.list_sync_review_items(session=db, state=SyncReviewState.PENDING)
    ids = {i.id for i in pending}
    assert pending_id in ids and discarded_id not in ids
```

- [ ] **Step 2: Run — expect FAIL.** `cd backend && uv run pytest tests/api/routes/test_sync_review.py -v` → FAIL (crud fns missing).

- [ ] **Step 3: Implement the crud** in `crud.py` (new section near the other M01x crud; reuse the `get_or_replay`/IntegrityError idempotency pattern already in the file):

```python
def create_sync_review_item(
    *, session: Session, data: SyncReviewItemCreate
) -> SyncReviewItem:
    """Ingest a STALE/CONFLICT offline mutation into the admin review queue.
    Idempotent by idempotency_key: a re-POST of the same offline item returns
    the existing row (the UNIQUE constraint + IntegrityError rollback path)."""
    existing = session.exec(
        select(SyncReviewItem).where(
            col(SyncReviewItem.idempotency_key) == data.idempotency_key
        )
    ).first()
    if existing is not None:
        return existing
    item = SyncReviewItem(
        idempotency_key=data.idempotency_key,
        mutation_kind=data.mutation_kind,
        payload=data.payload,
        reason=data.reason,
    )
    session.add(item)
    try:
        session.commit()
    except IntegrityError:  # concurrent ingest won the UNIQUE race
        session.rollback()
        return session.exec(
            select(SyncReviewItem).where(
                col(SyncReviewItem.idempotency_key) == data.idempotency_key
            )
        ).one()
    session.refresh(item)
    return item


def get_sync_review_item(
    *, session: Session, item_id: uuid.UUID
) -> SyncReviewItem | None:
    return session.get(SyncReviewItem, item_id)


def list_sync_review_items(
    *, session: Session, state: SyncReviewState | None = None
) -> list[SyncReviewItem]:
    stmt = select(SyncReviewItem)
    if state is not None:
        stmt = stmt.where(col(SyncReviewItem.state) == state)
    stmt = stmt.order_by(col(SyncReviewItem.created_at))
    return list(session.exec(stmt).all())


def resolve_sync_review_item(
    *,
    session: Session,
    item_id: uuid.UUID,
    admin_id: uuid.UUID,
    new_state: SyncReviewState,
    note: str | None,
) -> SyncReviewItem:
    """Status-only triage: mark RESOLVED or DISCARDED. Does NOT re-run the held
    mutation. 422 if target is not a terminal state; 404 if missing; 409 if the
    item was already triaged (not PENDING)."""
    if new_state not in (SyncReviewState.RESOLVED, SyncReviewState.DISCARDED):
        raise HTTPException(
            status_code=422, detail="state must be RESOLVED or DISCARDED"
        )
    item = session.get(SyncReviewItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Sync-review item not found")
    if item.state != SyncReviewState.PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"Only PENDING items can be resolved (current: {item.state.value})",
        )
    item.state = new_state
    item.resolved_by_user_id = admin_id
    item.resolved_at = get_datetime_utc()
    item.resolution_note = note
    session.add(item)
    session.commit()
    session.refresh(item)
    return item
```

> Add the new names to the existing `from app.models import (...)` block in `crud.py` (`SyncReviewItem`, `SyncReviewItemCreate`, `SyncReviewState`). `IntegrityError`, `select`, `col`, `get_datetime_utc`, `HTTPException` are already imported.

- [ ] **Step 4: Run — expect PASS.** `cd backend && uv run pytest tests/api/routes/test_sync_review.py -v` → PASS. `uv run ruff check . && uv run mypy app` → clean.

- [ ] **Step 5: Commit.**

```bash
git add backend/app/crud.py backend/tests/api/routes/test_sync_review.py
git commit -m "feat(sync-review): ingest/list/resolve crud, idempotent + status-only (Part 4.3)"
```

---

### Task 4: routes — ingest (auth), list (admin), resolve (admin) + role-guard tests

**Files:**
- Create: `backend/app/api/routes/sync_review.py`
- Modify: `backend/app/api/main.py`
- Modify: `backend/tests/api/routes/test_sync_review.py`

- [ ] **Step 1: Write the failing route tests** (append to `test_sync_review.py`; raw HTTP — assert status + key presence/role gates):

```python
from app.core.config import settings


def _payload() -> dict:
    return {
        "idempotency_key": str(uuid.uuid4()),
        "mutation_kind": "sale",
        "payload": {"total_thb": "1200.00"},
        "reason": "STALE",
    }


def test_ingest_requires_auth(client) -> None:
    r = client.post(f"{settings.API_V1_STR}/sync-review", json=_payload())
    assert r.status_code == 401


def test_staff_can_ingest(client, staff_token_headers) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/sync-review", json=_payload(),
        headers=staff_token_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "PENDING" and body["reason"] == "STALE"


def test_ingest_is_idempotent_over_http(client, staff_token_headers) -> None:
    body = _payload()
    r1 = client.post(f"{settings.API_V1_STR}/sync-review", json=body, headers=staff_token_headers)
    r2 = client.post(f"{settings.API_V1_STR}/sync-review", json=body, headers=staff_token_headers)
    assert r1.json()["id"] == r2.json()["id"]


def test_list_is_admin_only(client, staff_token_headers) -> None:
    r = client.get(
        f"{settings.API_V1_STR}/sync-review?state=PENDING",
        headers=staff_token_headers,
    )
    assert r.status_code == 403


def test_admin_lists_pending(client, superuser_token_headers, staff_token_headers) -> None:
    client.post(f"{settings.API_V1_STR}/sync-review", json=_payload(), headers=staff_token_headers)
    r = client.get(
        f"{settings.API_V1_STR}/sync-review?state=PENDING",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    assert any(i["state"] == "PENDING" for i in r.json())


def test_resolve_is_admin_only(client, staff_token_headers, superuser_token_headers) -> None:
    created = client.post(
        f"{settings.API_V1_STR}/sync-review", json=_payload(), headers=staff_token_headers
    ).json()
    r = client.post(
        f"{settings.API_V1_STR}/sync-review/{created['id']}/resolve",
        json={"state": "RESOLVED", "note": "done"},
        headers=staff_token_headers,
    )
    assert r.status_code == 403


def test_admin_resolves_item(client, staff_token_headers, superuser_token_headers) -> None:
    created = client.post(
        f"{settings.API_V1_STR}/sync-review", json=_payload(), headers=staff_token_headers
    ).json()
    r = client.post(
        f"{settings.API_V1_STR}/sync-review/{created['id']}/resolve",
        json={"state": "DISCARDED", "note": "duplicate"},
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "DISCARDED"
    assert body["resolved_by_user_id"] is not None
    assert body["resolved_at"] is not None


def test_resolve_404(client, superuser_token_headers) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/sync-review/{uuid.uuid4()}/resolve",
        json={"state": "RESOLVED", "note": None},
        headers=superuser_token_headers,
    )
    assert r.status_code == 404
```

- [ ] **Step 2: Run — expect FAIL.** `cd backend && uv run pytest tests/api/routes/test_sync_review.py -k "http or admin or staff or auth or 404 or list or resolve" -v` → FAIL (route missing / 404 on the path).

- [ ] **Step 3: Create the route** `backend/app/api/routes/sync_review.py`:

```python
import uuid

from fastapi import APIRouter, Depends

from app import crud
from app.api.deps import AdminUser, CurrentUser, SessionDep, get_admin
from app.models import (
    SyncReviewItemCreate,
    SyncReviewItemPublic,
    SyncReviewResolve,
    SyncReviewState,
)

router = APIRouter(prefix="/sync-review", tags=["sync-review"])


@router.post("", response_model=SyncReviewItemPublic)
def ingest_sync_review_item(
    data: SyncReviewItemCreate,
    session: SessionDep,
    current_user: CurrentUser,  # any authenticated device may report a stale/conflict
) -> SyncReviewItemPublic:
    item = crud.create_sync_review_item(session=session, data=data)
    return SyncReviewItemPublic.model_validate(item, from_attributes=True)


@router.get(
    "",
    response_model=list[SyncReviewItemPublic],
    dependencies=[Depends(get_admin)],
)
def list_sync_review_items(
    session: SessionDep,
    state: SyncReviewState | None = None,
) -> list[SyncReviewItemPublic]:
    items = crud.list_sync_review_items(session=session, state=state)
    return [
        SyncReviewItemPublic.model_validate(i, from_attributes=True) for i in items
    ]


@router.post("/{item_id}/resolve", response_model=SyncReviewItemPublic)
def resolve_sync_review_item(
    item_id: uuid.UUID,
    body: SyncReviewResolve,
    session: SessionDep,
    admin: AdminUser,
) -> SyncReviewItemPublic:
    item = crud.resolve_sync_review_item(
        session=session, item_id=item_id, admin_id=admin.id,
        new_state=body.state, note=body.note,
    )
    return SyncReviewItemPublic.model_validate(item, from_attributes=True)
```

> Note: `@router.post("")` + `prefix="/sync-review"` resolves to `POST /api/v1/sync-review`. If the repo's other routers use a trailing-slash convention, match it (check `pricing_overrides.py`); keep the test URLs in sync.

Register in `backend/app/api/main.py`: add `sync_review` to the `from app.api.routes import (...)` block and `api_router.include_router(sync_review.router)`.

- [ ] **Step 4: Run — expect PASS.** `cd backend && uv run pytest tests/api/routes/test_sync_review.py -v` → all PASS. `uv run ruff check . && uv run mypy app` → clean.

- [ ] **Step 5: Commit.**

```bash
git add backend/app/api/routes/sync_review.py backend/app/api/main.py backend/tests/api/routes/test_sync_review.py
git commit -m "feat(sync-review): role-tiered routes (auth ingest, admin list/resolve) (Part 4.3)"
```

---

### Task 5: SDK regen + full suite + high-risk review gate

**Files:** none new — verification + review.

- [ ] **Step 1: Regenerate the SDK** so the new endpoints/schemas land in the client:

```bash
cd frontend && bun run generate-client
```

Confirm `types.gen.ts` contains `SyncReviewItemPublic`, `SyncReviewItemCreate`, `SyncReviewResolve`, and the `sync-review` operations.

- [ ] **Step 2: Full backend suite + lint/type.** `cd backend && uv run pytest -q` → all green; `uv run ruff check . && uv run mypy app` → clean. Final drift gate: `uv run alembic revision --autogenerate -m "probe DELETE ME"` → empty, then `rm` it.

- [ ] **Step 3: Review (CLAUDE.md §5 — role-tiering over financial payloads).**
  - `superpowers:requesting-code-review` (orchestrator).
  - `ecc:database-reviewer` — focus: the M020 migration (enum DROP in downgrade, UNIQUE + compound index, FK), the **deliberate UNIQUE-on-idempotency_key deviation** from the spec's "index", and that the idempotent-ingest IntegrityError path is race-correct.
  - `ecc:security-reviewer` — focus: confirm **no staff-reachable route returns another caller's `payload`** (list + resolve are admin-only; ingest only echoes the caller's own submission), that resolve cannot mutate ledgers/stock (status-only), and that the 95%-metric queue can't be used to leak COGS to `YGN_STAFF`.
  Address findings, re-run suite, commit fixes.

- [ ] **Step 4: Commit SDK + open PR.**

```bash
git add frontend/src/client
git commit -m "chore(sdk): regenerate client for sync-review queue (Part 4.3)"
```

Then open one PR `dev → master` per `create-pr`. Title: `feat(part4.3): sync-review queue (M020) for offline STALE/CONFLICT triage`. Body: thin-ingest + status-only design decisions, role-tiering, the UNIQUE-idempotency rationale, and review sign-off.

---

## Out of scope (deferred — do NOT build here)
- **Server-side CONFLICT auto-capture** in `create_sale`/`consume_quantity_fifo` — deferred to Part 5 (needs the PWA + would re-trigger the FIFO concurrency review gate).
- **Resolve re-applies the payload** (server-side mutation replay) — explicitly rejected; manual re-entry is a frontend concern.
- **Frontend sync-review admin screen + the STALE/CONFLICT detection in the offline layer** — Part 5.3 (`bun run generate-client` + role-shell screens).

## Definition of Done (this round)
- `POST /sync-review` ingests STALE/CONFLICT items for any authenticated user; idempotent by `idempotency_key` (re-POST → same row).
- `GET /sync-review?state=PENDING` and `POST /sync-review/{id}/resolve` are **admin-only** (staff → 403); resolve is status-only (RESOLVED/DISCARDED + note, records actor/time), 404 on missing, 409 on already-triaged, 422 on a non-terminal target state.
- M020 applied; `alembic revision --autogenerate` produces an **empty** diff.
- Full suite green; `ruff` + `mypy` clean; SDK regenerated; database + security review signed off.
