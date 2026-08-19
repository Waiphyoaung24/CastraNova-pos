# List Pagination & Picker Completeness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kill the list-truncation defect class — pickers fetch complete (so customer #101+ is selectable and checkout stops being blocked), and every remaining list paginates on the server.

**Architecture:** Two mechanisms, strictly separated. **Pickers** get unpaginated `/options` projections (the shipped `GET /products/options` pattern) and render through a new `<EntityCombobox>` that caps the DOM at 50 rows. **Lists** move to a `{data, count}` envelope (the shipped `AuditPublic` pattern) with a shared `usePagination` + `<PaginationControls>` dropped *under* existing tables — their bespoke markup and mobile-card layouts are not rewritten.

**Tech Stack:** FastAPI + SQLModel + Pydantic v2 (backend), React + TS + TanStack Query/Table + shadcn/ui + cmdk (frontend), `@hey-api/openapi-ts` generated SDK, pytest + Playwright, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-07-12-list-pagination-and-pickers-design.md`

## Global Constraints

- **Base branch:** `dev_wth`, **after** `feat/product-options-pagination` merges. **Stage 0 is a hard gate.**
- **HIGH RISK** per `CLAUDE.md` §5 (role-tiered financial fields). TDD is mandatory. Review must add `ecc:database-reviewer` + `ecc:security-reviewer`.
- **No Alembic migration.** Every change is read-side (response models + queries). If you find yourself writing a migration, stop — you have misread the plan.
- **Never hand-edit `frontend/src/client/`** — regenerate with `bun run generate-client`.
- **Never run tests against the dev `app` DB.** Backend/E2E run in one-off Docker containers against **`app_test`** (recipes below).
- **Naming conventions (already shipped — match them exactly):** model `<Entity>Option`; crud `list_<entity>_options(*, session)`; route `@router.get("/options")` → `read_options`; envelope `<Entity>Public {data: list[...], count: int}`; counter `count_<entity>(...)`.
- **Count invariant:** every `count_*` query MUST apply the **same `WHERE` clause** as its `list_*` query. `count_audit` documents this as deliberate duplication — follow it. A count that ignores a filter advertises pages that render empty.
- **Route ordering:** declare `/options` **before** any `/{id}` route, or FastAPI matches `options` as an id.

### Test recipes (proven — use verbatim)

```bash
# Backend pytest / mypy / ruff — worktree code, isolated app_test DB.
# venv is at /app/.venv and is NOT shadowed by the /app/backend mount.
MSYS_NO_PATHCONV=1 docker run --rm --network castranova-pos_default \
  --env-file <scratch>/test.env \
  -v "<worktree>/backend:/app/backend" -w /app/backend \
  backend:latest python -m pytest tests/... -q
# test.env = running backend container's `printenv` with POSTGRES_DB=app_test

# Frontend tsc / biome / generate-client (bun workspace; anon volume preserves node_modules)
docker run --rm -v "<worktree>:/app" -v /app/node_modules -w /app/frontend \
  frontend:latest bunx tsc --noEmit
```

---

## Parallelisation Map

**File ownership is partitioned so no two concurrent worktrees touch the same file.**

```
STAGE 0  (blocking gate)
   └─ feat/product-options-pagination merges into dev_wth

