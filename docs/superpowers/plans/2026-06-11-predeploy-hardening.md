# Pre-Deployment Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the pre-deploy security/correctness debts per the approved spec `docs/superpowers/specs/2026-06-11-castranova-predeploy-hardening-design.md` — three sequential PRs (catalog correctness → security hardening incl. least-privilege DB role → E2E test-infra) plus a DoD verification sweep.

**Architecture:** PR 1 adds `ORDER BY created_at DESC` + bounded pagination to the unordered LIMIT-100 catalogs. PR 2 lands the code hardening (sanitized IntegrityError 409, replay user-binding, sync-review audit column, rate limits, YGN_STAFF defaults, refresh-expiry alignment, redaction lock tests, shared-team policy comments) and two migrations (service-ticket FKs; least-priv `castranova_app` grant matrix — role itself created by prestart). PR 3 gives Playwright a per-run DB reset via a dependency project. The DoD sweep certifies the final stack.

**Tech Stack:** FastAPI ≥0.114, SQLModel, Alembic, psycopg3, slowapi, pytest; Playwright (bun) for E2E; Docker Compose dev stack.

**Conventions that bind every task:**
- crud raises `HTTPException` directly (e.g. `crud.py:298`) — follow that for new 409s.
- Backend tests run via `bash scripts/test.sh` (full, slow) or `docker compose exec -T backend pytest <path> -q` (targeted). E2E: `cd frontend && bunx playwright test` (config enforces `workers: 1`).
- Every `models.py` change needs an Alembic migration **unless** it is Python-side-only (field defaults) — verify with the drift probe: `docker compose exec -T backend alembic revision --autogenerate -m probe` must produce an empty migration (then delete the probe file).
- Domain 409s ("already sold by…", "N actually available") are informative **by PRD §10 — never genericize them**. The new sanitized 409 is only for `IntegrityError`s that escape crud.
- Review gates: PR 1 → `requesting-code-review`. PRs 2–3 are **high-risk** (ledgers/roles) → additionally dispatch `ecc:database-reviewer` + `ecc:security-reviewer`.
- High-risk rule (CLAUDE.md): the FIFO concurrency suite must be green before any PR that touches consumption paths (PR 2 does — replay binding).

**Flagged, NOT in this plan (do not absorb silently):** `ACCESS_TOKEN_EXPIRE_MINUTES` is 8 days vs spec §6.2's 30 minutes. Aligning it requires frontend silent-refresh wiring (operational risk for 12h warehouse shifts) — decide in Part 5.4. Recorded here so it isn't lost.

---

# PR 1 — Catalog correctness (`feat/hardening-pr1-catalog`)

### Task 1.1: Newest-first ordering on the four catalog list functions

**Files:**
- Modify: `backend/app/crud.py:237-240` (list_suppliers), `:269-272` (list_customers), `:307-310` (list_projects), `:349-352` (list_products)
- Test: `backend/tests/crud/test_catalog_ordering.py` (create)

All four tables have `created_at` (verified: `models.py` Supplier:241, Customer:278, Project:323, Product:370) — no migration needed.

- [ ] **Step 1: Write the failing test**

```python
"""Newest-first ordering on the shared catalogs (hardening spec §3).

Unordered LIMIT-100 heap scans silently dropped newly created rows from every
screen catalog once a table crossed 100 rows (observed live at 107 products,
2026-06-11). Newest-first guarantees recent rows are always on page one.
"""

import uuid

from sqlmodel import Session

from app import crud
from app.models import (
    CustomerCreate,
    ProductCreate,
    ProjectCreate,
    SupplierCreate,
    TrackingMode,
)


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


def test_list_products_newest_first(db: Session) -> None:
    first = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"ORD-A-{_suffix()}",
            model_name="Ordering A",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="10.00",
            repair_price_thb="5.00",
        ),
    )
    second = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"ORD-B-{_suffix()}",
            model_name="Ordering B",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="10.00",
            repair_price_thb="5.00",
        ),
    )
    listed = crud.list_products(session=db, skip=0, limit=500)
    ids = [p.id for p in listed]
    assert ids.index(second.id) < ids.index(first.id)


def test_list_customers_newest_first(db: Session) -> None:
    first = crud.create_customer(
        session=db, customer_in=CustomerCreate(name=f"Ord Cust A {_suffix()}")
    )
    second = crud.create_customer(
        session=db, customer_in=CustomerCreate(name=f"Ord Cust B {_suffix()}")
    )
    listed = crud.list_customers(session=db, skip=0, limit=500)
    ids = [c.id for c in listed]
    assert ids.index(second.id) < ids.index(first.id)


def test_list_suppliers_newest_first(db: Session) -> None:
    first = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"Ord Sup A {_suffix()}")
    )
    second = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name=f"Ord Sup B {_suffix()}")
    )
    listed = crud.list_suppliers(session=db, skip=0, limit=500)
    ids = [s.id for s in listed]
    assert ids.index(second.id) < ids.index(first.id)


def test_list_projects_newest_first(db: Session) -> None:
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name=f"Ord Proj Cust {_suffix()}")
    )
    first = crud.create_project(
        session=db,
        project_in=ProjectCreate(
            code=f"ORD-A-{_suffix()}", name="Ord Proj A", customer_id=customer.id
        ),
    )
    second = crud.create_project(
        session=db,
        project_in=ProjectCreate(
            code=f"ORD-B-{_suffix()}", name="Ord Proj B", customer_id=customer.id
        ),
    )
    listed = crud.list_projects(session=db, skip=0, limit=500)
    ids = [p.id for p in listed]
    assert ids.index(second.id) < ids.index(first.id)
```

NOTE for the implementer: check the actual `*Create`-schema constructor names/signatures in `models.py` and the crud create-function names before running; adjust the test to the real names (they exist — receive/sale tests use them — but verify exact kwargs, e.g. whether crud takes `product_in=`/`customer_in=` or positional `data=`).

- [ ] **Step 2: Run the test, verify it fails**

Run: `docker compose exec -T backend pytest tests/crud/test_catalog_ordering.py -q`
Expected: 4 FAILs (newest item is appended last in heap order, so `index(second) > index(first)`). If any PASS spuriously (heap order coincidence), still proceed — the implementation makes the property guaranteed rather than coincidental.

- [ ] **Step 3: Add ORDER BY to the four crud functions**

In `backend/app/crud.py`, change each of the four list functions (suppliers :237, customers :269, projects :307, products :349) to the same shape (shown for products; repeat identically for the other three with their model class):

