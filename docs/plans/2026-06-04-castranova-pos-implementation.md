# CastraNova-POS Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `@superpowers:executing-plans` to implement this plan task-by-task. Each task is TDD: write the failing test, watch it fail, write minimal code, watch it pass, commit. Also lean on `@superpowers:test-driven-development` and `@superpowers:systematic-debugging` when a test won't pass.

**Goal:** Build the CastraNova-POS inventory & channel-margin backend (FastAPI + SQLModel + Postgres) and offline-capable React PWA frontend, implementing PRD v3.0 / v2.6 (FR-001 → FR-020) per the system design spec.

**Architecture:** Append-only movement ledgers (`unit_movement`, `part_movement`, `cost_line`) are the source of truth; cached state columns (`unit.current_state`, `part_batch.remaining_qty`) are updated in the same transaction. SERIALIZED stock is one row per piece with a server-enforced state machine; QUANTITY stock is FIFO purchase batches consumed oldest-first under row locks, splitting cost across `cost_line` rows. Every offline-originating mutation is idempotent (client UUID + `UNIQUE` constraint). Two roles (`BKK_ADMIN`, `YGN_STAFF`) enforced server-side; financial fields redacted for staff via separate Pydantic schemas.

**Tech Stack:** FastAPI ≥0.114, SQLModel ≥0.0.21, Postgres (psycopg3), Alembic, PyJWT, pwdlib(argon2); React + Vite + TanStack Router/Query + shadcn/ui; `reportlab` (PDF), `openpyxl` (Excel), `tenacity` (notify retry), `slowapi` (rate limit), `vite-plugin-pwa` + `idb-keyval` (offline), `html5-qrcode` (phone-camera barcode fallback). Reference: system design spec `docs/superpowers/specs/2026-05-23-castranova-pos-system-design.md`.

---

## Scope of this document

This plan is **fully bite-sized (TDD, complete code)** for the parts where a zero-context engineer needs the most help and the risk is highest:

- **Part 0 — Foundation** (deps, enums, role guards, test fixtures, migration workflow)
- **Part 1 — Group 1** (catalog + master data + serialized receive + unit state machine + idempotency + serialized sale + offline shell)
- **Part 2 — FIFO core** (race-safe `batch_no`, quantity receive, `consume_quantity_fifo` + `cost_line`, sale PART lines, concurrency test)

The remaining work is a **structured task roadmap** (Part 3–5): each task lists files, what to build, and the test focus, and is executed *by analogy to the detailed patterns above*. Expand any roadmap task into bite-sized steps on demand — they reuse the same crud/route/test patterns.

**Reference learnings folded in:**
- *InvenTree (domain reference, Django — not our stack):* validates the append-only tracking-ledger-with-deltas pattern and the serial-vs-quantity dichotomy. We deliberately go **further**: a dedicated `part_batch` + `cost_line` give true FIFO cost layering (InvenTree treats `batch` as freeform text), and we **enforce** a unit state machine (InvenTree statuses are non-enforcing flags). Allocations-as-reservation-rows informed `project_pull`.
- *Context7-verified APIs:* SQLModel `Relationship(back_populates=…)` + `select(...).with_for_update()` for FIFO row locks; Alembic `revision --autogenerate` → `upgrade head`; TanStack Query `PersistQueryClientProvider` + `setMutationDefaults` + `resumePausedMutations`; `vite-plugin-pwa` `registerType:'autoUpdate'`.

**Conventions (match the template — verified against the repo):**
- Models in `backend/app/models.py`: `XBase` / `XCreate` / `XUpdate` / `XPublic` split; UUID PKs via `Field(default_factory=uuid.uuid4, primary_key=True)`; timestamps via `get_datetime_utc` + `sa_type=DateTime(timezone=True)`; money as `Decimal` with `sa_column=Column(Numeric(12, 2))`.
- All DB access in `backend/app/crud.py`; functions are keyword-only: `def fn(*, session: Session, ...)`.
- Routes: one file per resource in `backend/app/api/routes/`, `APIRouter(prefix=…, tags=[…])`, registered in `backend/app/api/main.py`. Deps from `app.api.deps`: `SessionDep`, `CurrentUser`.
- Tests under `backend/tests/` mirroring `app/` (`backend/tests/crud/…`, `backend/tests/api/routes/…`). Fixtures from `backend/tests/conftest.py`: `db` (Session), `client` (TestClient), `superuser_token_headers`, `normal_user_token_headers`.
- **Run tests:** `cd backend && uv run pytest <path>::<test> -v` (or `bash scripts/test.sh` for the full suite). **Migrations:** `cd backend && uv run alembic revision --autogenerate -m "…"` then `uv run alembic upgrade head`. The spec's **M-numbers are logical FK-order labels, not the Alembic chain order** — create each revision when its task runs; FK deps are satisfied by the build order. **Lint/type:** `uv run ruff check . && uv run mypy app`.
- **Commit cadence:** one commit per task (after its tests pass). Branch off `master` first: `git switch -c feat/castranova-pos`.

---

# Part 0 — Foundation

### Task 0.1: Add backend dependencies

**Files:**
- Modify: `backend/pyproject.toml` (dependencies array)

**Step 1: Add the new runtime deps.** Append to `[project].dependencies`:

```toml
    "reportlab<5.0.0,>=4.2.0",
    "openpyxl<4.0.0,>=3.1.0",
    "slowapi<1.0.0,>=0.1.9",
    "qrcode<8.0.0,>=7.4.0",          # Code128 via reportlab.graphics.barcode; qrcode optional for camera-pair QR
```

(`tenacity`, `alembic`, `sqlmodel`, `sentry-sdk`, `pytest` are already present.)

**Step 2: Sync and verify.**

Run: `cd backend && uv sync`
Expected: resolves and installs without conflict.

**Step 3: Commit.**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "build: add reportlab, openpyxl, slowapi deps for CastraNova-POS"
```

---

### Task 0.2: Define domain enums

**Files:**
- Modify: `backend/app/models.py` (top, after imports)
- Test: `backend/tests/test_enums.py`

**Step 1: Write the failing test.**

```python
# backend/tests/test_enums.py
from app.models import (
    UserRole, TrackingMode, Channel, UnitState, MovementType,
    ProjectPullState, LineState, OverrideState, AdjustmentTarget,
)