STAGE 1  ── two worktrees IN PARALLEL (zero shared files) ──
   ├─ BE  feat/list-options-and-envelopes   backend/**  (models.py, crud.py, routes/*)
   └─ UI  feat/list-pagination-primitives   frontend/src/{components/Common,hooks}/**  (NEW files + DataTable)

           ↓ both merge to dev_wth, then SDK regenerated ONCE (Task I1)

STAGE 2  ── six worktrees IN PARALLEL (each owns distinct screens) ──
   ├─ F1  sale.tsx, tickets.tsx                    ← URGENT: unblocks checkout
   ├─ F2  receive.tsx, stock.tsx
   ├─ F3  customers.tsx, suppliers.tsx
   ├─ F4  products.tsx, admin.tsx
   ├─ F5  projects.tsx
   └─ F6  pulls.tsx, PullCreatePanel.tsx, pricing-overrides.tsx
```

**Why Stage 1 is not further split:** `models.py` and `crud.py` are touched by every backend
change. Splitting them across worktrees guarantees merge conflicts. They are one track.

**Why `audit.tsx` appears nowhere:** it is owned by the concurrent ledger-pagination work.
**Do not open it.**

**SDK conflict rule:** if two branches both regenerate `frontend/src/client/*.gen.ts`, do
**not** hand-merge. Take either side, then re-run `bun run generate-client` against the
merged backend. The SDK is generated, never authored.

---

# STAGE 0 — Gate

### Task 0: Wait for the base branch

- [ ] **Step 1: Confirm the merge landed**

```bash
git fetch --all
git log --oneline dev_wth..feat/product-options-pagination | wc -l   # must print 0
git log --oneline -1 dev_wth
```

Expected: `0`. If non-zero, **stop** — the base is not ready. Proceeding from the current
`dev_wth` will conflict across `crud.py`, `models.py`, and five screens.

- [ ] **Step 2: Confirm the prior art is present**

```bash
grep -n "def list_product_options" backend/app/crud.py     # expect a hit
grep -n "class AuditPublic" backend/app/models.py          # expect a hit
ls frontend/src/hooks/useProductOptions.ts                 # expect the file
```

These are the patterns every task below mirrors. Read all three before writing code.

---

# STAGE 1 — Worktree BE: `feat/list-options-and-envelopes`

**Owns:** `backend/**` only. Touches no frontend file.

## Task B1: `GET /customers/options` — the checkout-blocking fix

**Files:**
- Modify: `backend/app/models.py` (add `CustomerOption`)
- Modify: `backend/app/crud.py` (add `list_customer_options`)
- Modify: `backend/app/api/routes/customers.py` (add `read_options`)
- Test: `backend/tests/api/routes/test_customers.py`

**Interfaces:**
- Produces: `CustomerOption {id: uuid.UUID, name: str}`; `crud.list_customer_options(*, session) -> list[CustomerOption]`; `GET /customers/options -> list[CustomerOption]`, auth `get_current_user` (mirrors `read_customers`).

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/api/routes/test_customers.py`:

```python
def test_customer_options_returns_every_row_past_the_paged_default(
    client: TestClient, db: Session, normal_user_token_headers: dict[str, str]
) -> None:
    """The picker must see every customer. The paginated GET /customers/ defaults to
    limit=100, which made customer #101 unselectable and blocked the sale outright."""
    for i in range(150):
        db.add(Customer(name=f"OptCust {i:03d}"))
    db.commit()

    r = client.get(
        f"{settings.API_V1_STR}/customers/options",
        headers=normal_user_token_headers,
    )

    assert r.status_code == 200
    rows = r.json()
    names = [row["name"] for row in rows if row["name"].startswith("OptCust ")]
    assert len(names) == 150, "options must not paginate"
    assert names == sorted(names), "options must be ordered by name"
    assert set(rows[0]) == {"id", "name"}, "projection must be id + name only"
```

- [ ] **Step 2: Run it and watch it fail**

```bash
MSYS_NO_PATHCONV=1 docker run --rm --network castranova-pos_default --env-file <scratch>/test.env \
  -v "<wt>/backend:/app/backend" -w /app/backend backend:latest \
  python -m pytest tests/api/routes/test_customers.py::test_customer_options_returns_every_row_past_the_paged_default -q
```
Expected: **FAIL** — 404 (route does not exist).

- [ ] **Step 3: Add the model**

In `backend/app/models.py`, next to the other Customer schemas:

```python
class CustomerOption(SQLModel):
    """Lightweight customer projection for the sale/tickets/projects pickers. `name`
    is the only field any picker renders. Customer has no is_active flag, so every
    row is returned."""

    id: uuid.UUID
    name: str
```

- [ ] **Step 4: Add the crud function**

In `backend/app/crud.py`, mirroring `list_product_options`:

```python
def list_customer_options(*, session: Session) -> list[CustomerOption]:
    """Every customer as a lightweight {id, name} projection, ordered by name.
    Deliberately unpaginated: the customer pickers must work offline (the list is
    persisted to IndexedDB and FR-007 requires a customer on every sale), so a
    server-side typeahead is not an option — the list has to be on the device."""
    rows = session.exec(
        select(  # type: ignore[call-overload]
            col(Customer.id),
            col(Customer.name),
        ).order_by(col(Customer.name))
    ).all()
    return [CustomerOption(id=r[0], name=r[1]) for r in rows]
```

- [ ] **Step 5: Add the route — BEFORE any `/{customer_id}` route**

In `backend/app/api/routes/customers.py` (import `CustomerOption`):

```python
@router.get(
    "/options",
    response_model=list[CustomerOption],
    dependencies=[Depends(get_current_user)],
)
def read_options(session: SessionDep) -> list[CustomerOption]:
    """Every customer as a lightweight picker projection, ordered by name. Deliberately
    unpaginated: no client parameter can amplify the response, and the pickers must work
    offline (FR-007 requires a customer on every sale)."""
    return crud.list_customer_options(session=session)
```

- [ ] **Step 6: Run the test — expect PASS**, then the full module + mypy + ruff

```bash
... python -m pytest tests/api/routes/test_customers.py -q
... python -m mypy app
... python -m ruff check app tests
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/models.py backend/app/crud.py backend/app/api/routes/customers.py backend/tests/api/routes/test_customers.py
git commit -m "feat(customers): add unpaginated GET /customers/options for pickers

The paginated GET /customers/ defaults to limit=100, so customer #101+ was
unselectable in the sale/tickets pickers — and FR-007 requires a customer on
every sale, so that sale could not be recorded at all."
```

## Task B2: `GET /suppliers/options`

**Files:**
- Modify: `backend/app/models.py`, `backend/app/crud.py`, `backend/app/api/routes/suppliers.py`
- Test: `backend/tests/api/routes/test_suppliers.py`

**Interfaces:**
- Produces: `SupplierOption {id, name}`; `crud.list_supplier_options(*, session) -> list[SupplierOption]`; `GET /suppliers/options`, auth `get_current_user` (mirrors `read_suppliers`).

- [ ] **Step 1: Write the failing test**

```python
def test_supplier_options_returns_every_row_past_the_paged_default(
    client: TestClient, db: Session, normal_user_token_headers: dict[str, str]
) -> None:
    for i in range(150):
        db.add(Supplier(name=f"OptSup {i:03d}"))
    db.commit()

    r = client.get(
        f"{settings.API_V1_STR}/suppliers/options",
        headers=normal_user_token_headers,
    )

    assert r.status_code == 200
    rows = r.json()
    names = [row["name"] for row in rows if row["name"].startswith("OptSup ")]
    assert len(names) == 150
    assert names == sorted(names)
    assert set(rows[0]) == {"id", "name"}
```

- [ ] **Step 2: Run it — expect FAIL (404)**

- [ ] **Step 3: Model**

```python
class SupplierOption(SQLModel):
    """Lightweight supplier projection for the receive/stock pickers. Supplier has no
    is_active flag, so every row is returned."""

    id: uuid.UUID
    name: str
```

- [ ] **Step 4: Crud**

```python
def list_supplier_options(*, session: Session) -> list[SupplierOption]:
    """Every supplier as a lightweight {id, name} projection, ordered by name.
    Deliberately unpaginated — the receive and stock-filter pickers must be able to
    reach every supplier."""
    rows = session.exec(
        select(  # type: ignore[call-overload]
            col(Supplier.id),
            col(Supplier.name),
        ).order_by(col(Supplier.name))
    ).all()
    return [SupplierOption(id=r[0], name=r[1]) for r in rows]
```

- [ ] **Step 5: Route (before any `/{supplier_id}` route)**

```python
@router.get(
    "/options",
    response_model=list[SupplierOption],
    dependencies=[Depends(get_current_user)],
)
def read_options(session: SessionDep) -> list[SupplierOption]:
    """Every supplier as a lightweight picker projection, ordered by name.
    Deliberately unpaginated (receive tabs + stock supplier filter)."""
    return crud.list_supplier_options(session=session)
```

- [ ] **Step 6: pytest + mypy + ruff — expect PASS**
- [ ] **Step 7: Commit** — `feat(suppliers): add unpaginated GET /suppliers/options for pickers`

## Task B3: `GET /projects/options` — ACTIVE only, admin

**Files:**
- Modify: `backend/app/models.py`, `backend/app/crud.py`, `backend/app/api/routes/projects.py`
- Test: `backend/tests/api/routes/test_projects.py`

**Interfaces:**
- Produces: `ProjectOption {id, code, name}`; `crud.list_project_options(*, session) -> list[ProjectOption]`; `GET /projects/options`, auth **`get_admin`** (mirrors `read_projects`, which is admin-only).

**Behavior change:** CLOSED projects are excluded — a closed project must not accept a new
pull. Recorded in `notes.md` for owner confirmation.

- [ ] **Step 1: Write the failing test**

```python
def test_project_options_excludes_closed_and_returns_every_active_row(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """Picker must see every ACTIVE project (not just the first 100) and must NOT
    offer a CLOSED one — you cannot pull against a closed project."""
    customer = Customer(name="OptProj Customer")
    db.add(customer)
    db.commit()
    db.refresh(customer)

    for i in range(150):
        db.add(
            Project(
                code=f"OPTP-{i:03d}",
                name=f"Open {i:03d}",
                customer_id=customer.id,
                status=ProjectStatus.ACTIVE,
            )
        )
    db.add(
        Project(
            code="OPTP-CLOSED",
            name="Closed one",
            customer_id=customer.id,
            status=ProjectStatus.CLOSED,
        )
    )
    db.commit()

    r = client.get(
        f"{settings.API_V1_STR}/projects/options", headers=superuser_token_headers
    )

    assert r.status_code == 200
    rows = r.json()
    codes = [row["code"] for row in rows if row["code"].startswith("OPTP-")]
    assert len(codes) == 150, "every ACTIVE project must be returned, unpaginated"
    assert "OPTP-CLOSED" not in codes, "CLOSED projects must not be selectable"
    assert codes == sorted(codes)
    assert set(rows[0]) == {"id", "code", "name"}


def test_project_options_is_admin_only(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    """Mirrors read_projects, which is admin-gated."""
    r = client.get(
        f"{settings.API_V1_STR}/projects/options", headers=normal_user_token_headers
    )
    assert r.status_code == 403
```

- [ ] **Step 2: Run — expect FAIL (404)**

- [ ] **Step 3: Model**

```python
class ProjectOption(SQLModel):
    """Lightweight project projection for the pull-create picker. Only ACTIVE projects
    are returned (see crud.list_project_options)."""

    id: uuid.UUID
    code: str
    name: str
```

- [ ] **Step 4: Crud — the ACTIVE filter**

```python
def list_project_options(*, session: Session) -> list[ProjectOption]:
    """Every ACTIVE project as {id, code, name}, ordered by code. CLOSED projects are
    excluded: a closed project must not accept a new pull. The projects table still
    lists every project, so an admin can still see and reopen a closed one."""
    rows = session.exec(
        select(  # type: ignore[call-overload]
            col(Project.id),
            col(Project.code),
            col(Project.name),
        )
        .where(Project.status == ProjectStatus.ACTIVE)
        .order_by(col(Project.code))
    ).all()
    return [ProjectOption(id=r[0], code=r[1], name=r[2]) for r in rows]
```

- [ ] **Step 5: Route (before any `/{project_id}` route)**

```python
@router.get(
    "/options",
    response_model=list[ProjectOption],
    dependencies=[Depends(get_admin)],
)
def read_options(session: SessionDep) -> list[ProjectOption]:
    """Every ACTIVE project as a lightweight picker projection, ordered by code.
    Deliberately unpaginated. Admin-only, mirroring GET /projects/."""
    return crud.list_project_options(session=session)
```

- [ ] **Step 6: pytest + mypy + ruff — expect PASS**
- [ ] **Step 7: Commit** — `feat(projects): add admin GET /projects/options (ACTIVE only)`

## Task B4: `active_only` on the existing `/products/options`

**Files:**
- Modify: `backend/app/crud.py` (`list_product_options`), `backend/app/api/routes/products.py` (`read_options`)
- Test: `backend/tests/api/routes/test_products.py`

**Interfaces:**
- Produces: `crud.list_product_options(*, session, active_only: bool = False) -> list[ProductOption]`; `GET /products/options?active_only=<bool>` (**default `false`**).

**Why a param and not a `WHERE`:** the **audit SKU combobox shares this endpoint**, and
`list_product_options`' own docstring says it must include inactive products, "whose
historical movements still appear in the append-only ledgers." An unconditional filter would
make a discontinued product's SKU unfilterable in the ledger. So the filter is **opt-in**:
pickers pass `active_only=true`; the audit filter keeps the default `false`.

- [ ] **Step 1: Write the failing test**

```python
def test_product_options_active_only_filters_inactive(
    client: TestClient, db: Session, normal_user_token_headers: dict[str, str]
) -> None:
    """active_only=true hides discontinued products from the pickers; the default
    (false) keeps them, because the audit SKU filter must still reach a discontinued
    SKU's historical movements."""
    db.add(Product(sku="OPT-ACTIVE", model_name="Active", tracking_mode=TrackingMode.QUANTITY,
                   retail_price_thb=Decimal("10.00"), repair_price_thb=Decimal("5.00"),
                   is_active=True))
    db.add(Product(sku="OPT-DEAD", model_name="Discontinued", tracking_mode=TrackingMode.QUANTITY,
                   retail_price_thb=Decimal("10.00"), repair_price_thb=Decimal("5.00"),
                   is_active=False))
    db.commit()

    default = client.get(
        f"{settings.API_V1_STR}/products/options", headers=normal_user_token_headers
    ).json()
    default_skus = {p["sku"] for p in default}
    assert "OPT-DEAD" in default_skus, "default must keep inactive (audit SKU filter)"

    active = client.get(
        f"{settings.API_V1_STR}/products/options?active_only=true",
        headers=normal_user_token_headers,
    ).json()
    active_skus = {p["sku"] for p in active}
    assert "OPT-ACTIVE" in active_skus
    assert "OPT-DEAD" not in active_skus, "pickers must not offer a discontinued product"


def test_product_options_never_leaks_purchase_cost(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    """Role-tiering: staff may see SELLING prices (they transact at them) but cost is
    'completely hidden, not just visually masked' — the key must be ABSENT, not null."""
    rows = client.get(
        f"{settings.API_V1_STR}/products/options", headers=normal_user_token_headers
    ).json()
    assert rows, "seed catalog expected"
    for row in rows:
        assert "purchase_cost_thb" not in row
        assert "latest_purchase_cost_thb" not in row
        assert "cogs" not in row
    assert set(rows[0]) == {
        "id", "sku", "model_name", "tracking_mode",
        "retail_price_thb", "repair_price_thb",
    }
```

- [ ] **Step 2: Run — expect FAIL** (`active_only` is not a param; the filter test fails)

- [ ] **Step 3: Add the param to crud, and CORRECT the docstring**

The existing docstring asserts it "includes inactive products" unconditionally — that is no
longer the whole truth. Replace `list_product_options` with:

```python
def list_product_options(
    *, session: Session, active_only: bool = False
) -> list[ProductOption]:
    """Every product as a lightweight {id, sku, model_name, tracking_mode, prices}
    projection, ordered by SKU. Unpaginated single round-trip for pickers/lookups
    across the app.

    `active_only=True` drops discontinued products — what the sale/receive/tickets/
    pulls pickers want. The DEFAULT is False, because the audit SKU filter shares this
    endpoint and must still reach an inactive product's SKU: its historical movements
    remain in the append-only ledgers forever."""
    statement = select(  # type: ignore[call-overload]
        col(Product.id),
        col(Product.sku),
        col(Product.model_name),
        col(Product.tracking_mode),
        col(Product.retail_price_thb),
        col(Product.repair_price_thb),
    )
    if active_only:
        statement = statement.where(Product.is_active)
    rows = session.exec(statement.order_by(col(Product.sku))).all()
    return [
        ProductOption(
            id=r[0],
            sku=r[1],
            model_name=r[2],
            tracking_mode=r[3],
            retail_price_thb=r[4],
            repair_price_thb=r[5],
        )
        for r in rows
    ]
```

> Keep the existing `ProductOption(...)` construction exactly as the merged code has it —
> only the statement building and signature change.

- [ ] **Step 4: Thread the param through the route**

```python
@router.get(
    "/options",
    response_model=list[ProductOption],
    dependencies=[Depends(get_current_user)],
)
def read_options(
    session: SessionDep,
    active_only: bool = False,
) -> list[ProductOption]:
    """Every product as a lightweight picker/lookup projection, ordered by SKU.
    Deliberately unpaginated. `active_only=true` hides discontinued products (what the
    pickers want); the default keeps them, because the audit SKU filter must still be
    able to select a discontinued SKU whose movements remain in the ledger."""
    return crud.list_product_options(session=session, active_only=active_only)
```

- [ ] **Step 5: pytest + mypy + ruff — expect PASS**
- [ ] **Step 6: Commit** — `feat(products): add active_only to GET /products/options`

## Task B5: `{data, count}` envelopes for the four unfiltered lists

**Files:**
- Modify: `backend/app/models.py` (4 envelopes), `backend/app/crud.py` (4 counters), `backend/app/api/routes/{products,customers,suppliers,projects}.py`
- Test: `backend/tests/api/routes/test_{products,customers,suppliers,projects}.py`

**Interfaces:**
- Produces: `ProductsPublic`, `CustomersPublic`, `SuppliersPublic`, `ProjectsPublic` — each `{data: list[<Entity>Public], count: int}`; `crud.count_products/count_customers/count_suppliers/count_projects(*, session) -> int`. The four list routes now return the envelope.

These four take **no filters**, so their counts are plain totals (like `count_users`). The
filtered ones are Tasks B6/B7 — do not conflate them.

- [ ] **Step 1: Write one failing test per entity** (shown for customers; repeat verbatim for products/suppliers/projects, changing only the model, factory and route)

```python
def test_customers_list_returns_envelope_with_true_total(
    client: TestClient, db: Session, normal_user_token_headers: dict[str, str]
) -> None:
    """The table pages server-side, so it needs the true total — not the page length."""
    for i in range(120):
        db.add(Customer(name=f"EnvCust {i:03d}"))
    db.commit()

    r = client.get(
        f"{settings.API_V1_STR}/customers/?skip=0&limit=25",
        headers=normal_user_token_headers,
    )

    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"data", "count"}
    assert len(body["data"]) == 25, "page size honoured"
    assert body["count"] >= 120, "count is the TOTAL, not the page length"
    assert body["count"] != len(body["data"])


def test_customers_pages_are_disjoint_and_end_cleanly(
    client: TestClient, db: Session, normal_user_token_headers: dict[str, str]
) -> None:
    for i in range(30):
        db.add(Customer(name=f"PageCust {i:03d}"))
    db.commit()

    p1 = client.get(f"{settings.API_V1_STR}/customers/?skip=0&limit=10",
                    headers=normal_user_token_headers).json()
    p2 = client.get(f"{settings.API_V1_STR}/customers/?skip=10&limit=10",
                    headers=normal_user_token_headers).json()
    assert {c["id"] for c in p1["data"]}.isdisjoint({c["id"] for c in p2["data"]})

    past_end = client.get(f"{settings.API_V1_STR}/customers/?skip=10000&limit=10",
                          headers=normal_user_token_headers).json()
    assert past_end["data"] == [], "a page past the end is empty..."
    assert past_end["count"] == p1["count"], "...but the count stays truthful"
```

- [ ] **Step 2: Run all four — expect FAIL** (response is a bare list; `set(body)` raises / assert fails)

- [ ] **Step 3: Add the envelopes** to `models.py`, mirroring `AuditPublic`:

```python
class ProductsPublic(SQLModel):
    data: list[ProductPublic]
    count: int


class CustomersPublic(SQLModel):
    data: list[CustomerPublic]
    count: int


class SuppliersPublic(SQLModel):
    data: list[SupplierPublic]
    count: int


class ProjectsPublic(SQLModel):
    data: list[ProjectPublic]
    count: int
```

- [ ] **Step 4: Add the counters** to `crud.py` (one per entity; these lists take no filters, so the count is a plain total):

```python
def count_customers(*, session: Session) -> int:
    """Total customer rows for the pagination envelope. list_customers applies no
    filter, so neither does this — see count_audit for the filtered pattern."""
    return session.exec(select(func.count()).select_from(Customer)).one()


def count_suppliers(*, session: Session) -> int:
    """Total supplier rows for the pagination envelope (list_suppliers is unfiltered)."""
    return session.exec(select(func.count()).select_from(Supplier)).one()


def count_products(*, session: Session) -> int:
    """Total product rows for the pagination envelope (list_products is unfiltered)."""
    return session.exec(select(func.count()).select_from(Product)).one()


def count_projects(*, session: Session) -> int:
    """Total project rows for the pagination envelope (list_projects is unfiltered —
    the table shows CLOSED projects too; only the /options picker filters them)."""
    return session.exec(select(func.count()).select_from(Project)).one()
```

- [ ] **Step 5: Switch the four routes to the envelope** (shown for customers; repeat for the others)

```python
@router.get(
    "/",
    response_model=CustomersPublic,
    dependencies=[Depends(get_current_user)],
)
def read_customers(
    session: SessionDep,
    skip: Annotated[int, Query(ge=0, le=10_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> CustomersPublic:
    return CustomersPublic(
        data=crud.list_customers(session=session, skip=skip, limit=limit),  # type: ignore[arg-type]
        count=crud.count_customers(session=session),
    )
```

- [ ] **Step 6: Run the whole backend suite** — other tests assert a bare list and will now
fail. Update each to read `body["data"]`. This is expected churn, not a regression.

```bash
... python -m pytest tests -q
... python -m mypy app && python -m ruff check app tests
```

- [ ] **Step 7: Commit** — `feat(api): {data,count} envelope for product/customer/supplier/project lists`

## Task B6: `{data, count}` for pricing-overrides — **filtered count**

**Files:**
- Modify: `backend/app/models.py`, `backend/app/crud.py`, `backend/app/api/routes/pricing_overrides.py`
- Test: `backend/tests/api/routes/test_pricing_override.py`

**Interfaces:**
- Produces: `PricingOverridesPublic {data, count}`; `crud.count_pricing_overrides(*, session, state: OverrideState | None = None) -> int`.

**This is where the count invariant bites.** The route filters by `state`. A count that
ignores `state` would report every override while the page shows only PENDING ones — the
pager would offer pages that render empty.

- [ ] **Step 1: Write the failing invariant test**

**Before writing this test:** open `test_pricing_override.py` and find how it already creates
an override (there is an existing helper / fixture — the module has 13 passing tests). Reuse
it; do not invent a new factory. Seed **3 `PENDING`** and **7 `APPROVED`** rows, then:

```python
def test_pricing_override_count_honours_the_state_filter(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """THE invariant: count must apply the SAME WHERE clause as data. A count that
    ignored `state` would report 10 while the page showed 3 — so the pager would offer
    pages that render empty."""
    # Seed via this module's existing override-creation helper:
    #   3 rows with state=OverrideState.PENDING
    #   7 rows with state=OverrideState.APPROVED
    # (Deviations above the threshold land as PENDING; within it, AUTO_APPROVED — so set
    #  `state` explicitly on the row rather than relying on the threshold logic.)

    r = client.get(
        f"{settings.API_V1_STR}/pricing-overrides?state=PENDING&skip=0&limit=100",
        headers=superuser_token_headers,
    )

    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"data", "count"}
    assert all(o["state"] == "PENDING" for o in body["data"])
    assert body["count"] == 3, (
        "count must be the FILTERED total (3 PENDING), not the table total (10)"
    )
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Model**

```python
class PricingOverridesPublic(SQLModel):
    data: list[PricingOverridePublic]
    count: int
```

- [ ] **Step 4: Counter — mirror `list_pricing_overrides`' WHERE construction exactly**

```python
def count_pricing_overrides(
    *, session: Session, state: OverrideState | None = None
) -> int:
    """Total rows for the same filter set as list_pricing_overrides, for the pagination
    envelope. Mirrors its WHERE-clause construction exactly, so the count and the page
    it describes can never disagree about what "matches" (see count_audit)."""
    statement = select(func.count()).select_from(PricingOverrideRequest)
    if state is not None:
        statement = statement.where(PricingOverrideRequest.state == state)
    return session.exec(statement).one()
```

> Read `list_pricing_overrides` and confirm this `if state is not None` branch matches it
> **clause for clause**. If it has any other filter, mirror that too.

- [ ] **Step 5: Route returns the envelope**

```python
@router.get(
    "",
    response_model=PricingOverridesPublic,
    dependencies=[Depends(get_admin)],
)
def list_pricing_overrides(
    *,
    session: SessionDep,
    state: OverrideState | None = None,
    skip: Annotated[int, Query(ge=0, le=10_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> PricingOverridesPublic:
    return PricingOverridesPublic(
        data=crud.list_pricing_overrides(
            session=session, state=state, skip=skip, limit=limit
        ),
        count=crud.count_pricing_overrides(session=session, state=state),
    )
```

- [ ] **Step 6: pytest + mypy + ruff — expect PASS**
- [ ] **Step 7: Commit** — `feat(pricing-overrides): {data,count} envelope with a state-honouring count`

## Task B7: `{data, count}` for project-pulls — **filtered count**

Identical shape to B6, for `ProjectPullState`.

**Files:** `backend/app/models.py`, `backend/app/crud.py`, `backend/app/api/routes/project_pulls.py`; test `backend/tests/api/routes/test_project_pulls.py`

**Interfaces:** `ProjectPullsPublic {data, count}`; `crud.count_project_pulls(*, session, state: ProjectPullState | None = None) -> int`.

- [ ] **Step 1: Failing invariant test**

```python
def test_project_pull_count_honours_the_state_filter(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """count must apply the SAME WHERE clause as data (see count_audit)."""
    # ... seed 2 PENDING and 5 FULFILLED pulls via this module's existing helper

    body = client.get(
        f"{settings.API_V1_STR}/project-pulls?state=PENDING&skip=0&limit=100",
        headers=superuser_token_headers,
    ).json()

    assert set(body) == {"data", "count"}
    assert all(p["state"] == "PENDING" for p in body["data"])
    assert body["count"] == 2, "filtered total, not the table total (7)"
```

- [ ] **Step 2: Run — expect FAIL**
- [ ] **Step 3: Model**

```python
class ProjectPullsPublic(SQLModel):
    data: list[ProjectPullPublic]
    count: int
```

- [ ] **Step 4: Counter**

```python
def count_project_pulls(
    *, session: Session, state: ProjectPullState | None = None
) -> int:
    """Total rows for the same filter set as list_project_pulls, for the pagination
    envelope. Mirrors its WHERE-clause construction exactly (see count_audit)."""
    statement = select(func.count()).select_from(ProjectPull)
    if state is not None:
        statement = statement.where(ProjectPull.state == state)
    return session.exec(statement).one()
```

- [ ] **Step 5: Route returns `ProjectPullsPublic`** (same shape as B6, auth stays `get_current_user`)
- [ ] **Step 6: pytest + mypy + ruff — expect PASS**
- [ ] **Step 7: Commit** — `feat(project-pulls): {data,count} envelope with a state-honouring count`

## Task B8: Denormalize `product_sku` onto override + pull-line rows

**Files:**
- Modify: `backend/app/models.py` (`PricingOverridePublic`, `ProjectPullLinePublic`), `backend/app/crud.py` (the two builders)
- Test: `backend/tests/api/routes/test_pricing_override.py`, `backend/tests/api/routes/test_project_pulls.py`

**Interfaces:**
- Produces: `PricingOverridePublic.product_sku: str`; `ProjectPullLinePublic.product_sku: str` and `.model_name: str`.

**Why:** both rows carry only `product_id`, which is why the frontend builds `productLabels`
(id→sku) and `productNames` (id→model_name) from the products list. With an **active-only**
picker, those maps lose entries for deactivated products, so **historical override rows and
existing pull lines would render blank labels.** Denormalizing makes the rows
self-describing and **deletes both label maps outright**.

- [ ] **Step 1: Write the failing test — the deactivated-product case is the point**

```python
def test_override_row_carries_sku_even_for_a_deactivated_product(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """The row must describe itself. The frontend's id->sku map is built from the
    active-only picker, so a since-deactivated product would otherwise render a blank
    label on its own historical override."""
    product = Product(
        sku="DENORM-DEAD",
        model_name="Discontinued",
        tracking_mode=TrackingMode.QUANTITY,
        retail_price_thb=Decimal("100.00"),
        repair_price_thb=Decimal("50.00"),
        is_active=True,
    )
    db.add(product)
    db.commit()
    db.refresh(product)

    # Create an override against it using this module's existing helper, then retire
    # the product — exactly the sequence that blanks the label today.
    # ... create_override(product_id=product.id, ...)

    product.is_active = False
    db.add(product)
    db.commit()

    body = client.get(
        f"{settings.API_V1_STR}/pricing-overrides?limit=100",
        headers=superuser_token_headers,
    ).json()

    row = next(o for o in body["data"] if o["product_id"] == str(product.id))
    assert row["product_sku"] == "DENORM-DEAD", (
        "the row must carry its own sku — the picker no longer supplies one"
    )
```

- [ ] **Step 2: Run — expect FAIL** (`KeyError: 'product_sku'`)

- [ ] **Step 3: Add the fields**

```python
class PricingOverridePublic(SQLModel):
    id: uuid.UUID
    target_kind: OverrideTargetKind
    product_id: uuid.UUID
    product_sku: str  # denormalized so the row is self-describing (see crud)
    ...
```

```python
class ProjectPullLinePublic(SQLModel):
    id: uuid.UUID
    line_kind: SaleLineKind
    product_id: uuid.UUID
    product_sku: str  # denormalized — see crud.list_project_pull_lines
    model_name: str
    ...
```

- [ ] **Step 4: Populate them in the crud builders** — join `Product` in
`list_pricing_overrides` and `list_project_pull_lines`. Add a docstring line to each:

```python
    """... Carries the product's sku (and model_name) denormalized, so a row remains
    readable after its product is deactivated — the frontend's picker is active-only,
    so an id->label map built from it would blank out exactly these historical rows."""
```

- [ ] **Step 5: Full backend suite + mypy + ruff — expect PASS**
- [ ] **Step 6: Commit** — `feat(api): denormalize product_sku onto override and pull-line rows`

---

# STAGE 1 — Worktree UI: `feat/list-pagination-primitives`

**Owns:** `frontend/src/hooks/usePagination.ts`, `frontend/src/components/Common/PaginationControls.tsx`, `frontend/src/components/Common/EntityCombobox.tsx`, `frontend/src/components/Common/DataTable.tsx`. **Touches no backend file and no route screen** — fully parallel with Worktree BE.

## Task U1: `usePagination` hook

**Files:** Create `frontend/src/hooks/usePagination.ts`

**Interfaces:**
- Produces: `usePagination(opts?: {pageSize?: number}) -> {page: number, pageSize: number, skip: number, limit: number, setPage: (p: number) => void, reset: () => void, pageCount: (total: number) => number}`

- [ ] **Step 1: Write the hook**

```ts
import { useCallback, useState } from "react"

const DEFAULT_PAGE_SIZE = 25

/**
 * Page state for a server-paginated list. Converts a 1-based page number into the
 * `skip`/`limit` the API expects.
 *
 * Callers MUST pass `skip`/`limit` into the queryFn AND include `page` in the
 * queryKey — otherwise TanStack serves the cached first page forever and the pager
 * silently does nothing (which is exactly the bug this replaces on admin.tsx).
 */