```python
def list_products(
    *, session: Session, skip: int = 0, limit: int = 100
) -> list[Product]:
    return list(
        session.exec(
            select(Product)
            .order_by(col(Product.created_at).desc())
            .offset(skip)
            .limit(limit)
        ).all()
    )
```

`col` is already imported in crud.py (used at `:1419` and elsewhere) — verify the import line and reuse it.

- [ ] **Step 4: Run the test, verify it passes**

Run: `docker compose exec -T backend pytest tests/crud/test_catalog_ordering.py -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/crud.py backend/tests/crud/test_catalog_ordering.py
git commit -m "fix(catalog): newest-first ordering on product/customer/supplier/project lists"
```

### Task 1.2: Bounded skip/limit on all unbounded list routes

**Files:**
- Modify: `backend/app/api/routes/users.py:35`, `products.py:22`, `customers.py:25`, `suppliers.py:19`, `projects.py:23`, `project_pulls.py:57`
- Test: `backend/tests/api/test_pagination_bounds.py` (create)

Adopt the already-bounded pattern from `pricing_overrides.py:47`. (`pricing_overrides` and `sync_review`/`audit` are already bounded or use their own params — verify `audit.py` while in there; bound it the same way if it has bare `skip`/`limit`.)

- [ ] **Step 1: Write the failing test**

```python
"""Pagination bounds (hardening spec §3): limit clamped to [1, 500], skip >= 0."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings

BOUNDED_LIST_PATHS = [
    "/users/",
    "/products",
    "/customers",
    "/suppliers",
    "/projects",
    "/project-pulls",
]


@pytest.mark.parametrize("path", BOUNDED_LIST_PATHS)
@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 501}, {"skip": -1}],
    ids=["limit-zero", "limit-over-cap", "negative-skip"],
)
def test_out_of_bounds_pagination_is_422(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    path: str,
    params: dict[str, int],
) -> None:
    r = client.get(
        f"{settings.API_V1_STR}{path}", headers=superuser_token_headers, params=params
    )
    assert r.status_code == 422
```