def test_user_roles():
    assert {r.value for r in UserRole} == {"BKK_ADMIN", "YGN_STAFF"}

def test_unit_states_terminal_set():
    assert UnitState.ADJUSTED_OUT.value == "ADJUSTED_OUT"
    assert {s.value for s in UnitState} >= {
        "RECEIVED", "IN_STOCK", "SOLD", "MAINTENANCE_OUT", "PROJECT_OUT", "ADJUSTED_OUT",
    }

def test_tracking_modes():
    assert {m.value for m in TrackingMode} == {"SERIALIZED", "QUANTITY"}
```

**Step 2: Run it to verify it fails.**

Run: `cd backend && uv run pytest tests/test_enums.py -v`
Expected: FAIL — `ImportError: cannot import name 'UserRole'`.

**Step 3: Write minimal implementation.** In `backend/app/models.py`, after the existing imports add:

```python
import enum


class UserRole(str, enum.Enum):
    BKK_ADMIN = "BKK_ADMIN"
    YGN_STAFF = "YGN_STAFF"


class TrackingMode(str, enum.Enum):
    SERIALIZED = "SERIALIZED"
    QUANTITY = "QUANTITY"


class Channel(str, enum.Enum):
    SALE = "SALE"
    MAINTENANCE = "MAINTENANCE"
    PROJECT = "PROJECT"


class UnitState(str, enum.Enum):
    RECEIVED = "RECEIVED"
    IN_STOCK = "IN_STOCK"
    SOLD = "SOLD"
    MAINTENANCE_OUT = "MAINTENANCE_OUT"
    PROJECT_OUT = "PROJECT_OUT"
    ADJUSTED_OUT = "ADJUSTED_OUT"


class MovementType(str, enum.Enum):
    RECEIVED = "RECEIVED"
    SOLD = "SOLD"
    MAINTENANCE_OUT = "MAINTENANCE_OUT"
    PROJECT_OUT = "PROJECT_OUT"
    ADJUSTED_OUT = "ADJUSTED_OUT"


class ProjectPullState(str, enum.Enum):
    PENDING = "PENDING"
    FULFILLED = "FULFILLED"
    SHORT = "SHORT"
    CANCELLED = "CANCELLED"


class LineState(str, enum.Enum):
    PENDING = "PENDING"
    FULFILLED = "FULFILLED"
    SHORT = "SHORT"
    CANCELLED = "CANCELLED"


class OverrideState(str, enum.Enum):
    AUTO_APPROVED = "AUTO_APPROVED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AdjustmentTarget(str, enum.Enum):
    UNIT = "UNIT"
    QUANTITY = "QUANTITY"
```

**Step 4: Run to verify pass.** `uv run pytest tests/test_enums.py -v` → PASS.

**Step 5: Commit.** `git add … && git commit -m "feat(models): add CastraNova domain enums"`

---

### Task 0.3: Add `role` to User + migration

**Files:**
- Modify: `backend/app/models.py` (`UserBase`)
- Create: `backend/app/alembic/versions/<hash>_m001_user_add_role.py` (autogenerated)
- Test: `backend/tests/crud/test_user_role.py`

**Step 1: Write the failing test.**

```python
# backend/tests/crud/test_user_role.py
from sqlmodel import Session
from app.models import UserRole, UserCreate
from app import crud

def test_new_user_defaults_to_admin_role(db: Session):
    user = crud.create_user(session=db, user_create=UserCreate(
        email="role-test@example.com", password="changethis123", role=UserRole.YGN_STAFF,
    ))
    assert user.role == UserRole.YGN_STAFF
```

**Step 2: Run to verify it fails.** `uv run pytest tests/crud/test_user_role.py -v` → FAIL (`role` not a field).

**Step 3: Implement.** In `UserBase` add:

```python
    role: UserRole = Field(default=UserRole.BKK_ADMIN)