export function usePagination({ pageSize = DEFAULT_PAGE_SIZE } = {}) {
  const [page, setPageRaw] = useState(1)

  const setPage = useCallback((p: number) => setPageRaw(Math.max(1, p)), [])
  const reset = useCallback(() => setPageRaw(1), [])

  // Rows can be deleted while we're on a late page; clamp so we never strand the
  // user on an empty page with no way back.
  const pageCount = useCallback(
    (total: number) => Math.max(1, Math.ceil(total / pageSize)),
    [pageSize],
  )

  return {
    page,
    pageSize,
    skip: (page - 1) * pageSize,
    limit: pageSize,
    setPage,
    reset,
    pageCount,
  }
}
```

- [ ] **Step 2: Typecheck**

```bash
docker run --rm -v "<wt>:/app" -v /app/node_modules -w /app/frontend frontend:latest bunx tsc --noEmit
```
Expected: clean.

- [ ] **Step 3: Commit** — `feat(frontend): add usePagination hook for server-paginated lists`

## Task U2: `<PaginationControls>`

**Files:** Create `frontend/src/components/Common/PaginationControls.tsx`

**Interfaces:**
- Consumes: `components/ui/pagination.tsx` (already present, currently unused).
- Produces: `<PaginationControls total pageSize page onPageChange />`

- [ ] **Step 1: Write the component**

```tsx
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination"