NOTE: check the exact route paths (trailing slash differs per router — `users` uses `/users/`; verify each in the route files) and the existing fixture names (`client`, `superuser_token_headers` are the template's standard conftest fixtures — confirm in `backend/tests/conftest.py` / `backend/tests/utils`).

- [ ] **Step 2: Run the test, verify it fails**

Run: `docker compose exec -T backend pytest tests/api/test_pagination_bounds.py -q`
Expected: FAIL — currently 200 for all out-of-bounds params.

- [ ] **Step 3: Bound the six routes**

For each route in the Files list, change the signature to the `pricing_overrides.py:47` pattern (shown for `products.py:22`; repeat identically):

```python
from typing import Annotated

from fastapi import Query


@router.get("", response_model=list[ProductPublic])
def read_products(
    session: SessionDep,
    skip: Annotated[int, Query(ge=0, le=10_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[ProductPublic]:
    return crud.list_products(session=session, skip=skip, limit=limit)
```

Keep each route's existing decorator, deps, and return exactly as-is — only the two params change. Add the `Annotated`/`Query` imports where missing.

- [ ] **Step 4: Run tests + regenerate the frontend SDK**

Run: `docker compose exec -T backend pytest tests/api/test_pagination_bounds.py -q` → all passed.
Run: `bash scripts/test.sh` → full backend suite green (catches any fixture that relied on out-of-bounds pagination).
Run: `cd frontend && bun run generate-client && cd ..` — the OpenAPI param constraints changed; commit the regenerated `frontend/src/client/`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/ backend/tests/api/test_pagination_bounds.py frontend/src/client/
git commit -m "fix(api): validate skip/limit bounds on all list endpoints"
```

### Task 1.3: Ship PR 1

- [ ] **Step 1:** Full verification: `bash scripts/test.sh` green; `cd frontend && bunx playwright test` green; `uv run ruff check .` + `uv run mypy app` (in `backend/`) clean.
- [ ] **Step 2:** Dispatch `superpowers:requesting-code-review` for the branch diff; fix Critical/Important findings.
- [ ] **Step 3:** Ship with `create-pr` (base: `dev`). Title: `fix(catalog): ordered, bounded list endpoints (pre-deploy hardening PR 1)`.

---

# PR 2 — Security hardening (`feat/hardening-pr2-security`)

> Branch from `dev` after PR 1 merges. Task order matters: the DB-role task (2.8) is LAST — everything must be green before the connection switches.

### Task 2.1: Global IntegrityError handler → sanitized 409

**Files:**
- Modify: `backend/app/main.py` (after line 27, the RateLimitExceeded handler)
- Test: `backend/tests/api/test_integrity_handler.py` (create)

- [ ] **Step 1: Write the failing test**

```python
"""A DB IntegrityError that escapes crud must surface as a sanitized 409,
never a raw 500 leaking constraint/table names (hardening spec §4.1.1).

Domain 409s raised explicitly by crud (PRD §10: "already sold by …") are NOT
covered by this handler and keep their informative payloads.
"""

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.main import app


def test_integrity_error_returns_sanitized_409() -> None:
    @app.get("/_test/integrity-boom", include_in_schema=False)
    def _boom() -> None:  # pragma: no cover - exercised via TestClient
        raise IntegrityError(
            statement="INSERT INTO secret_table ...",
            params=None,
            orig=Exception('violates check constraint "ck_secret_internal"'),
        )

    try:
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/_test/integrity-boom")
        assert r.status_code == 409
        assert r.json() == {"detail": "Conflicting or invalid data."}
        body = r.text.lower()
        assert "secret_table" not in body
        assert "ck_secret_internal" not in body
    finally:
        app.router.routes = [
            rt for rt in app.router.routes if getattr(rt, "path", "") != "/_test/integrity-boom"
        ]
```

- [ ] **Step 2: Run, verify it fails** — `docker compose exec -T backend pytest tests/api/test_integrity_handler.py -q` → FAIL (currently 500).

- [ ] **Step 3: Implement the handler in `main.py`**

```python
import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    # Sanitized boundary for IntegrityErrors that escape crud's explicit
    # catches (programming bugs / raw SQL). Domain conflicts (PRD §10) are
    # raised by crud as informative HTTPException(409)s and never reach here.
    # Full detail goes to logs/Sentry; the client gets no schema internals.
    logger.exception("Unhandled IntegrityError on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=409, content={"detail": "Conflicting or invalid data."})
```

Place after the existing `app.add_exception_handler(RateLimitExceeded, ...)` line; merge imports with the existing ones.

- [ ] **Step 4: Run** the new test (passes) + `docker compose exec -T backend pytest tests/api -q` (no regressions).
- [ ] **Step 5: Commit** — `git add backend/app/main.py backend/tests/api/test_integrity_handler.py && git commit -m "feat(api): sanitized 409 for escaped IntegrityErrors"`

### Task 2.2: Replay user-binding on the four idempotent creates

**Files:**
- Modify: `backend/app/crud.py` — `create_sale` (replay branch at ~:1520), `receive_serialized` (full-replay + concurrent-replay branches at ~:423-493), `receive_quantity` (replay branches at ~:565-645), `open_service_ticket` (existing-row branch at ~:1787-1821)
- Test: `backend/tests/crud/test_replay_user_binding.py` (create)

Actor columns (verified): `sale.created_by_user_id`, `unit.received_by_user_id`, `part_batch.received_by_user_id`, `service_ticket.created_by_user_id`.

- [ ] **Step 1: Write the failing tests**

```python
"""Same-key/different-user idempotency replays are rejected with 409
(hardening spec §4.1.2 / spec §6.6 addendum). Same-user replays keep
returning the existing row with 200 semantics — that behavior is already
covered by the existing idempotency tests.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlmodel import Session

from app import crud

# Reuse this module's existing seeding helpers if present; otherwise import
# the seed helpers used by tests/crud/test_receipts*.py (product+supplier
# factories) — follow the actual fixture names found there.
from tests.utils.user import create_random_user  # verify path: used across tests/


def _two_users(db: Session):
    return create_random_user(db), create_random_user(db)


def test_receive_quantity_replay_other_user_409(db: Session, seeded_qty_product, seeded_supplier) -> None:
    user_a, user_b = _two_users(db)
    key = uuid.uuid4()
    kwargs = dict(
        session=db,
        product_id=seeded_qty_product.id,
        supplier_id=seeded_supplier.id,
        received_qty=3,
        purchase_cost_thb=Decimal("10.00"),
        idempotency_key=key,
    )
    crud.receive_quantity(**kwargs, received_by_user_id=user_a.id)
    with pytest.raises(HTTPException) as exc:
        crud.receive_quantity(**kwargs, received_by_user_id=user_b.id)
    assert exc.value.status_code == 409


def test_receive_quantity_replay_same_user_ok(db: Session, seeded_qty_product, seeded_supplier) -> None:
    user_a, _ = _two_users(db)
    key = uuid.uuid4()
    kwargs = dict(
        session=db,
        product_id=seeded_qty_product.id,
        supplier_id=seeded_supplier.id,
        received_qty=3,
        purchase_cost_thb=Decimal("10.00"),
        idempotency_key=key,
        received_by_user_id=user_a.id,
    )
    first = crud.receive_quantity(**kwargs)
    again = crud.receive_quantity(**kwargs)
    assert again.id == first.id
```

Write the analogous other-user-409 + same-user-ok pairs for `receive_serialized`, `create_sale` (seed a sellable unit first, exactly as `tests/crud/test_sales*.py` does), and `open_service_ticket` (needs only a customer). **Copy the seeding patterns from the existing test files for those flows** — do not invent new factories; if `seeded_qty_product`/`seeded_supplier` fixtures don't exist under those names, inline the same seeding the neighboring tests use.

- [ ] **Step 2: Run, verify the 409 tests fail** (replay currently returns the row regardless of caller).

- [ ] **Step 3: Implement the binding checks in crud.py**

Add one module-level helper near the top of the crud idempotency section:

```python
def _assert_replay_actor(*, stored_user_id: uuid.UUID, caller_user_id: uuid.UUID) -> None:
    """Same-key replays must come from the original actor (spec §6.6 addendum).

    Client idempotency keys are 122-bit UUIDs; a same-key/different-user hit is
    a stolen/duplicated key, never a legitimate offline retry.
    """
    if stored_user_id != caller_user_id:
        raise HTTPException(
            status_code=409,
            detail="Idempotency key was already used by a different user.",
        )
```

Then, at each replay return point:
- `create_sale` replay branch: `_assert_replay_actor(stored_user_id=replay.created_by_user_id, caller_user_id=created_by_user_id)` before `return replay`.
- `receive_quantity`: same with `replay.received_by_user_id`, in BOTH the up-front replay branch and the `except IntegrityError` concurrent-replay branch.
- `receive_serialized`: in the full-replay branch and the concurrent-replay branch, check the first replayed unit: `_assert_replay_actor(stored_user_id=<first unit>.received_by_user_id, caller_user_id=received_by_user_id)` (all units of one receipt share the actor).
- `open_service_ticket`: in the `existing is not None` branch with `existing.created_by_user_id`; also after `get_or_replay` if its replay flag indicates an existing row was returned (inspect `get_or_replay`'s return contract — it returns `(row, created: bool)`).

- [ ] **Step 4: Run** the new file + the existing idempotency/FIFO tests: `docker compose exec -T backend pytest tests/crud -q` → green. **Run the FIFO concurrency suite explicitly** (it covers the concurrent-replay paths this task touched): `docker compose exec -T backend pytest tests/crud/test_fifo_concurrency.py -q` (verify the real filename via `ls backend/tests/crud/`).
- [ ] **Step 5: Commit** — `git commit -m "feat(security): bind idempotency replays to the original actor"`

### Task 2.3: `submitted_by_user_id` on sync-review + ownership-enforced replay

**Files:**
- Modify: `backend/app/models.py:981-1011` (SyncReviewItem + its Public schemas nearby), `backend/app/crud.py:1419-1439` (create_sync_review_item), `backend/app/api/routes/sync_review.py:18-31` (ingest route)
- Create: `backend/app/alembic/versions/<rev>_m024_syncreview_submitted_by.py` (autogenerate)
- Test: extend `backend/tests/api/test_sync_review.py` (locate the existing file via `ls backend/tests/api/ | grep -i sync`)

- [ ] **Step 1: Write the failing tests** (in the existing sync-review test file's style):

```python
def test_ingest_records_submitter(db: Session, client: TestClient, normal_user_token_headers) -> None:
    payload = {
        "idempotency_key": str(uuid.uuid4()),
        "mutation_kind": "sale",
        "payload": {"k": "v"},
        "reason": "STALE",
    }
    r = client.post(f"{settings.API_V1_STR}/sync-review", json=payload, headers=normal_user_token_headers)
    assert r.status_code == 200
    item = db.exec(
        select(SyncReviewItem).where(
            SyncReviewItem.idempotency_key == uuid.UUID(payload["idempotency_key"])
        )
    ).one()
    assert item.submitted_by_user_id is not None


def test_ingest_replay_other_user_409(client: TestClient, normal_user_token_headers, superuser_token_headers) -> None:
    payload = {
        "idempotency_key": str(uuid.uuid4()),
        "mutation_kind": "sale",
        "payload": {"k": "v"},
        "reason": "STALE",
    }
    assert client.post(f"{settings.API_V1_STR}/sync-review", json=payload, headers=normal_user_token_headers).status_code == 200
    r = client.post(f"{settings.API_V1_STR}/sync-review", json=payload, headers=superuser_token_headers)
    assert r.status_code == 409
```

(Adapt fixture names/paths to the existing sync-review tests; same-user replay-200 is already covered there — keep it green.)

- [ ] **Step 2: Run, verify failures** (no column / no 409 yet).

- [ ] **Step 3: Model + crud + route changes**

`models.py` SyncReviewItem — add after `resolved_by_user_id`:

```python
    submitted_by_user_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", index=True
    )
```

Add `submitted_by_user_id: uuid.UUID | None` to the **admin** public schema (`SyncReviewItemPublic`) only — NOT the staff schema (`SyncReviewItemStaffPublic`).

`crud.py` `create_sync_review_item` — new required kwarg + binding:

```python
def create_sync_review_item(
    *, session: Session, data: SyncReviewItemCreate, submitted_by_user_id: uuid.UUID
) -> SyncReviewItem:
    item, created = get_or_replay(
        session=session,
        statement=select(SyncReviewItem).where(
            col(SyncReviewItem.idempotency_key) == data.idempotency_key
        ),
        build=lambda: SyncReviewItem(
            idempotency_key=data.idempotency_key,
            mutation_kind=data.mutation_kind,
            payload=data.payload,
            reason=data.reason,
            submitted_by_user_id=submitted_by_user_id,
        ),
    )
    if not created and item.submitted_by_user_id is not None:
        _assert_replay_actor(
            stored_user_id=item.submitted_by_user_id, caller_user_id=submitted_by_user_id
        )
    return item
```

(`None` legacy rows replay without binding — they predate the column. Verify `get_or_replay` returns `(row, created)` in that order; adjust if its contract differs.)

`sync_review.py` ingest route — replace `dependencies=[Depends(get_current_user)]` with an injected `current_user: CurrentUser` and pass `submitted_by_user_id=current_user.id`.

- [ ] **Step 4: Autogenerate + review the migration**

```bash
docker compose exec -T backend alembic revision --autogenerate -m "m024 syncreview submitted_by"
```
Review the generated file: exactly one `add_column` (nullable UUID FK) + one `create_index`; nothing else. Then `docker compose exec -T backend alembic upgrade head`.

- [ ] **Step 5: Run** sync-review tests + drift probe (empty) → green. **Step 6: Commit** — `git commit -m "feat(sync-review): record submitter; bind ingest replays to the submitter"`

### Task 2.4: Rate limits on refresh/logout/pricing-overrides/sync-ingest

**Files:**
- Modify: `backend/app/core/limiter.py` (add constants), `backend/app/api/routes/login.py:78-128`, `pricing_overrides.py:19-39`, `sync_review.py:18-31`
- Test: extend the existing login rate-limit test file (locate via `grep -rln "RATE_LIMIT\|limiter" backend/tests/`) with one test per endpoint, following its existing enable-limiter pattern.

- [ ] **Step 1: Constants in `limiter.py`** (below `LOGIN_RATE_LIMIT`):

```python
REFRESH_RATE_LIMIT = "5/15 minutes"   # spec §6.2: auth endpoints
LOGOUT_RATE_LIMIT = "20/15 minutes"
PRICING_OVERRIDE_RATE_LIMIT = "30/hour"   # threshold-probe + queue-flood guard
SYNC_INGEST_RATE_LIMIT = "120/hour"  # above any legit 7-day-queue replay burst
```

- [ ] **Step 2: Write failing tests** — for each endpoint, with the limiter force-enabled (copy the existing login-rate-limit test's enable/disable fixture pattern exactly), hit the endpoint limit+1 times and assert the final response is 429. For refresh/logout, unauthenticated requests are fine (the 401/400 still counts against the limit). For pricing-overrides/sync-ingest use `normal_user_token_headers` and a minimal valid body per existing tests in those files.

- [ ] **Step 3: Decorate the routes** (login pattern from `login.py:47-49` — `@limiter.limit` BELOW `@router.post`, route takes `request: Request`):

- `refresh_access_token` (already has `request: Request`): add `@limiter.limit(REFRESH_RATE_LIMIT)`.
- `logout`: add `@limiter.limit(LOGOUT_RATE_LIMIT)` and add `request: Request,  # noqa: ARG001 — required by slowapi` as first param.
- `create_pricing_override`: add `@limiter.limit(PRICING_OVERRIDE_RATE_LIMIT)` + `request: Request` param (same noqa).
- `ingest_sync_review_item`: add `@limiter.limit(SYNC_INGEST_RATE_LIMIT)` + `request: Request` param (same noqa).

Import the constants from `app.core.limiter` in each route file.

- [ ] **Step 4: Run** the new tests + the whole api suite (`pytest tests/api -q`) — the conftest session fixture disables the limiter globally, so unrelated tests stay unaffected. **Step 5: Commit** — `git commit -m "feat(security): rate-limit refresh/logout/pricing-overrides/sync-ingest"`

### Task 2.5: Least-privilege role defaults (YGN_STAFF)

**Files:**
- Modify: `backend/app/models.py:141` (UserBase.role default), `backend/app/api/routes/private.py:16-38`, `backend/app/core/db.py:24-36` (init_db)
- Test: extend `backend/tests/api/test_private.py` (or matching name) + `backend/tests/api/test_users.py`

- [ ] **Step 1: Write failing tests**

```python
def test_new_user_defaults_to_staff(db: Session) -> None:
    user = crud.create_user(
        session=db,
        user_create=UserCreate(email=random_email(), password=random_lower_string()),
    )
    assert user.role == UserRole.YGN_STAFF


def test_private_create_user_defaults_to_staff(client: TestClient, db: Session) -> None:
    email = random_email()
    r = client.post(
        f"{settings.API_V1_STR}/private/users/",
        json={"email": email, "password": random_lower_string(), "full_name": "P"},
    )
    assert r.status_code == 200
    user = db.exec(select(User).where(User.email == email)).one()
    assert user.role == UserRole.YGN_STAFF


def test_first_superuser_seed_stays_admin(db: Session) -> None:
    su = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    assert su.role == UserRole.BKK_ADMIN
```

- [ ] **Step 2: Run, verify the first two fail** (currently BKK_ADMIN). The third passes only after Step 3's init_db change *and* a reseed — see Step 4.

- [ ] **Step 3: Implement**

`models.py:141`: `role: UserRole = Field(default=UserRole.YGN_STAFF)`.

`private.py` — add the explicit field and pass it through:

```python
class PrivateUserCreate(BaseModel):
    email: str
    password: str
    full_name: str
    is_verified: bool = False
    role: UserRole = UserRole.YGN_STAFF
```
and in the route body add `role=user_in.role,` to the `User(...)` constructor.

`core/db.py` init_db — make the seed explicit (spec D2):

```python
        user_in = UserCreate(
            email=settings.FIRST_SUPERUSER,
            password=settings.FIRST_SUPERUSER_PASSWORD,
            is_superuser=True,
            role=UserRole.BKK_ADMIN,
        )
```
(import `UserRole` alongside the existing models import).

- [ ] **Step 4: Reseed + run the full backend suite**

The dev DB's existing superuser predates the change (role already BKK_ADMIN — fine). Run `bash scripts/test.sh`. **Expect fallout:** any test/fixture that created a user via default and then exercised admin behavior now gets staff. Fix each by passing `role=UserRole.BKK_ADMIN` explicitly where admin intent is real; where the test *meant* staff, the `createStaffUser`-style workaround can be simplified later (do not refactor here — minimal explicit-role fixes only). Drift probe must stay empty (Python-side default, no server_default).

- [ ] **Step 5: E2E sanity** — `cd frontend && bunx playwright test tests/admin.spec.ts tests/receive.spec.ts` (the privateApi `createUser` helper now yields staff users; `createStaffUser` keeps working — verify no test asserted the old admin default).
- [ ] **Step 6: Commit** — `git commit -m "feat(security): default new users to YGN_STAFF (least privilege)"`

### Task 2.6: Refresh-token expiry → 7 days (spec §6.2)

**Files:** Modify `backend/app/core/config.py:39`.

- [ ] **Step 1:** Change `REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 30` → `60 * 24 * 7`, with comment `# spec §6.2: refresh tokens live 7 days`.
- [ ] **Step 2:** Run the login/refresh tests: `docker compose exec -T backend pytest tests/api/test_login.py -q` → green (cookie max-age derives from the setting).
- [ ] **Step 3: Commit** — `git commit -m "fix(auth): align refresh-token expiry to spec §6.2 (7 days)"`

### Task 2.7: FR-015 / staff financial-redaction lock tests

**Files:** Create `backend/tests/api/test_staff_redaction_lock.py`.

Audit conclusion (verified 2026-06-11): the staff-reachable read surfaces are ALREADY cost-free by design — `SerialMovementPublic`/`SkuBatchPublic`/`SkuSearchResult` (models.py:1634-1670) carry no THB cost; `LowStockItemPublic` (models.py:405) carries none; all `/reports/*` are admin-gated (`reports.py:15`). PRD FR-015's "batch-by-batch attribution" is intact (batch_no/received_at/quantities). **This task locks that state with raw-HTTP tests so a future schema edit cannot silently regress it.**

- [ ] **Step 1: Write the lock tests**

```python
"""Raw-HTTP redaction lock (hardening spec §4.1.7, spec §6.5/S7, PRD FR-015).

Walks staff-token responses and asserts NO derived-financial key appears at any
depth. Catches future schema edits that re-leak cost to staff. The one staff-
visible cost-by-design is the receive flow echoing the staff's own input
(2026-06-09 decision) — receive endpoints are deliberately not swept here.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings

FORBIDDEN_KEYS = {
    "purchase_cost_thb",
    "unit_cost_thb",
    "total_cost_thb",
    "total_cogs_thb",
    "cogs_thb",
    "margin_thb",
    "budget_thb",
    "consumed_cost_thb",
    "deviation_pct",
}


def _assert_no_forbidden_keys(node: Any, path: str = "$") -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            assert k not in FORBIDDEN_KEYS, f"financial key '{k}' leaked at {path}"
            _assert_no_forbidden_keys(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _assert_no_forbidden_keys(v, f"{path}[{i}]")


STAFF_GET_PATHS = [
    "/low-stock",
    "/products",
    "/dashboards/stock-on-hand",
    "/project-pulls",
]


@pytest.mark.parametrize("path", STAFF_GET_PATHS)
def test_staff_list_surfaces_carry_no_financials(
    client: TestClient, staff_token_headers: dict[str, str], path: str
) -> None:
    r = client.get(f"{settings.API_V1_STR}{path}", headers=staff_token_headers)
    assert r.status_code == 200
    _assert_no_forbidden_keys(r.json())


def test_staff_sku_search_keeps_attribution_without_cost(
    client: TestClient, staff_token_headers: dict[str, str], seeded_received_batch
) -> None:
    # seeded_received_batch: seed a QUANTITY product + one received batch the
    # same way tests/api/test_search*.py does — copy that seeding verbatim.
    r = client.get(
        f"{settings.API_V1_STR}/search/sku/{seeded_received_batch.sku}",
        headers=staff_token_headers,
    )
    assert r.status_code == 200
    body = r.json()
    _assert_no_forbidden_keys(body)
    # PRD FR-015: attribution preserved — batches present with qty + timestamps.
    assert body["batches"], "batch-by-batch attribution must remain for staff"
    assert {"batch_no", "received_at", "received_qty", "remaining_qty"} <= set(
        body["batches"][0]
    )


@pytest.mark.parametrize(
    "path",
    ["/reports/channel-margin?month=2026-06", "/reports/holding-period"],
)
def test_staff_cannot_reach_cost_reports(
    client: TestClient, staff_token_headers: dict[str, str], path: str
) -> None:
    r = client.get(f"{settings.API_V1_STR}{path}", headers=staff_token_headers)
    assert r.status_code == 403
```

A `staff_token_headers` fixture probably exists (the redaction tests from Parts 4–5.3 used one) — find it via `grep -rn "staff_token\|YGN_STAFF" backend/tests/ | head`; if absent, build it in this file with the existing user-creation utils (`role=UserRole.YGN_STAFF` explicit).

- [ ] **Step 2: Run** — expected: all green immediately (this is a lock, not a fix). If any leak IS found, that's a real finding: apply the §6.5 Staff-schema pattern to that surface before proceeding (absent fields, union response_model, `deps.is_admin` dispatch), then re-run.
- [ ] **Step 3: Commit** — `git commit -m "test(security): raw-HTTP staff financial-redaction lock (FR-015/S7)"`

### Task 2.8: Shared-team access-policy comments (no behavior change)

**Files:** Modify `backend/app/api/routes/sales.py:66`, `service_tickets.py:63,81`, `project_pulls.py:82`, `receipts.py:58`.

- [ ] **Step 1:** Add this comment (adjusted per site) directly above each of the five route decorators:

```python
# Shared-team access (recorded decision D3, hardening spec 2026-06-11): any
# authenticated staff/admin may act on any <sale receipt / service ticket /
# project pull / unit label> — the ~5-person warehouse team works shifts over
# shared objects (PRD §5). Ownership scoping was considered and rejected. No
# derived financials are exposed on this surface.
```

- [ ] **Step 2:** `docker compose exec -T backend pytest tests/api -q` (nothing changed) + commit: `git commit -m "docs(security): record shared-team access decision at the four IDOR sites"`

### Task 2.9: Wire movement→service-ticket FKs (+ missing index)

**Files:**
- Modify: `backend/app/models.py` — `UnitMovement.service_ticket_id` and `PartMovement.service_ticket_id` field declarations (locate via `grep -n "service_ticket_id" backend/app/models.py`)
- Create: `backend/app/alembic/versions/<rev>_m025_movement_service_ticket_fks.py`
- Test: `backend/tests/alembic/test_m025_fks.py` (create; follow the existing migration-test pattern if `backend/tests/` has one — check `ls backend/tests/`)

- [ ] **Step 1: Models** — add `foreign_key="serviceticket.id"` to both `service_ticket_id` declarations (mirror how `project_pull_id` is declared on the same models — same pattern, M012 precedent).

- [ ] **Step 2: Autogenerate, then EDIT the migration**

```bash
docker compose exec -T backend alembic revision --autogenerate -m "m025 movement service_ticket fks"
```
Edit the generated file so `upgrade()` is exactly:

```python
def upgrade():
    # Orphan pre-check: the FK must not be created over dangling references.
    conn = op.get_bind()
    for table in ("partmovement", "unitmovement"):
        orphans = conn.execute(
            sa.text(
                f"SELECT COUNT(*) FROM {table} m WHERE m.service_ticket_id IS NOT NULL "
                "AND NOT EXISTS (SELECT 1 FROM serviceticket t WHERE t.id = m.service_ticket_id)"
            )
        ).scalar()
        if orphans:
            raise RuntimeError(
                f"{table} has {orphans} orphaned service_ticket_id rows; resolve before migrating"
            )
    op.create_foreign_key(
        "fk_partmovement_service_ticket_id",
        "partmovement", "serviceticket", ["service_ticket_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_unitmovement_service_ticket_id",
        "unitmovement", "serviceticket", ["service_ticket_id"], ["id"],
    )
    op.create_index(
        "ix_unitmovement_service_ticket_id",
        "unitmovement", ["service_ticket_id"],
        postgresql_where=sa.text("service_ticket_id IS NOT NULL"),
    )
```
`downgrade()` drops the index + both FKs (`op.drop_constraint(..., type_="foreignkey")`). If autogenerate also emits unrelated diffs, the models drifted — stop and reconcile first (M022/M023 left autogenerate empty).

NOTE: `partmovement` already has partial index `ix_partmovement_service_ticket_id` (M023) — do NOT recreate it; only `unitmovement` lacks one.

- [ ] **Step 3: Apply + verify**: `alembic upgrade head`; then drift probe (empty); then a quick FK smoke test: inserting a `partmovement` with a random `service_ticket_id` raises `IntegrityError` (write it in the new test file using the db fixture, building the minimal movement row the way `tests/crud/test_append_only.py`'s `ledger_ids` fixture does).
- [ ] **Step 4:** `bash scripts/test.sh` green. **Step 5: Commit** — `git commit -m "feat(db): wire movement→service_ticket FKs + unitmovement partial index (M015/M016 gap)"`

### Task 2.10: Least-privilege runtime DB role `castranova_app` (LAST in PR 2)

**Files:**
- Modify: `backend/app/core/config.py` (app/admin URI split), `backend/app/alembic/env.py:33-34` (admin URI), `backend/tests/conftest.py:19-39` (admin engine for teardown), `backend/scripts/prestart.sh`, `compose.yml` (backend + prestart env), `compose.override.yml` (if backend env block needs the vars), `.env` (+ mirror in `.env.example` if present)
- Create: `backend/app/ensure_app_role.py`, `backend/app/alembic/versions/<rev>_m026_app_role_grants.py`
- Test: extend `backend/tests/crud/test_append_only.py`

- [ ] **Step 1: Config split** (`config.py`, after the POSTGRES_* block):

```python
    # Least-privilege runtime role (hardening spec §4.2.3). When unset, the app
    # falls back to the admin (POSTGRES_USER) connection — pre-hardening behavior.
    POSTGRES_APP_USER: str = ""
    POSTGRES_APP_PASSWORD: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> PostgresDsn:
        return PostgresDsn.build(
            scheme="postgresql+psycopg",
            username=self.POSTGRES_APP_USER or self.POSTGRES_USER,
            password=self.POSTGRES_APP_PASSWORD or self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_ADMIN_DATABASE_URI(self) -> PostgresDsn:
        """Superuser connection — migrations, role management, test teardown."""
        return PostgresDsn.build(
            scheme="postgresql+psycopg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )
```
(Replace the existing `SQLALCHEMY_DATABASE_URI` property; keep decorator style identical to the current one at config.py:73-81.)

- [ ] **Step 2: Point Alembic + prestart at the admin connection**

`alembic/env.py:33-34`: `return str(settings.SQLALCHEMY_ADMIN_DATABASE_URI)`.

`backend/app/ensure_app_role.py` (new):

```python
"""Idempotently ensure the least-privilege runtime role exists (prestart step).

Runs as the admin connection BEFORE `alembic upgrade head` so the grants
migration (M026) can reference the role. No-op when POSTGRES_APP_USER is unset.
Secrets stay in env — never in migrations.
"""

import logging

from sqlalchemy import create_engine, text

from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    if not settings.POSTGRES_APP_USER:
        logger.info("POSTGRES_APP_USER unset — skipping app-role creation")
        return
    engine = create_engine(str(settings.SQLALCHEMY_ADMIN_DATABASE_URI))
    with engine.begin() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :r"),
            {"r": settings.POSTGRES_APP_USER},
        ).scalar()
        if not exists:
            # Role names can't be bound params; the name comes from our own env.
            conn.execute(
                text(
                    f'CREATE ROLE "{settings.POSTGRES_APP_USER}" LOGIN PASSWORD :pw'
                ),
                {"pw": settings.POSTGRES_APP_PASSWORD},
            )
            logger.info("created role %s", settings.POSTGRES_APP_USER)
        else:
            conn.execute(
                text(f'ALTER ROLE "{settings.POSTGRES_APP_USER}" LOGIN PASSWORD :pw'),
                {"pw": settings.POSTGRES_APP_PASSWORD},
            )
            logger.info("role %s exists — password refreshed", settings.POSTGRES_APP_USER)


if __name__ == "__main__":
    main()
```
NOTE: if psycopg rejects a bound param in DDL (`CREATE ROLE ... PASSWORD :pw`), fall back to quoted interpolation via `psycopg.sql` or escape single quotes; verify behavior in Step 6 by running prestart.

`backend/scripts/prestart.sh` — insert between `backend_pre_start.py` and `alembic upgrade head`:

```bash
python app/ensure_app_role.py
```

- [ ] **Step 3: Grants migration M026**

```bash
docker compose exec -T backend alembic revision -m "m026 app role grants"
```
Write `upgrade()` by hand (no autogenerate — grants aren't model-derived):

```python
LEDGERS = ("unitmovement", "partmovement", "costline", "pricechange", "notificationlog")

def upgrade():
    conn = op.get_bind()
    role = os.environ.get("POSTGRES_APP_USER", "")
    if not role:
        return  # role not configured (e.g. CI without env) — grants are a no-op
    exists = conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}
    ).scalar()
    if not exists:
        return
    q = f'"{role}"'
    op.execute(f"GRANT USAGE ON SCHEMA public TO {q}")
    # Broad default for current + future tables…
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO {q}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {q}")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE ON TABLES TO {q}"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT USAGE, SELECT ON SEQUENCES TO {q}"
    )
    # …then claw back mutation on the ledgers (spec §4.6 REVOKE — now real):
    for t in LEDGERS:
        op.execute(f"REVOKE UPDATE, DELETE ON {t} FROM {q}")
    # Hard-deletes exist only on user (admin delete-user flow):
    op.execute(f'GRANT DELETE ON "user" TO {q}')
    # alembic_version stays admin-only (no grant). No DDL, no ownership.
```
`downgrade()`: `REVOKE ALL ON ALL TABLES IN SCHEMA public FROM role` + reverse the default-privileges statements (same guard). Add `import os` at top.

**Survey first:** `grep -n "session.delete\|\.delete(" backend/app/crud.py` — if crud hard-deletes any table besides `user`, add a `GRANT DELETE` line for each such table (list them in the migration with a comment naming the crud function).

- [ ] **Step 4: conftest admin engine** (`backend/tests/conftest.py`):

Add below the existing imports / above the db fixture:

```python
from sqlalchemy import create_engine as _create_engine

# TRUNCATE teardown needs the admin connection: the app role deliberately
# cannot TRUNCATE the append-only ledgers (hardening spec §4.2.3).
admin_engine = _create_engine(str(settings.SQLALCHEMY_ADMIN_DATABASE_URI))
```
and switch ONLY the teardown block of the `db` fixture to use `with Session(admin_engine) as admin_session:` for the table-discovery + TRUNCATE statements (init_db and the yielded session stay on the app engine — the suite must exercise the app role).

- [ ] **Step 5: Compose + env wiring**

`.env` — add (document in the same style as POSTGRES_*):

```
POSTGRES_APP_USER=castranova_app
POSTGRES_APP_PASSWORD=changethis-app
```
`compose.yml` — add to BOTH the `prestart` and `backend` service environment blocks:

```yaml
  - POSTGRES_APP_USER=${POSTGRES_APP_USER}
  - POSTGRES_APP_PASSWORD=${POSTGRES_APP_PASSWORD}
```
(Optional-style, no `?Variable not set` — unset must mean "run as admin", the fallback.) Mirror into `.env.example` if the repo has one (`ls -a | grep env`).

- [ ] **Step 6: Bring the stack up on the new role + run everything**

```bash
docker compose up -d --build backend prestart   # prestart creates role + applies M026
docker compose exec -T backend python -c "from app.core.config import settings; print(settings.SQLALCHEMY_DATABASE_URI)"   # shows castranova_app
bash scripts/test.sh
```
Expected: full suite green **as the app role**. Failures here are grant gaps — fix by adding the specific missing GRANT to M026 (downgrade+upgrade or a fixup before commit; the migration is unreleased) and document each addition with a comment naming the operation that needed it.

- [ ] **Step 7: Write the privilege tests** (extend `backend/tests/crud/test_append_only.py`):

```python
import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine

from app.core.config import settings

requires_app_role = pytest.mark.skipif(
    not settings.POSTGRES_APP_USER, reason="app role not configured"
)


@requires_app_role
@pytest.mark.parametrize(
    "table", ["unitmovement", "partmovement", "costline", "pricechange", "notificationlog"]
)
def test_app_role_cannot_truncate_ledger(table: str) -> None:
    engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))
    with engine.connect() as conn:
        with pytest.raises(sa.exc.ProgrammingError, match="permission denied"):
            conn.execute(sa.text(f"TRUNCATE {table}"))
        conn.rollback()