```

Also add `role` to `UserCreate`/`UserUpdate` if not inherited (it is, via `UserBase`).

**Step 4: Generate + apply migration (M001).**

Run:
```bash
cd backend && uv run alembic revision --autogenerate -m "M001 user add role"
# review the generated file: it should add_column('user', 'role', ...) with a server_default
uv run alembic upgrade head
```
Edit the migration to set `server_default='BKK_ADMIN'` on upgrade so existing rows are valid, then drop the server_default in a follow-up `op.alter_column` (or leave it — acceptable for v1).

**Step 5: Run test → PASS. Commit** (`git add app/models.py app/alembic/versions/*role*.py && git commit -m "feat(models): add user role enum + M001 migration"`).

---

### Task 0.4: Role-guard dependencies

**Files:**
- Modify: `backend/app/api/deps.py`
- Test: `backend/tests/api/test_role_guards.py`

**Step 1: Write the failing test.**

```python
# backend/tests/api/test_role_guards.py
import pytest
from fastapi import HTTPException
from app.api.deps import get_admin
from app.models import User, UserRole

def _user(role): return User(email="x@e.com", hashed_password="x", role=role)

def test_get_admin_allows_admin():
    assert get_admin(_user(UserRole.BKK_ADMIN)).role == UserRole.BKK_ADMIN

def test_get_admin_blocks_staff():
    with pytest.raises(HTTPException) as e:
        get_admin(_user(UserRole.YGN_STAFF))
    assert e.value.status_code == 403
```

**Step 2: Run → FAIL** (`get_admin` undefined).

**Step 3: Implement** in `deps.py`:

```python
from app.models import User, UserRole

def get_admin(current_user: CurrentUser) -> User:
    if current_user.role != UserRole.BKK_ADMIN:
        raise HTTPException(status_code=403, detail="Admin only")
    return current_user

AdminUser = Annotated[User, Depends(get_admin)]
```

> **`is_superuser` is retained** (design decision): the bootstrap superuser keeps `is_superuser=True` **and** gets `role=BKK_ADMIN`. Template `/users` + `/items` guards stay on `is_superuser` (no rewrite); all new CastraNova routes authorize via `get_admin` (`role`). Do not remove `is_superuser`.

**Step 4: Run → PASS. Step 5: Commit.**

---

### Task 0.5: Add staff-token fixture to conftest

**Files:**
- Modify: `backend/tests/conftest.py`
- Modify: `backend/tests/utils/user.py` (or wherever `authentication_token_from_email` lives)

**Step 1:** Add a `staff_token_headers` fixture that creates/loads a `YGN_STAFF` user and returns auth headers (mirror the existing `normal_user_token_headers` fixture, but set `role=UserRole.YGN_STAFF`). This is needed by every staff/admin route test below.

**Step 2:** Smoke test: `uv run pytest tests/ -k token -q` collects without error.

**Step 3: Commit.** `git commit -m "test: add staff_token_headers fixture"`

---

### Task 0.6: Remove (or retire) the template `Item` entity

**Files (blast radius = 7, verified against the repo):** `backend/app/models.py`, `backend/app/crud.py`, `backend/app/api/routes/items.py`, `backend/app/api/main.py`, `backend/tests/conftest.py` (teardown references `Item`), `backend/tests/utils/item.py`, `backend/tests/api/routes/test_items.py`.

The template ships an `Item` model unused by this domain; the catalog migration (M005) replaces it. Pick one:

- **Remove (recommended):** delete the `Item*` models + `create_item` crud + `routes/items.py`, unregister its router in `api/main.py`, drop the `Item` cleanup in `conftest.py` teardown, and delete `tests/utils/item.py` + `tests/api/routes/test_items.py`. Generate a migration that drops the `item` table. Run the full suite → green.
- **Keep dormant:** leave it untouched (no migration). Acceptable, but it is dead code — note it per CLAUDE.md §3.

Do this **before** Task 1.3 (M005), since the autogenerate diff for `product` will otherwise also try to drop `item` implicitly. Commit either way.

---

# Part 1 — Group 1 (Catalog, Master Data, Serialized Receive, Sale, Offline Shell)

> Migrations M002–M008 + M010 + M015. After Group 1 the system can: manage catalog + master data, receive serialized units (with labels), and sell serialized units online + offline.

### Task 1.1: `location` model + seed (M002)

**Files:**
- Modify: `backend/app/models.py`
- Create: migration `M002_location`
- Modify: `backend/app/initial_data.py` (seed `YGN_WH`, `CUSTOMER`, `ADJUSTED_OUT`)
- Test: `backend/tests/crud/test_location.py`

**Step 1: Failing test.**

```python
# backend/tests/crud/test_location.py
from sqlmodel import Session, select
from app.models import Location
from app import crud

def test_seed_locations_present(db: Session):
    crud.seed_locations(session=db)
    codes = {l.code for l in db.exec(select(Location)).all()}
    assert {"YGN_WH", "CUSTOMER", "ADJUSTED_OUT"} <= codes
```

**Step 2: Run → FAIL.**

**Step 3: Implement.** Model:

```python
class LocationBase(SQLModel):
    code: str = Field(unique=True, index=True, max_length=32)
    name: str = Field(max_length=255)
    country: str | None = Field(default=None, max_length=64)
    is_active: bool = True

class Location(LocationBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))

class LocationPublic(LocationBase):
    id: uuid.UUID
```

crud:

```python
def seed_locations(*, session: Session) -> None:
    seeds = [("YGN_WH", "Yangon Warehouse"), ("CUSTOMER", "Customer (virtual)"), ("ADJUSTED_OUT", "Adjusted Out (virtual)")]
    for code, name in seeds:
        if not session.exec(select(Location).where(Location.code == code)).first():
            session.add(Location(code=code, name=name))
    session.commit()
```

**Step 4: Migration + apply** (`alembic revision --autogenerate -m "M002 location"` → upgrade). Call `seed_locations` from `initial_data.py`. **Step 5: Run → PASS. Commit.**

---

### Task 1.2: `supplier`, `customer`, `project` models + CRUD + routes (M003, M004)

**Files:** `backend/app/models.py`, `backend/app/crud.py`, `backend/app/api/routes/suppliers.py`, `…/customers.py`, `…/projects.py`, register in `app/api/main.py`; tests under `backend/tests/api/routes/`.

Build these three together — they are the canonical CRUD pattern every later resource follows. Use the spec §4.2 columns. `customer.type` is `DEALER`/`END_CUSTOMER` (add a `CustomerType` enum to Task 0.2 set if you prefer, or inline). `project.code` unique; `project.status` `ACTIVE`/`CLOSED`.

**Per-resource TDD loop (repeat for each):**

1. **Failing test** (`test_create_supplier_admin_only`): staff POST → 403; admin POST → 200 + row persisted; staff GET → 200 (read allowed).
2. Run → FAIL.
3. **Model** (Base/Create/Update/Public), **crud** (`create_x`, `get_x`, `list_x`, `update_x` — keyword-only), **route** (`GET` both roles; `POST`/`PATCH` `dependencies=[Depends(get_admin)]`).
4. **Migration** M003 (supplier+customer), M004 (project, FK customer). Apply.
5. Run → PASS. Commit per resource.

**Customer inline-create nuance (FR-007 + D25):** `POST /customers` is allowed for staff *too* (not admin-only) so staff can create a customer mid-sale. Test: `test_staff_can_create_customer_inline` → staff POST 200. Only `PATCH`/list-management stays admin. Document the duplicate-tolerance (S3) in a code comment — no dedup in v1.

---

### Task 1.3: `product` model + CRUD + routes + price-history (M005)

**Files:** `backend/app/models.py`, `crud.py`, `backend/app/api/routes/products.py`, `backend/app/alembic/versions/*M005*`, tests.

**Step 1: Failing tests.**

```python
# backend/tests/api/routes/test_products.py (excerpt)
def test_admin_creates_serialized_product(client, superuser_token_headers):
    r = client.post("/api/v1/products/", headers=superuser_token_headers, json={
        "sku": "CMP-100", "model_name": "Compressor 100", "brand": "Acme",
        "category": "compressor", "tracking_mode": "SERIALIZED",
        "retail_price_thb": "1200.00", "repair_price_thb": "300.00",
    })
    assert r.status_code == 200 and r.json()["sku"] == "CMP-100"

def test_staff_cannot_create_product(client, staff_token_headers):
    r = client.post("/api/v1/products/", headers=staff_token_headers, json={...})
    assert r.status_code == 403

def test_duplicate_sku_rejected(client, superuser_token_headers):
    # create twice → second returns 409
    ...
```

**Step 2: Run → FAIL. Step 3: Implement** model per spec §4.2 (note: **no `purchase_cost` column** — SERIALIZED cost lives on `unit`, QUANTITY cost derived from `part_batch`). Add `__table_args__` with `UniqueConstraint("sku")` (autogenerate also catches `unique=True` on the field). Money fields `Decimal` + `Numeric(12,2)`. crud raises `HTTPException(409)` on `IntegrityError` for duplicate SKU.

**Step 4: Price-history (FR-002):** add the `price_change` table **now, in Part 1** (do **NOT** defer to M018 — the *write* on `PATCH /products/{id}` records old→new for `retail_price_thb`/`repair_price_thb` in this group, so the table must already exist). Wire `crud.update_product` to insert a `PriceChange` row inside the same transaction when a price field changes. Test `test_price_change_recorded_on_update`. Also expose **`GET /products/{id}/price-history`** (admin, §8) returning the `price_change` rows newest-first; test `test_price_history_lists_changes`.

**Step 5: Migration M005 + (price_change). Run → PASS. Commit.**

> **Catalog seed import (FR-001):** add a `scripts/seed_catalog.py` that reads CSV/Excel (`openpyxl`) → calls `crud.create_product`. One task; test with a 3-row fixture file.

---

### Task 1.4: `unit` + `unit_movement` models + state machine (M008, M015)

This is the **serialized core**. Build the state machine as a pure function first (easy to test exhaustively), then wire it into crud.

**Files:** `backend/app/models.py`, `backend/app/core/state_machine.py` (new), `crud.py`, migrations M008 + M015, tests `backend/tests/core/test_unit_state_machine.py`.

**Step 1: Failing test — exhaustive transition table.**

```python
# backend/tests/core/test_unit_state_machine.py
import pytest
from app.core.state_machine import assert_unit_transition, IllegalTransition
from app.models import UnitState as S, MovementType as M

LEGAL = [
    (S.RECEIVED, M.RECEIVED, S.IN_STOCK),      # receive
    (S.IN_STOCK, M.SOLD, S.SOLD),
    (S.IN_STOCK, M.MAINTENANCE_OUT, S.MAINTENANCE_OUT),
    (S.IN_STOCK, M.PROJECT_OUT, S.PROJECT_OUT),
    (S.IN_STOCK, M.ADJUSTED_OUT, S.ADJUSTED_OUT),
]

@pytest.mark.parametrize("frm,mv,to", LEGAL)
def test_legal_transitions(frm, mv, to):
    assert assert_unit_transition(frm, mv) == to

def test_illegal_transition_from_sold():
    with pytest.raises(IllegalTransition):
        assert_unit_transition(S.SOLD, M.SOLD)
```

**Step 2: Run → FAIL. Step 3: Implement** `state_machine.py`:

```python
from app.models import UnitState, MovementType

class IllegalTransition(Exception): ...

_TABLE = {
    (UnitState.RECEIVED, MovementType.RECEIVED): UnitState.IN_STOCK,
    (UnitState.IN_STOCK, MovementType.SOLD): UnitState.SOLD,
    (UnitState.IN_STOCK, MovementType.MAINTENANCE_OUT): UnitState.MAINTENANCE_OUT,
    (UnitState.IN_STOCK, MovementType.PROJECT_OUT): UnitState.PROJECT_OUT,
    (UnitState.IN_STOCK, MovementType.ADJUSTED_OUT): UnitState.ADJUSTED_OUT,
}

def assert_unit_transition(current: UnitState, event: MovementType) -> UnitState:
    try:
        return _TABLE[(current, event)]
    except KeyError:
        raise IllegalTransition(f"{current} -[{event}]-> illegal")
```

**Step 4: Models.** `unit` (state cache + cost + barcode unique) and `unit_movement` (append-only; `idempotency_key` unique; FK columns nullable for sale/ticket/pull/adjustment). Add `UniqueConstraint("supplier_id","supplier_serial")` and `UniqueConstraint("castranova_barcode")` on `unit`. Migrations M008 + M015. **Step 5: Run → PASS. Commit.**

---

### Task 1.5: Serialized receive flow (FR-005)

**Files:** `crud.py` (`receive_serialized`), `backend/app/api/routes/receipts.py`, `backend/app/services/barcode.py` (new — Code128 + label PDF), tests `backend/tests/api/routes/test_receipts_serialized.py`.

**Step 1: Failing test.**

```python
def test_receive_serialized_creates_unit_and_movement(client, staff_token_headers, db, seed_product_supplier):
    r = client.post("/api/v1/receipts/serialized", headers=staff_token_headers, json={
        "product_id": str(seed_product_supplier.product_id),
        "supplier_id": str(seed_product_supplier.supplier_id),
        "pieces": [{"supplier_serial": "SN-1", "purchase_cost_thb": "900.00"}],
        "idempotency_key": "11111111-1111-1111-1111-111111111111",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["units"][0]["current_state"] == "IN_STOCK"
    assert body["units"][0]["castranova_barcode"]  # generated
```

**Step 2: Run → FAIL. Step 3: Implement** `crud.receive_serialized`: in one transaction, for each piece insert `unit` (state `IN_STOCK` via `assert_unit_transition(RECEIVED, RECEIVED)`, location `YGN_WH`), generate `castranova_barcode` (e.g. `CN-` + short uuid), insert `unit_movement(RECEIVED)`. `services/barcode.py` renders a Code128 label PDF with `reportlab.graphics.barcode.code128`. Route is staff-only.

**Step 4:** Idempotency test: replay same `idempotency_key` → 200 + same units, no duplicate (catch `UNIQUE` on `unit_movement.idempotency_key` → return existing). **Step 5: Run → PASS. Commit.**

> **Label PDF endpoint:** `GET /receipts/serialized/{unit_id}/label.pdf` returns the per-piece label (reprint by serial covers the lost-label scenario).

---

### Task 1.6: Idempotency helper (shared)

**Files:** `backend/app/crud.py` (`get_or_replay`), test `backend/tests/crud/test_idempotency.py`.

Extract the "insert; on `UNIQUE(idempotency_key)` IntegrityError, roll back and return the existing row as a 200" logic into one helper so Sale/Ticket/Pull/Movement all reuse it (DRY). Test: two calls with the same key produce one row and identical responses. Commit.

---

### Task 1.7: Serialized sale (FR-007, UNIT lines only)

**Files:** `models.py` (`sale`, `sale_line` — M010), `crud.py` (`create_sale`), `backend/app/api/routes/sales.py`, `services/receipt_pdf.py`, tests.

**Step 1: Failing tests** — happy path (sale of 1 IN_STOCK unit → `sale` + `sale_line(UNIT)` + `unit_movement(SOLD)`, unit now `SOLD`); **customer required** (omit `customer_id` → 422); **already-sold conflict** (sell same unit twice → second 409 with current state); **offline idempotency** (replay key → 200, no dup).

**Step 2: Run → FAIL. Step 3: Implement** `create_sale` in one transaction: lock the unit row (`select(Unit).where(...).with_for_update()`), assert `IN_STOCK`, snapshot `unit_cost_thb`/`unit_price_thb`, write rows, transition state. Apply override hook stub (full override logic in Part 4). Receipt PDF via `reportlab`. **Step 4: Run → PASS. Commit.**

> PART lines (QUANTITY) raise `400 "QUANTITY parts not yet enabled"` until Part 2 lands — keep the slice shippable.

---

### Task 1.8: Frontend offline shell (Group 1 frontend)

**Files:** `frontend/vite.config.ts` (add `VitePWA`), `frontend/src/lib/query-client.ts`, `frontend/src/main.tsx`, `frontend/src/components/OfflineIndicator.tsx`.

**Step 1:** Configure `vite-plugin-pwa` (`registerType: 'autoUpdate'`, Workbox `globPatterns`) — *Context7-verified*. Add `ReloadPrompt` via `virtual:pwa-register/react` `useRegisterSW`.

**Step 2:** Build the persisted query client (*Context7-verified pattern*):

```ts
// frontend/src/lib/query-client.ts
import { QueryClient } from '@tanstack/react-query'
import { createAsyncStoragePersister } from '@tanstack/query-async-storage-persister'
import { get, set, del } from 'idb-keyval'

export const queryClient = new QueryClient({
  defaultOptions: { queries: { gcTime: 1000 * 60 * 60 * 24 } },  // 24h
})
export const persister = createAsyncStoragePersister({
  storage: { getItem: get, setItem: set, removeItem: del },
})
// REQUIRED so paused mutations resume after reload:
queryClient.setMutationDefaults(['sales'], { mutationFn: postSale })
// …register defaults for receipts, tickets, pulls too
```

Wrap the app in `PersistQueryClientProvider` with `onSuccess={() => queryClient.resumePausedMutations()}`; also call `resumePausedMutations()` on `window` `online`. **No app-level encryption** (S4) — comment this decision inline.

**Step 3:** Manual E2E (Playwright, Task in Part 5): go offline → create sale → reload → reconnect → assert single sale via idempotency. **Commit.**

---

### Task 1.9: Barcode scan input + camera fallback (frontend)

**Files:** `frontend/src/hooks/useScanner.ts` (new), `frontend/src/components/ScanInput.tsx` (new), `frontend/src/components/CameraScanFallback.tsx` (new); wired into the receive, sale, and pull-fulfill screens.

Spec §3 / §6.11 require two scan paths sharing one commit contract (each emits a decoded code string to the focused flow):

- **BT scanner (primary, HID keyboard-wedge):** the scanner types characters into the focused input terminated by CR. `useScanner` buffers keystrokes and **commits only on the CR terminator**, ignoring stray/mistimed keystrokes (debounce by inter-key timing). Reference scanners: TYSSO BCP-2DC, Posiflex CD-3870.
- **Camera fallback (`html5-qrcode`):** when no BT scanner is paired, a "Scan with camera" control opens an in-browser scanner; on decode it emits the same code string (slower; not the primary path). The native `BarcodeDetector` API is a lighter modern alternative where supported — engineer's choice; `html5-qrcode` is the cross-browser default.

**Test (Playwright):** simulate keyboard-wedge keystrokes + CR → input commits once; stray keystrokes without CR → no commit. Camera path is manual-verified. **Commit.**

---

# Part 2 — FIFO Core (the crown jewel)

> Migrations M009 (part_batch) + M016 (part_movement) + M017 (cost_line). Build the FIFO consumer with full concurrency tests before wiring it into sale/maintenance/pull.

### Task 2.1: `part_batch` model + race-safe `batch_no` (M009, S8)

**Files:** `models.py`, `crud.py` (`next_batch_no`, `receive_quantity`), `backend/app/api/routes/receipts.py` (`POST /receipts/quantity`), tests `backend/tests/crud/test_batch_no.py`, `…/test_receipts_quantity.py`.

**Step 1: Failing test — sequential suffixes.**

```python
def test_batch_no_sequential_same_sku_same_day(db, seed_product_quantity):
    sku = seed_product_quantity.sku
    a = crud.next_batch_no(session=db, sku=sku, today=date(2026, 6, 4))
    b = crud.next_batch_no(session=db, sku=sku, today=date(2026, 6, 4))
    assert a.endswith("-001") and b.endswith("-002")
```

**Step 2: Run → FAIL. Step 3: Implement** (Context7/spec §6.4) using a transaction-scoped advisory lock:

```python
from sqlalchemy import func, select as sa_select

def next_batch_no(*, session: Session, sku: str, today: date, adj: bool = False) -> str:
    yyyymmdd = today.strftime("%Y%m%d")
    key = f"{yyyymmdd}-{sku}"
    session.exec(sa_select(func.pg_advisory_xact_lock(func.hashtext(key))))  # noqa
    prefix = f"{yyyymmdd}-{sku}-{'ADJ-' if adj else ''}"
    last = session.exec(
        select(PartBatch.batch_no).where(PartBatch.batch_no.like(f"{prefix}%"))
        .order_by(PartBatch.batch_no.desc())
    ).first()
    suffix = (int(last.rsplit("-", 1)[1]) if last else 0) + 1
    return f"{prefix}{suffix:03d}"
```

`receive_quantity` inserts `part_batch` (`received_qty == remaining_qty`, with the **discrepancy-confirmation note** from FR-006/Flow A.2) + `part_movement(RECEIVED)`. Add `CHECK (received_qty > 0 AND remaining_qty >= 0 AND remaining_qty <= received_qty)` and `UNIQUE(product_id, batch_no)`.

**Step 4: Migration M009 + M016. Run → PASS. Commit.**

---

### Task 2.2: `cost_line` + `consume_quantity_fifo` (M017)

**Files:** `models.py` (`cost_line`), `crud.py` (`consume_quantity_fifo`), tests `backend/tests/crud/test_fifo.py`.

**Step 1: Failing tests** — single batch; exact match; **batch boundary** (5 = 3+2 across two batches → 2 cost_lines with correct split); **oversell** (need > available → `HTTPException(409)` with the real available total); cost-line invariant (`sum(quantity) == requested`, `total = qty*unit_cost`).

```python
def test_fifo_spans_two_batches(db, two_batches_3_and_4):  # costs 10 and 12
    lines = crud.consume_quantity_fifo(session=db, product_id=pid, quantity_needed=5)
    assert [(l.quantity, str(l.unit_cost_thb)) for l in lines] == [(3, "10.00"), (2, "12.00")]
    assert sum(l.quantity for l in lines) == 5
```

**Step 2: Run → FAIL. Step 3: Implement** exactly per spec §6.3 — `select(PartBatch).where(remaining_qty>0).order_by(received_at, id).with_for_update()`, walk oldest-first, decrement `remaining_qty` under lock, build `CostLine` rows, raise 409 if insufficient. **Step 4: Run → PASS. Commit.**

---

### Task 2.3: FIFO concurrency test (no negative stock, no deadlock)

**Files:** `backend/tests/crud/test_fifo_concurrency.py`.

**Step 1:** Use `concurrent.futures.ThreadPoolExecutor` (each thread its own `Session` against the **real Postgres test DB**, not SQLite) to fire 10–20 concurrent consumers on one SKU with limited stock. **Assert:** total consumed ≤ stock, no `remaining_qty` goes negative, every successful consume has balanced `cost_line`s, and at least one loser gets a clean 409 (not a deadlock/500). This is the highest-value test in the suite — `@superpowers:systematic-debugging` if it flakes (usually a missing `with_for_update` or wrong `order_by`). **Commit.**

---

### Task 2.4: Wire FIFO into serialized sale → full sale (FR-007 PART lines)

**Files:** `crud.py` (`create_sale` — replace the 400 stub), tests.

PART line: call `consume_quantity_fifo`, write `part_movement(SOLD)` + its `cost_line[]`, snapshot `unit_cost_thb = total_cogs/quantity` onto the `sale_line`. Test the batch-boundary sale end-to-end (the spec's FR-007 acceptance: `sale` + `sale_line` + `part_movement` + 2 `cost_line` in one txn; offline replay no-dup). **Commit.**

---

### Task 2.5–2.9: Remaining Group 2 (roadmap — execute by analogy)

Each is a CRUD+ledger task using the patterns from Part 1–2. Migrations M011–M013, M016 (done), M018, M019, M020.

| Task | Builds | Files | Test focus |
|---|---|---|---|
| 2.5 Maintenance (FR-008) | `service_ticket` (with `idempotency_key` UNIQUE — offline ticket-open replay) + `service_ticket_part` (M011); `POST /service-tickets`, `PATCH`, `POST /{id}/close` → close runs FIFO per part line, writes `part_movement(MAINTENANCE_OUT)` + `cost_line[]`, sets `closed_at`, transitions any whole-unit swap | `routes/service_tickets.py`, crud | Open→add parts→close atomic; repair-price default; machine-swap note |
| 2.6 Project Pull (FR-009) | `project_pull` + `project_pull_line` (M012); admin `POST /project-pulls`, staff `GET ?state=PENDING`, `POST /{id}/fulfill`, admin `POST /{id}/cancel`; pull state machine (§4.5); revenue=0 cost-only; dual audit (`created_by` + `fulfilled_by`); **no `idempotency_key` on `project_pull`** (admin-created online — the offline-capable fulfill writes idempotent `unit_movement`/`part_movement` rows) | `routes/project_pulls.py`, `core/state_machine.py` (add pull transitions), crud | Fulfill all→FULFILLED; partial→SHORT + notify; cancel PENDING/SHORT; unit race first-write-wins |
| 2.7 Notifications (FR-018) | `notification_preference` (M007 — move earlier if needed) + `notification_log` (M019); `services/notify.py` LINE Messaging + Viber Bot clients with `tenacity` retry; per-user opt-in; `GET/PATCH /notifications/preferences` | `routes/notifications.py`, `services/notify.py` | Mock LINE/Viber; trigger on pull-short & low-stock; retry on 5xx; opt-out respected; failure → `notification_log` |
| 2.8 Low-stock (FR-016) | `GET /low-stock`, `PATCH /products/{id}/min-stock-level`, `PATCH /low-stock/bulk`; alert fires via notify when `sum(remaining_qty)` drops below threshold | `routes/low_stock.py`, crud, hook in `consume_quantity_fifo` | Cross-threshold fires alert; bulk-edit sets 20 SKUs |
| 2.9 Channel margin report (FR-013) | `GET /reports/channel-margin?month=` server-side aggregation: revenue from `sale_line`, COGS from `cost_line` via `part_movement`, grouped by channel (**derived from movement `event_type` / source table — there is no `channel` column**) | `routes/reports.py`, crud aggregation | Hand-calc vs report for mixed Sale/Maint/Project month |
| 2.10 Append-only enforcement (M021) | `REVOKE UPDATE, DELETE` on the 5 ledger tables for the app DB role; `GET /audit` filterable | migration M021, `routes/audit.py` | DB integration test: app role cannot UPDATE `unit_movement` |

---

# Part 3 — Group 3 (Overrides, Adjustment, Holding, Search, Exports) — roadmap

> **STATUS: ✅ COMPLETE** (branch `dev`). All 5 tasks done, TDD + db/security review on the high-risk ones (3.1, 3.2). Migrations added: M006 `system_setting` (`1cb3d9a4ffc0`), M013 `pricing_override_request` (`c9a23e6de5d4`), M014 `stock_adjustment` (`3f69da45b448`). 3.5 wired exports onto the **3 admin reports only**; both-roles list exports (search/low-stock) intentionally deferred to **Part 4.2** role-tiering to avoid leaking COGS to staff (see `memory/deferred-security-hardening.md`). Notes: `part_batch.supplier_id` made nullable (adjustment batches have no supplier); the recurring autogenerate drift (notificationlog index rename + `project_pull_id` FK/index on the movement ledgers) was kept out of M006/M013/M014 — **still unresolved, predates Part 3**, fix in its own migration.

Migrations M006 (system_setting), M013 (pricing_override_request — if not in 2.x), M014 (stock_adjustment).

| Task | Builds | Test focus |
|---|---|---|
| 3.1 Pricing overrides (FR-010) | `pricing_override_request` + `system_setting` threshold; deviation ≤ threshold → `AUTO_APPROVED`, else `PENDING`; `GET /pricing-overrides?state=PENDING`, `POST /{id}/decide`; sale/ticket line blocked until approved; **`GET /reports/override-exceptions?month=` (+`.pdf`/`.xlsx`) monthly report (§8)** | 3% auto-approves; 10% routes to queue; approve→completes; reject→blocked; monthly exceptions report shape |
| 3.2 Stock Adjustment (FR-011) | `stock_adjustment` (M014); admin-only; SERIALIZED→`unit_movement(ADJUSTED_OUT)`; QUANTITY−→FIFO consume; QUANTITY+→new `ADJ-###` batch (reuse `next_batch_no(adj=True)`) | Negative spans 2 batches; positive creates ADJ batch; staff 403 |
| 3.3 Holding period (FR-014) | `GET /reports/holding-period`; `now()-received_at`; threshold from `system_setting` (default 90d) | Flags >threshold; SKU rollup oldest batch |
| 3.4 Search (FR-015) | `GET /search/serial/{barcode}` (full `unit_movement` lifecycle), `GET /search/sku/{sku}` (batch + cost_line history + QOH) | Serial chronological; SKU batch attribution |
| 3.5 Exports (FR-017) | `services/export.py` PDF (`reportlab`) + Excel (`openpyxl`); `.pdf`/`.xlsx` suffix on every list/report route | Snapshot: headers + rows match on-screen for each of the 10 views |

---

# Part 4 — Group 4 (Dashboards, Role-Tiering, Sync-Review, AI) — roadmap

No new schema except `sync_review_item` (M020).

> **STATUS (2026-06-06): 4.1 + 4.2 + 4.3 ✅ COMPLETE; 4.4 ⏸️ DEFERRED.** Built on branch `dev`, TDD + db/security review on the high-risk role-tiering. 4.1 (`docs/superpowers/plans/2026-06-05-castranova-part4-dashboards.md`) and 4.3 (`docs/superpowers/plans/2026-06-06-castranova-part4.3-sync-review.md`) have their own bite-sized plans. Migrations added: M022 notificationlog-index rename, M023 movement FK indexes (4.1/2 drift+review), M020 `sync_review_item` (4.3, `73a2b0eb6de0`). **4.4 (AI) is deferred per the current round's decision** — AI scope is not being built now; revisit when the feature is locked at signing. With 4.4 deferred, Part 4 has no remaining active task.

| Task | Builds | Test focus |
|---|---|---|
| 4.1 Stock-on-Hand dashboard (FR-012) ✅ | `GET /dashboards/stock-on-hand?category=&supplier=&customer=`; QUANTITY `sum(remaining_qty)`, SERIALIZED active units; per-batch drill | P95 <10s at 500 SKUs/5000 batches (perf test) |
| 4.2 Role-tiered customer/project dashboards (FR-020, S7) ✅ | `CustomerDashboardStaffPublic` vs `…AdminPublic` (`GET /customers/{id}/dashboard`) **and** a parallel `ProjectDashboardStaffPublic`/`…AdminPublic` pair (`GET /projects/{id}/dashboard` — admin sees budget + consumed cost, staff sees neither), both mirroring §6.5; route dispatches by `current_user.role`; financial fields **absent** for staff | **Raw HTTP inspection**: staff response has no cost/margin keys on either dashboard; export disabled for staff |
| 4.3 Sync-review queue (95% smooth-sync goal) ✅ | `sync_review_item` (M020); `STALE`/`CONFLICT` mutations recorded; `GET /sync-review?state=PENDING`, `POST /{id}/resolve` (admin) | STALE>7d routed; conflict on replay logged; admin resolve/discard |
| 4.4 AI integration (S11, §7) ⏸️ DEFERRED | **Scope finalized at signing.** Scaffold only: `routes/assistant.py` + provider client in `core/`, behind JWT + role guard, role-tiered (no cost to staff), graceful degradation | Stub returns 501 until feature locked; role guard test |

---

# Part 5 — E2E, Hardening, Deployment — roadmap

> **Ordering note (revised 2026-06-07):** 5.3 (frontend screens) now precedes 5.2
> (browser E2E). Task 5.2's headline acceptance — *"offline queue survives reload;
> no dup on replay"* — is a frontend PWA behaviour (IndexedDB persistence +
> `resumePausedMutations` on reconnect) that can only be exercised through real
> inventory screens in a browser. Those screens do not exist yet (only template
> login/admin/settings routes are built), so **5.2 is BLOCKED-BY 5.3** and is
> deferred until the receive + sale screens (at minimum) ship. The backend for all
> five flows already exists and is covered by pytest; only the browser layer is
> blocked.

| Task | Builds | Test focus |
|---|---|---|
| 5.1 Auth hardening ✅ | `slowapi` rate-limit **`"5 per 15 minutes"`** on `/login` (route needs a `request: Request` param; `@router.post` decorator above `@limiter.limit`); refresh cookie `httpOnly secure sameSite=lax` | 6th login attempt in window → 429 |
| 5.3 Frontend SDK + screens *(do before 5.2)* | `bun run generate-client` after backend stable; admin + staff role-shells; offline indicator + queue counter; per-flow inventory screens (receive, sale, ticket, pull) | SDK regenerates; staff cannot see admin routes |
| 5.2 Playwright E2E ✅ (done 2026-06-11) | 5 paths: receive (serial+qty), sale online, **sale offline→reconnect→replay**, ticket close, pull fulfill (with short) | Offline queue survives reload; no dup on replay |
| 5.4 Deploy | Hostinger KVM 8: Traefik + Let's Encrypt + `pg_dump` cron + Sentry DSN; seed import; LINE/Viber bot enroll 10 users; BT scanner (TYSSO/Posiflex) tuning | Restore drill on staging; 8h offline drill |

**Pre-deploy hardening pass (done 2026-06-12, spec
`docs/superpowers/specs/2026-06-11-castranova-predeploy-hardening-design.md`):**
three stacked PRs (#6 catalog ordering/bounds → #7 security → #8 E2E infra) +
DoD sweep. Highlights: least-privilege `castranova_app` runtime role (the whole
suite + E2E run as it — spec §4.6 REVOKE finally real), replay user-binding,
sync-review submitter audit, rate limits on refresh/logout/pricing/sync-ingest,
YGN_STAFF default, refresh 7d, redaction lock tests, movement→service-ticket
FKs, ordered+bounded list endpoints, per-run E2E DB reset. DoD verified:
coverage **91%** on crud+api (gate 80%), append-only proven at DB level as the
app role, FIFO + redaction suites green, autogenerate drift empty, 455 backend
+ 176 E2E green. **Carried to 5.4 checklist:** SECRET_KEY/.env rotation;
M026 no-op-on-CI grant recovery (note in migration docstring); prestart
password-rotation ordering (backend_pre_start connects as app role BEFORE
ensure_app_role rotates — reorder or use admin URI); ACCESS_TOKEN_EXPIRE 8d vs
spec §6.2 30min (needs frontend silent-refresh decision); proxy-aware
rate-limit key; refresh-token denylist; migration-lock runbook (NOT VALID
pattern); stockadjustment not trigger/REVOKE-protected (pre-existing M021
scope); admin UI has no control to grant BKK_ADMIN (promotion is API-only).

**E2E suite stabilization (done 2026-06-07, prerequisite for 5.2):**
- Removed stale template specs `tests/items.spec.ts` (drove the removed `/items`
  route) and `tests/sign-up.spec.ts` (drove the removed `/signup` route); repointed
  `reset-password.spec.ts` off the deleted signup screen to the `createUser` API
  helper; removed the orphaned `signUpNewUser` / `randomItem*` test helpers.
- 5.1's login rate-limit was 429-ing the E2E suite (many logins from one IP).
  Disabled it for local dev + E2E via `RATE_LIMIT_ENABLED: "false"` in
  `compose.override.yml`; production (compose.yml, no override) keeps the secure
  default `True`. Suite is green: **46 passed**.

**5.2 completion notes (2026-06-11):**
- New browser specs: `tickets.spec.ts` (ticket close → parts consumed FIFO) and
  `pulls.spec.ts` (fulfill 2-of-3 → pull + line settle SHORT, stock −2). The
  fixme'd offline sale test in `sale.spec.ts` is now real: synthetic window
  `offline` event (no service worker in dev, so a network-level offline would
  break the post-queue reload), poll IndexedDB until the persister flushes the
  paused `["sales"]` mutation, reload, rehydrate-replay; asserts unit SOLD with
  **exactly one** SOLD movement (no dup on replay).
- Harness hardening found en route: scan input now driven by a single in-page
  keydown burst (the wedge buffer resets on >50ms inter-key gaps and per-key
  CDP typing stalls past that under load); `playwright.config.ts` pinned to
  `127.0.0.1:5173` + `--strictPort` (a foreign dev server squatting
  `[::1]:5173` silently intercepted the suite) with the matching loopback
  origin added to `BACKEND_CORS_ORIGINS`; reset-password specs navigate the
  emailed link baseURL-relative; `workers: 1` enforced in config.
- Known debt (→ 5.4 test-infra hardening): the shared dev DB accumulates
  ~5 products + ~4 customers per full run, and `list_products` /
  `list_customers` / `list_projects` are unordered `LIMIT 100` — once a table
  crosses 100 rows, freshly seeded rows silently vanish from screen catalogs
  and scans/pickers fail confusingly. Reset recipe: truncate app tables, then
  `docker compose up -d prestart`. Durable fix: `ORDER BY created_at DESC` on
  those list endpoints + per-run DB isolation. Suite at completion: **175
  passed**, 4 consecutive green full runs.

---

## Definition of Done (per the spec's acceptance + §9 testing)

- All 20 FRs have passing tests (unit + integration + the FIFO concurrency suite).
- Append-only `REVOKE` verified at DB level; no `UPDATE`/`DELETE` path in crud for ledgers.
- Staff cannot reach admin routes or see financial fields (verified by raw HTTP inspection, not DOM).
- Offline sale survives reload and replays exactly once (idempotency).
- Coverage ≥ 80% on `crud.py` + route handlers.
- `uv run ruff check . && uv run mypy app` clean; `bun run` biome clean; pre-commit passes.

---

## Execution Handoff

**Plan complete and saved to `docs/plans/2026-06-04-castranova-pos-implementation.md`. Two execution options:**

**1. Subagent-Driven (this session)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. REQUIRED SUB-SKILL: `@superpowers:subagent-driven-development`.

**2. Parallel Session (separate)** — open a new session in a worktree; batch execution with checkpoints. REQUIRED SUB-SKILL: `@superpowers:executing-plans`.

**Which approach?** (Recommended: start Subagent-Driven through Part 2 — the FIFO core is where review between tasks matters most — then switch to batch execution for the Part 3–5 roadmap.)