interface PaginationControlsProps {
  /** TRUE total from the API envelope's `count` — never `data.length`. */
  total: number
  pageSize: number
  /** 1-based. */
  page: number
  onPageChange: (page: number) => void
}

/**
 * Server-side pager. Sits UNDER an existing table; it does not own or wrap the table,
 * so each screen keeps its own markup and mobile-card layout.
 *
 * `total` is the API's `count`, not the row count of the current page. Paging over
 * `data.length` is precisely the lie admin.tsx used to tell.
 */
export function PaginationControls({
  total,
  pageSize,
  page,
  onPageChange,
}: PaginationControlsProps) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  if (pageCount <= 1) return null

  const first = (page - 1) * pageSize + 1
  const last = Math.min(page * pageSize, total)

  return (
    <div className="flex flex-col sm:flex-row items-center justify-between gap-3 pt-4">
      <p className="text-sm text-muted-foreground">
        Showing <span className="font-medium text-foreground">{first}</span>–
        <span className="font-medium text-foreground">{last}</span> of{" "}
        <span className="font-medium text-foreground">{total}</span>
      </p>

      <Pagination className="mx-0 w-auto justify-end">
        <PaginationContent>
          <PaginationItem>
            <PaginationPrevious
              aria-disabled={page <= 1}
              className={page <= 1 ? "pointer-events-none opacity-50" : undefined}
              onClick={(e) => {
                e.preventDefault()
                onPageChange(page - 1)
              }}
            />
          </PaginationItem>
          <PaginationItem>
            <span className="px-3 text-sm text-muted-foreground">
              Page {page} of {pageCount}
            </span>
          </PaginationItem>
          <PaginationItem>
            <PaginationNext
              aria-disabled={page >= pageCount}
              className={
                page >= pageCount ? "pointer-events-none opacity-50" : undefined
              }
              onClick={(e) => {
                e.preventDefault()
                onPageChange(page + 1)
              }}
            />
          </PaginationItem>
        </PaginationContent>
      </Pagination>
    </div>
  )
}
```

- [ ] **Step 2: `bunx tsc --noEmit`** — expect clean
- [ ] **Step 3: Commit** — `feat(frontend): add PaginationControls on the ui/pagination primitive`

## Task U3: `<EntityCombobox>` — search + hard render cap

**Files:** Create `frontend/src/components/Common/EntityCombobox.tsx`

**Interfaces:**
- Produces:
  ```ts
  <EntityCombobox<T>
    items={T[]}
    value={string | undefined}
    onChange={(id: string | undefined) => void}
    getKey={(item: T) => string}
    getLabel={(item: T) => string}
    placeholder?: string
    searchPlaceholder?: string
    emptyText?: string
    allowClear?: boolean
    ariaLabel?: string
    disabled?: boolean
  />
  ```

**The whole point of this component.** cmdk **mounts every `CommandItem`** and merely hides
non-matching ones, so a plain `Command` over 5,000 customers puts 5,000 nodes in the DOM on
open — search does not help. There is **no virtualization anywhere in this app**. So we set
`shouldFilter={false}`, run our **own** filter, and **slice to `VISIBLE_LIMIT`** before
rendering. Autocomplete gives findability; the cap gives DOM safety. Both are required.

- [ ] **Step 1: Write the component**

```tsx
import { Check, ChevronsUpDown } from "lucide-react"
import { useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { cn } from "@/lib/utils"

/**
 * How many options we are willing to put in the DOM at once.
 *
 * cmdk MOUNTS every CommandItem and only hides non-matching ones, so its built-in
 * filter does NOT bound the DOM — with thousands of customers a plain <Command> would
 * mount thousands of nodes on open and jank a warehouse tablet. We therefore disable
 * cmdk's filter (`shouldFilter={false}`), filter ourselves, and slice to this cap.
 */
const VISIBLE_LIMIT = 50

interface EntityComboboxProps<T> {
  items: T[]
  value: string | undefined
  onChange: (id: string | undefined) => void
  getKey: (item: T) => string
  getLabel: (item: T) => string
  placeholder?: string
  searchPlaceholder?: string
  emptyText?: string
  allowClear?: boolean
  ariaLabel?: string
  disabled?: boolean
}

export function EntityCombobox<T>({
  items,
  value,
  onChange,
  getKey,
  getLabel,
  placeholder = "Select…",
  searchPlaceholder = "Search…",
  emptyText = "No match found.",
  allowClear = false,
  ariaLabel,
  disabled = false,
}: EntityComboboxProps<T>) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const [shown, setShown] = useState(VISIBLE_LIMIT)

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return items
    return items.filter((item) => getLabel(item).toLowerCase().includes(q))
  }, [items, query, getLabel])

  const visible = matches.slice(0, shown)
  const hidden = matches.length - visible.length

  const selectedLabel = useMemo(() => {
    if (!value) return undefined
    const hit = items.find((item) => getKey(item) === value)
    return hit ? getLabel(hit) : undefined
  }, [items, value, getKey, getLabel])

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) {
          setQuery("")
          setShown(VISIBLE_LIMIT)
        }
      }}
    >
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-label={ariaLabel}
          aria-expanded={open}
          disabled={disabled}
          className="w-full justify-between font-normal"
        >
          <span className={cn(!selectedLabel && "text-muted-foreground", "truncate")}>
            {selectedLabel ?? placeholder}
          </span>
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>

      <PopoverContent
        className="w-(--radix-popover-trigger-width) p-0"
        align="start"
      >
        {/* shouldFilter={false}: we filter + slice ourselves so the DOM stays bounded. */}
        <Command shouldFilter={false}>
          <CommandInput
            placeholder={searchPlaceholder}
            value={query}
            onValueChange={(q) => {
              setQuery(q)
              setShown(VISIBLE_LIMIT)
            }}
          />
          <CommandList>
            <CommandEmpty>{emptyText}</CommandEmpty>
            <CommandGroup>
              {allowClear && (
                <CommandItem
                  value="__clear__"
                  onSelect={() => {
                    onChange(undefined)
                    setOpen(false)
                  }}
                >
                  <Check
                    className={cn(
                      "mr-2 h-4 w-4",
                      value ? "opacity-0" : "opacity-100",
                    )}
                  />
                  <span className="text-muted-foreground">All</span>
                </CommandItem>
              )}

              {visible.map((item) => {
                const key = getKey(item)
                return (
                  <CommandItem
                    key={key}
                    value={key}
                    onSelect={() => {
                      onChange(key)
                      setOpen(false)
                    }}
                  >
                    <Check
                      className={cn(
                        "mr-2 h-4 w-4",
                        value === key ? "opacity-100" : "opacity-0",
                      )}
                    />
                    <span className="truncate">{getLabel(item)}</span>
                  </CommandItem>
                )
              })}
            </CommandGroup>
          </CommandList>

          {hidden > 0 && (
            <div className="flex items-center justify-between gap-2 border-t px-3 py-2">
              <span className="text-xs text-muted-foreground">
                Showing {visible.length} of {matches.length}
              </span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 text-xs"
                onClick={() => setShown((n) => n + VISIBLE_LIMIT)}
              >
                Show {Math.min(VISIBLE_LIMIT, hidden)} more
              </Button>
            </div>
          )}
        </Command>
      </PopoverContent>
    </Popover>
  )
}
```

- [ ] **Step 2: `bunx tsc --noEmit`** — expect clean
- [ ] **Step 3: Commit** — `feat(frontend): add EntityCombobox with search and a 50-row DOM cap`

## Task U4: Give `DataTable` real (manual) pagination

**Files:** Modify `frontend/src/components/Common/DataTable.tsx`

**Interfaces:**
- Produces: `DataTable` accepts optional
  `manualPagination?: {pageCount: number, pageIndex: number, pageSize: number, total: number, onPageChange: (pageIndex: number) => void}`.
  When omitted, behaviour is unchanged (client-side paging) so no existing caller breaks.

**Why:** `admin.tsx` renders `DataTable` over a hard-coded 100-row fetch. Its pager uses
`getPaginationRowModel()` (client-side) and so **walks only rows already in memory** — it
shows page buttons that can never reach user #101. Wiring TanStack's `manualPagination` makes
the buttons re-query.

**`total` is passed in, never derived.** Reconstructing it as `pageCount * data.length`
over-reports on the last page (a half-full final page would inflate the total). The caller
already has the true `count` from the API envelope — pass it.

- [ ] **Step 1: Add the opt-in manual mode**

```tsx
interface DataTableProps<TData, TValue> {
  columns: ColumnDef<TData, TValue>[]
  data: TData[]
  /**
   * Server-side paging. When provided, TanStack stops slicing `data` itself — `data` is
   * then exactly ONE page — and the pager re-queries instead. `pageCount` and `total`
   * both come from the API envelope's `count`. Omit for the legacy client-side paging.
   */
  manualPagination?: {
    pageCount: number
    pageIndex: number
    pageSize: number
    total: number
    onPageChange: (pageIndex: number) => void
  }
}