@requires_app_role
def test_app_role_cannot_disable_triggers_or_ddl() -> None:
    engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))
    with engine.connect() as conn:
        with pytest.raises(sa.exc.ProgrammingError):
            conn.execute(sa.text("ALTER TABLE unitmovement DISABLE TRIGGER ALL"))
        conn.rollback()
        with pytest.raises(sa.exc.ProgrammingError):
            conn.execute(sa.text("DROP TABLE unitmovement"))
        conn.rollback()
```
(The existing `test_update_rejected_on_ledger`/`test_delete_rejected_on_ledger` now double as REVOKE tests when running as the app role — the error may surface as permission-denied instead of the trigger message; loosen their `match=` to accept either, with a comment.)

- [ ] **Step 8:** Run the file + full suite + E2E (`bunx playwright test` — the live backend now runs least-privilege). **Step 9: Commit** — `git commit -m "feat(db): least-privilege castranova_app runtime role; REVOKE now bites on ledgers"`

### Task 2.11: Ship PR 2

- [ ] **Step 1:** Full verification: `bash scripts/test.sh`, FIFO concurrency suite explicitly, full E2E, ruff/mypy/biome, drift probe empty.
- [ ] **Step 2:** **High-risk review gate:** `superpowers:requesting-code-review` + dispatch `ecc:database-reviewer` (grants matrix, M024–M026, FK orphan check, conftest split) + `ecc:security-reviewer` (replay binding, rate limits, role defaults, sanitized 409). Fix Critical/Important.
- [ ] **Step 3:** Ship with `create-pr` (base `dev`). Title: `feat(security): pre-deploy hardening PR 2 — replay binding, rate limits, least-priv DB role`.

---

# PR 3 — E2E test-infra (`feat/hardening-pr3-e2e-infra`)

> Branch from `dev` after PR 2 merges.

### Task 3.1: Per-run DB reset as a Playwright dependency project

**Files:**
- Create: `frontend/tests/global.setup.ts`
- Modify: `frontend/playwright.config.ts` (projects block, lines ~34-44)

- [ ] **Step 1: Write `frontend/tests/global.setup.ts`**

```typescript
import { execSync } from "node:child_process"
import { test as setup } from "@playwright/test"