export function DataTable<TData, TValue>({
  columns,
  data,
  manualPagination,
}: DataTableProps<TData, TValue>) {
  const mp = manualPagination
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    // In manual mode `data` IS the page — slicing it again would paginate the page.
    ...(mp
      ? {
          manualPagination: true as const,
          pageCount: mp.pageCount,
          state: {
            pagination: { pageIndex: mp.pageIndex, pageSize: mp.pageSize },
          },
          onPaginationChange: (updater: unknown) => {
            const prev = { pageIndex: mp.pageIndex, pageSize: mp.pageSize }
            const next =
              typeof updater === "function"
                ? (updater as (p: typeof prev) => typeof prev)(prev)
                : (updater as typeof prev)
            mp.onPageChange(next.pageIndex)
          },
        }
      : { getPaginationRowModel: getPaginationRowModel() }),
  })
```

- [ ] **Step 2: Make the footer tell the truth**

In manual mode `data.length` is one page, so the existing `of {data.length} entries` would
under-report. Derive all three numbers from the source of truth:

```tsx
  const total = mp ? mp.total : data.length
  const pageSize = mp ? mp.pageSize : table.getState().pagination.pageSize
  const pageIndex = mp ? mp.pageIndex : table.getState().pagination.pageIndex
  const first = total === 0 ? 0 : pageIndex * pageSize + 1
  const last = Math.min((pageIndex + 1) * pageSize, total)