// Per-run DB reset (hardening spec §5): truncate all app tables, then re-run
// prestart (alembic no-op + init_db reseeds superuser, locations, settings —
// verified: backend/app/core/db.py init_db). Runs BEFORE auth.setup.ts via
// project dependencies. Host-coupled to the compose dev stack by design — this
// suite only ever runs against it (see e2e-shared-dev-db memory notes).
setup("reset dev database", () => {
  if (process.env.E2E_SKIP_DB_RESET === "1") {
    console.log("E2E_SKIP_DB_RESET=1 — skipping DB reset")
    return
  }
  const repoRoot = `${__dirname}/../..`
  const truncate = `
    DO $$ DECLARE names text;
    BEGIN
      SELECT string_agg(quote_ident(tablename), ', ') INTO names
      FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version';
      IF names IS NOT NULL THEN
        EXECUTE 'TRUNCATE TABLE ' || names || ' RESTART IDENTITY CASCADE';
      END IF;
    END $$;`
  execSync(
    `docker compose exec -T db psql -U postgres -d app -v ON_ERROR_STOP=1 -c "${truncate.replace(/\n/g, " ")}"`,
    { cwd: repoRoot, stdio: "inherit" },
  )
  // `run --rm` blocks until prestart finishes (deterministic, no sleeps).
  execSync("docker compose run --rm prestart", { cwd: repoRoot, stdio: "inherit" })
})
```

- [ ] **Step 2: Chain the projects** in `playwright.config.ts`:

```typescript
  projects: [
    { name: 'setup db', testMatch: /global\.setup\.ts/ },
    {
      name: 'setup',
      testMatch: /auth\.setup\.ts/,
      dependencies: ['setup db'],
    },
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        storageState: 'playwright/.auth/user.json',
      },
      dependencies: ['setup'],
    },
  ],