```

Use `first`, `last`, `total` in the existing "Showing X to Y of Z entries" copy.

- [ ] **Step 3: Show the pager in manual mode, and hide the rows-per-page select there**

- The render guard is currently `table.getPageCount() > 1`. Change it to
  `(mp ? mp.pageCount : table.getPageCount()) > 1`.
- The "Rows per page" `<Select>` calls `table.setPageSize()`, which is meaningless in manual
  mode (page size is owned by the caller's `usePagination`). Wrap it in `{!mp && ( … )}`.

- [ ] **Step 4: `bunx tsc --noEmit`** — expect clean. No existing caller passes
`manualPagination`, so `admin.tsx` still compiles unchanged at this point.

- [ ] **Step 5: Commit** — `feat(frontend): add opt-in manual (server-side) pagination to DataTable`

---

# INTEGRATION — after both Stage 1 worktrees merge

## Task I1: Merge, regenerate the SDK once, verify green

- [ ] **Step 1: Merge both branches into `dev_wth`**

```bash
git checkout dev_wth
git merge --no-ff feat/list-options-and-envelopes
git merge --no-ff feat/list-pagination-primitives   # no file overlap — must be clean
```

- [ ] **Step 2: Regenerate the SDK ONCE against the merged backend**

```bash
bun run generate-client
```

> If a `client/*.gen.ts` conflict ever appears, do **not** hand-merge — take either side
> and re-run this. The SDK is generated, never authored (`CLAUDE.md`).

- [ ] **Step 3: Expect the frontend to NOT compile.** The six list screens still treat the
list responses as bare arrays; they are now `{data, count}`. **This is the intended red
state** — Stage 2 fixes each screen. Confirm the errors are exactly that and nothing else:

```bash
docker run --rm -v "$PWD:/app" -v /app/node_modules -w /app/frontend frontend:latest bunx tsc --noEmit
```

- [ ] **Step 4: Backend must be fully green**

```bash
... python -m pytest tests -q && python -m mypy app && python -m ruff check app tests
```

- [ ] **Step 5: Commit the regenerated SDK** — `chore(sdk): regenerate for options endpoints and list envelopes`

## Task I2: Create ALL options hooks — once, here

**Files:**
- Create: `frontend/src/hooks/useCustomerOptions.ts`, `useSupplierOptions.ts`, `useProjectOptions.ts`
- Modify: `frontend/src/hooks/useProductOptions.ts` (add `activeOnly`)

**Why here and not in a Stage-2 task:** `useProductOptions` is needed by F1, F2 *and* F6, and
the three new hooks are needed by more than one F-task each. If any F-task created them, the
"parallel" worktrees would collide on `frontend/src/hooks/`. Creating them at integration
makes every Stage-2 task a pure **consumer**, so the six really are independent.

They cannot be written in the Stage-1 UI worktree either — they call SDK methods that do not
exist until the backend merges and the SDK is regenerated (Task I1).

- [ ] **Step 1: Create the three hooks**

```ts
// frontend/src/hooks/useCustomerOptions.ts
import { useQuery } from "@tanstack/react-query"
import { CustomersService } from "@/client"

/** Complete customer list for the pickers. Unpaginated by design — the picker must work
 *  offline (FR-007 requires a customer on every sale), so the list lives on the device. */