```
(The old `testMatch: /.*\.setup\.ts/` would match BOTH setup files — the split patterns above are required, not cosmetic.)

- [ ] **Step 3: Run** `bunx playwright test --reporter=line` from `frontend/` twice back-to-back. Expected: both runs fully green; product/customer counts in the DB stay flat between runs (`docker compose exec -T db psql -U postgres -d app -tc "SELECT count(*) FROM product;"` returns the same small number after each).
- [ ] **Step 4: Commit** — `git commit -m "test(e2e): per-run DB reset via Playwright dependency project"`

### Task 3.2: De-flake admin.spec "Edit user" (row-scoped assertion)

**Files:** Modify `frontend/tests/admin.spec.ts` (~line 96).

- [ ] **Step 1:** Replace the page-wide assertion:

```typescript
    await expect(page.getByText("User updated successfully")).toBeVisible()
    // Scope to the user's own row — a page-wide getByText flakes once the
    // table paginates (>100 users) or other specs add rows concurrently.
    await expect(
      page.getByRole("row").filter({ hasText: email }).getByText(updatedName),
    ).toBeVisible()
```

- [ ] **Step 2:** `bunx playwright test tests/admin.spec.ts` → green. **Step 3: Commit** — `git commit -m "test(e2e): scope admin edit-user assertion to its row"`

### Task 3.3: Ship PR 3

- [ ] **Step 1:** Full E2E twice (Task 3.1 Step 3 counts if still fresh) + biome clean.
- [ ] **Step 2:** Review gate: `superpowers:requesting-code-review`; plus `ecc:security-reviewer` is NOT needed here (no auth surface) — `ecc:database-reviewer` only if the reset SQL changed during review.
- [ ] **Step 3:** `create-pr` (base `dev`). Title: `test(e2e): per-run DB reset + admin.spec de-flake (pre-deploy hardening PR 3)`.

---

# DoD Verification Sweep (on `dev` after all three PRs merge)

### Task 4.1: Coverage gate

- [ ] **Step 1:** `docker compose exec -T backend pytest --cov=app.crud --cov=app.api.routes --cov-report=term-missing -q`
- [ ] **Step 2:** If either `crud.py` or the routes package is below 80%: list the uncovered lines, write targeted tests for real behavior gaps (NOT line-chasing — uncovered error branches that can genuinely fire get tests; dead code gets reported, not tested). Re-run to ≥80%.
- [ ] **Step 3:** Commit any new tests — `git commit -m "test(dod): close coverage gaps to >=80% on crud + routes"`

### Task 4.2: Invariant + posture checks (each must pass; fix-forward if not)

- [ ] Append-only for real: `docker compose exec -T backend pytest tests/crud/test_append_only.py -q` — including the new app-role TRUNCATE/DDL denials from Task 2.10.
- [ ] Redaction: `docker compose exec -T backend pytest tests/api/test_staff_redaction_lock.py -q`.
- [ ] FIFO concurrency suite green (exact filename per Task 2.2 Step 4).
- [ ] Replay binding + sync-review ownership tests green.
- [ ] Tooling: in `backend/`: `uv run ruff check .` + `uv run mypy app` clean; in `frontend/`: `bunx biome check .` clean.
- [ ] Drift probe: `alembic revision --autogenerate -m probe` → empty (delete probe file).
- [ ] Full E2E green on the reset infra: `bunx playwright test` from `frontend/`.

### Task 4.3: Close the loop

- [ ] **Step 1:** Update `docs/plans/2026-06-04-castranova-pos-implementation.md`: add a "Pre-deploy hardening (done <date>)" note under Part 5 listing the three PRs + DoD results; note the flagged `ACCESS_TOKEN_EXPIRE_MINUTES` decision for 5.4.
- [ ] **Step 2:** Update memory `deferred-security-hardening.md`: mark done — staff redaction lock (FR-015 surfaces verified already-clean + locked), DB role/REVOKE, IntegrityError handler, replay binding + sync-review submitted_by, refresh 7d, role defaults, movement FKs, rate limits (refresh/logout/pricing/sync) — and leave open the 5.4 items (proxy key_func, denylist, migration-locks runbook, access-token expiry decision). Update `e2e-shared-dev-db-pitfalls.md`: the per-run reset retires the reseed/pollution recipes.
- [ ] **Step 3:** Commit docs/memory updates — `git commit -m "docs(hardening): record pre-deploy hardening completion + 5.4 leftovers"`