export function useCustomerOptions() {
  return useQuery({
    queryKey: ["customers", "options"],
    queryFn: () => CustomersService.readOptions(),
  })
}
```

```ts
// frontend/src/hooks/useSupplierOptions.ts
import { useQuery } from "@tanstack/react-query"
import { SuppliersService } from "@/client"

/** Complete supplier list for the receive tabs and the stock supplier filter. */
export function useSupplierOptions({ enabled = true } = {}) {
  return useQuery({
    queryKey: ["suppliers", "options"],
    queryFn: () => SuppliersService.readOptions(),
    enabled,
  })
}
```

```ts
// frontend/src/hooks/useProjectOptions.ts
import { useQuery } from "@tanstack/react-query"
import { ProjectsService } from "@/client"

/** ACTIVE projects only — a CLOSED project must not accept a new pull. Admin-only
 *  endpoint, so callers gate with `enabled: isAdmin`. */
export function useProjectOptions({ enabled = true } = {}) {
  return useQuery({
    queryKey: ["projects", "options"],
    queryFn: () => ProjectsService.readOptions(),
    enabled,
  })
}
```

- [ ] **Step 2: Add `activeOnly` to `useProductOptions`**

Keep the default `false` so the **audit SKU combobox keeps seeing discontinued SKUs** (their
movements live in the ledger forever). Pickers opt in with `true`. Note the distinct query
keys — the two variants must not share a cache entry.

```ts
// frontend/src/hooks/useProductOptions.ts
import { useQuery } from "@tanstack/react-query"
import { ProductsService } from "@/client"

/**
 * Complete product list for pickers/lookups.
 *
 * `activeOnly` drops discontinued products — what the sale/receive/tickets/pulls pickers
 * want. It defaults to FALSE because the audit SKU filter shares this hook and must still
 * be able to select a discontinued SKU, whose historical movements remain in the ledger.
 */
export function useProductOptions({ activeOnly = false } = {}) {
  return useQuery({
    queryKey: ["products", "options", { activeOnly }],
    queryFn: () => ProductsService.readOptions({ activeOnly }),
  })
}
```

> Check the merged `useProductOptions` for its existing signature and query key, and keep
> every current caller working — the audit SKU combobox calls it with no argument and must
> keep the unfiltered behaviour.

- [ ] **Step 3: `bunx tsc --noEmit`** — the four hooks must compile. The six screens still
will not (Stage 2 fixes them); that is expected.

- [ ] **Step 4: Commit** — `feat(frontend): options hooks for customers/suppliers/projects + activeOnly on products`

---

# STAGE 2 — six parallel worktrees

Each branches off the integrated `dev_wth`. **Each owns distinct screen files — no two touch
the same file, and none creates a hook** (Task I2 did). Every task ends with
`bunx tsc --noEmit` clean + a commit.

Common pattern for a **table** migration:

```tsx
const { page, pageSize, skip, limit, setPage } = usePagination()

const { data } = useQuery({
  queryKey: ["customers", { skip, limit }],   // page MUST be in the key
  queryFn: () => CustomersService.readCustomers({ skip, limit }),
  placeholderData: keepPreviousData,          // no empty flash while paging
})

const rows = data?.data ?? []
const total = data?.count ?? 0
// ...existing table markup, unchanged, rendering `rows`...
<PaginationControls total={total} pageSize={pageSize} page={page} onPageChange={setPage} />
```

## Task F1 — `sale.tsx` + `tickets.tsx`: customer pickers ← **DO THIS FIRST**

**Files:**
- Modify: `frontend/src/routes/_layout/sale.tsx`, `frontend/src/routes/_layout/tickets.tsx`

**Interfaces:**
- Consumes: `useCustomerOptions()` and `useProductOptions({activeOnly})` (Task I2); `<EntityCombobox>` (Task U3).

This is the task that unblocks checkout. Ship it before the others.

- [ ] **Step 1:** In `sale.tsx`, replace the `CustomersService.readCustomers()` query with `useCustomerOptions()`, and swap the `CheckoutPanel` customer `<Select>` for `<EntityCombobox>`:

```tsx
<EntityCombobox
  items={customers ?? []}
  value={customerId}
  onChange={setCustomerId}
  getKey={(c) => c.id}
  getLabel={(c) => c.name}
  placeholder="Select customer…"
  searchPlaceholder="Search customers…"
  emptyText="No customer found."
  ariaLabel="Customer"
/>
```

- [ ] **Step 2:** Same swap in `tickets.tsx`'s `CustomerPicker` (desktop **and** mobile call sites).
- [ ] **Step 3:** The products query in both files is already `useProductOptions` (from the merged branch). Pass `{ activeOnly: true }` — a picker must not offer a discontinued product.
- [ ] **Step 4:** `bunx tsc --noEmit` — expect clean.
- [ ] **Step 5: Commit** — `fix(sale,tickets): customer picker reaches every customer (was capped at 100)`

## Task F2 — `receive.tsx` + `stock.tsx`: supplier pickers

**Files:** Modify `frontend/src/routes/_layout/receive.tsx`, `frontend/src/routes/_layout/stock.tsx`

**Interfaces:**
- Consumes: `useSupplierOptions({enabled})`, `useProductOptions({activeOnly})` (Task I2); `<EntityCombobox>` (Task U3).

- [ ] **Step 1:** Replace both `SuppliersService.readSuppliers()` calls in `receive.tsx` (SerializedTab + QuantityTab) and the one in `stock.tsx` (admin filter — keep the admin gate by passing `useSupplierOptions({ enabled: isAdmin })`).
- [ ] **Step 2:** Swap all three `<Select>`s for `<EntityCombobox>` (`ariaLabel="Supplier"`; on `stock.tsx` pass `allowClear` so the filter can be cleared).
- [ ] **Step 3:** Pass `{ activeOnly: true }` to `useProductOptions` in `receive.tsx`'s two tabs.
- [ ] **Step 4:** `bunx tsc --noEmit`; **Step 5: Commit** — `fix(receive,stock): supplier picker reaches every supplier`

## Task F3 — `customers.tsx` + `suppliers.tsx`: tables

**Files:** Modify `frontend/src/routes/_layout/customers.tsx`, `frontend/src/routes/_layout/suppliers.tsx`

- [ ] **Step 1:** Apply the table pattern above to both (`readCustomers` / `readSuppliers` now return `{data, count}`).
- [ ] **Step 2:** Render `<PaginationControls>` under each table. **Do not touch the existing table markup or the mobile-card layouts.**
- [ ] **Step 3:** `bunx tsc --noEmit`; **Step 4: Commit** — `feat(customers,suppliers): server-side table pagination`

## Task F4 — `products.tsx` + `admin.tsx`

**Files:** Modify `frontend/src/routes/_layout/products.tsx`, `frontend/src/routes/_layout/admin.tsx`

**Interfaces:**
- Consumes: `usePagination` (U1), `<PaginationControls>` (U2), `DataTable`'s `manualPagination` (U4).

- [ ] **Step 1:** `products.tsx` — table pattern (`readProducts` → `{data, count}`) + `<PaginationControls>`. The catalog table keeps showing **inactive** products (only pickers filter).
- [ ] **Step 2:** `admin.tsx` — replace the hard-coded `readUsers({skip: 0, limit: 100})` with `usePagination` + real `skip`/`limit` (**page must be in the queryKey**, or TanStack serves the cached first page forever and the pager silently does nothing again). `/users/` already returns `count` — no backend change.

```tsx
const { page, pageSize, skip, limit, setPage, pageCount } = usePagination()

const { data } = useQuery({
  queryKey: ["users", { skip, limit }],
  queryFn: () => UsersService.readUsers({ skip, limit }),
  placeholderData: keepPreviousData,
})

const total = data?.count ?? 0

<DataTable
  columns={columns}
  data={data?.data ?? []}
  manualPagination={{
    pageCount: pageCount(total),
    pageIndex: page - 1,
    pageSize,
    total,
    onPageChange: (i) => setPage(i + 1),
  }}
/>
```

- [ ] **Step 3:** `bunx tsc --noEmit`; **Step 4: Commit** — `fix(admin,products): real server-side pagination (the admin pager no longer lies)`

## Task F5 — `projects.tsx`

**Files:** Modify `frontend/src/routes/_layout/projects.tsx`

**Interfaces:**
- Consumes: `useCustomerOptions()` (I2), `<EntityCombobox>` (U3), `usePagination` + `<PaginationControls>` (U1/U2).

Owns the whole file: **both** the customer picker and the projects table. (This is why F1 does
not touch `projects.tsx` even though it is a customer picker — one owner per file.)

- [ ] **Step 1:** Swap the customer `<Select>` for `<EntityCombobox>` backed by `useCustomerOptions()`.
- [ ] **Step 2:** Apply the table pattern to the projects list + `<PaginationControls>`.
- [ ] **Step 3:** `bunx tsc --noEmit`; **Step 4: Commit** — `feat(projects): complete customer picker + server-side table pagination`

## Task F6 — `pulls.tsx` + `PullCreatePanel.tsx` + `pricing-overrides.tsx`

**Files:** Modify `frontend/src/routes/_layout/pulls.tsx`, `frontend/src/components/pos/PullCreatePanel.tsx`, `frontend/src/routes/_layout/pricing-overrides.tsx`

**Interfaces:**
- Consumes: `useProjectOptions({enabled})`, `useProductOptions({activeOnly})` (I2); `<EntityCombobox>` (U3); `usePagination` + `<PaginationControls>` (U1/U2); the denormalized `product_sku` / `model_name` fields (B8).

- [ ] **Step 1:** `pulls.tsx` — replace `ProjectsService.readProjects()` with `useProjectOptions({ enabled: isAdmin })`; swap the project `<Select>` in `PullCreatePanel` for `<EntityCombobox>` (`ariaLabel="Project"`). Pass `{ activeOnly: true }` to `useProductOptions`.
- [ ] **Step 2:** `pulls.tsx` — **delete the `productNames` map** and read `line.model_name` / `line.product_sku` straight off the pull line (B8). Apply the table pattern to the pull queue + `<PaginationControls>`.
- [ ] **Step 3:** `pricing-overrides.tsx` — **delete the `productLabels` map and the whole products query**; read `row.product_sku` (B8). Apply the table pattern + `<PaginationControls>`.
- [ ] **Step 4: Both filtered tables — put `state` in the queryKey AND reset to page 1 on filter change.**

Without the reset, switching the filter while on page 3 requests `skip=50` against a
3-row filtered result and renders an empty table:

```tsx
const { page, pageSize, skip, limit, setPage, reset, pageCount } = usePagination()

const { data } = useQuery({
  queryKey: ["pricing-overrides", state, { skip, limit }],  // state AND page in the key
  queryFn: () => PricingOverridesService.listPricingOverrides({ state, skip, limit }),
  placeholderData: keepPreviousData,
})

// on the filter control:
onValueChange={(next) => {
  setState(next)
  reset()          // back to page 1 — the old page may not exist under the new filter
}}
```

- [ ] **Step 5:** `bunx tsc --noEmit`; **Step 6: Commit** — `feat(pulls,pricing-overrides): server-side pagination; drop the product label maps`

---

# FINAL — verification & review

## Task V1: Full verification

- [ ] **Step 1: Backend green on `app_test`**

```bash
... python -m pytest tests -q && python -m mypy app && python -m ruff check app tests
```

- [ ] **Step 2: Frontend green**

```bash
docker run --rm -v "$PWD:/app" -v /app/node_modules -w /app/frontend frontend:latest bunx tsc --noEmit
docker run --rm -v "$PWD:/app" -v /app/node_modules -w /app/frontend frontend:latest bunx biome check src
```

- [ ] **Step 3: E2E on `app_test` — NEVER the dev `app` DB**

Add `frontend/tests/list-pagination.spec.ts` asserting the two behaviours that actually matter:

```ts
test("a customer beyond the old 100-row cap is selectable at checkout", async ({ page }) => {
  // seed >100 customers via privateApi, then:
  await page.goto("/sale")
  await page.getByRole("combobox", { name: "Customer" }).click()
  await page.getByPlaceholder("Search customers…").fill("ZZZ Last Customer")
  await page.getByRole("option", { name: "ZZZ Last Customer" }).click()
  await expect(page.getByRole("combobox", { name: "Customer" })).toContainText(
    "ZZZ Last Customer",
  )
})

test("the customers table pages to page 2 and shows different rows", async ({ page }) => {
  await page.goto("/customers")
  const firstRow = await page.getByRole("row").nth(1).textContent()
  await page.getByRole("link", { name: /next/i }).click()
  await expect(page.getByRole("row").nth(1)).not.toHaveText(firstRow ?? "")
})
```

Run via the throwaway `e2e-backend` (`POSTGRES_DB=app_test`) with `E2E_SKIP_DB_RESET=1`, then
**verify the dev `app` DB is intact** (users/products/sales counts unchanged).

## Task V2: High-risk review (mandatory)

- [ ] **Step 1:** `superpowers:requesting-code-review` over the whole branch.
- [ ] **Step 2:** Additionally dispatch **`ecc:database-reviewer`** and **`ecc:security-reviewer`** (`CLAUDE.md` §5 — role-tiered financial fields).

**Direct the security reviewer at the one thing that matters most:** `ProductOption` carries
`retail_price_thb` + `repair_price_thb`. Confirm these are **selling** prices (staff already
transact at them) and that **no purchase-cost/COGS/margin field is present** — the PRD rule
is that cost is "completely hidden from staff, not just visually masked".

**Direct the database reviewer at the count invariant:** every `count_*` must apply the same
`WHERE` clause as its `list_*`. Check `count_pricing_overrides` and `count_project_pulls`
clause-for-clause against their list functions.

## Task V3: Update `notes.md`

- [ ] **Step 1:** Mark the truncation bug section **DONE**, listing what shipped.
- [ ] **Step 2:** Leave the **"BEHAVIOR CHANGE TO CONFIRM — pickers become active-only"** block
in place and **unresolved** — the owner asked to confirm it after seeing it live.
- [ ] **Step 3:** Record what remains: `audit.tsx`'s user-filter dropdown (still a bare
`readUsers()`, deliberately untouched — the other dev owns that file), and
`GET /search/sku/{sku}`'s `_CONSUMPTION_LIMIT = 200` ceiling.
