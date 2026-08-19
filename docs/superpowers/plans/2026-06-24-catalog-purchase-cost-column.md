# Admin Catalog Purchase-Cost Column Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Purchase" column to the Admin Catalog showing each product's latest purchase cost, without exposing cost to non-admin users.

**Architecture:** A new admin-only endpoint `GET /products/purchase-costs` returns the latest receipt cost per product (newest `PartBatch` for QUANTITY / newest `Unit` for SERIALIZED by `received_at`). The catalog page fetches it separately and merges client-side. `ProductPublic` and the staff-accessible `GET /products/` are left unchanged so COGS never leaks.

**Tech Stack:** FastAPI + SQLModel + Postgres (DISTINCT ON), `@hey-api/openapi-ts` SDK, React + TanStack Query + shadcn/ui.

## Global Constraints

- HIGH-RISK (cost/COGS). Review stage MUST also run `ecc:database-reviewer` + `ecc:security-reviewer`.
- COGS stays admin-only: the new endpoint is `dependencies=[Depends(get_admin)]`; cost must NOT be added to `ProductPublic` or any `get_current_user` endpoint.
- All DB access through `crud.py`; no raw SQL in routes.
- Set-based, no N+1 (DISTINCT ON per source, merged in Python).
- "Purchase price" = latest receipt cost by `received_at`; products with no receipts are absent (UI shows `—`).
- No Alembic migration (read-only over existing `PartBatch`/`Unit` columns).
- mypy strict (annotate everything); ruff for changed lines only; biome for frontend; never hand-edit `frontend/src/client/`.
- Money columns are THB only (matches Retail/Repair).

---

### Task 1: Backend — latest-purchase-cost endpoint (admin-only)

**Files:**
- Modify: `backend/app/models.py` (add `ProductPurchaseCost` after `ProductPublic`, ~line 409)
- Modify: `backend/app/crud.py` (add `latest_purchase_costs`)
- Modify: `backend/app/api/routes/products.py` (add route + import)
- Create: `backend/tests/api/routes/test_purchase_costs.py`

**Interfaces:**
- Produces: `crud.latest_purchase_costs(*, session: Session) -> dict[uuid.UUID, Decimal]`
- Produces: `ProductPurchaseCost(product_id: uuid.UUID, latest_purchase_cost_thb: Decimal)`
- Produces: `GET /products/purchase-costs` → `list[ProductPurchaseCost]`, admin-only.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/api/routes/test_purchase_costs.py`:

```python
import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import Location, ProductCreate, SupplierCreate, TrackingMode


def _ensure_locations(db: Session) -> None:
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)


def _new_product(db: Session, mode: TrackingMode) -> uuid.UUID:
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"PC-{uuid.uuid4().hex[:8]}",
            model_name="Bearing",
            tracking_mode=mode,
            retail_price_thb="50.00",
            repair_price_thb="10.00",
        ),
    )
    return product.id


def _new_supplier(db: Session) -> uuid.UUID:
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name="Acme Parts", country="TH")
    )
    return supplier.id


def _receive_quantity(
    client: TestClient,
    headers: dict[str, str],
    product_id: uuid.UUID,
    supplier_id: uuid.UUID,
    cost: str,
) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/receipts/quantity",
        headers=headers,
        json={
            "product_id": str(product_id),
            "supplier_id": str(supplier_id),
            "received_qty": 5,
            "purchase_cost_thb": cost,
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 200, r.text


def _receive_serialized(
    client: TestClient,
    headers: dict[str, str],
    product_id: uuid.UUID,
    supplier_id: uuid.UUID,
    cost: str,
) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/receipts/serialized",
        headers=headers,
        json={
            "product_id": str(product_id),
            "supplier_id": str(supplier_id),
            "pieces": [
                {"supplier_serial": f"SN-{uuid.uuid4().hex[:10]}", "purchase_cost_thb": cost}
            ],
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 200, r.text


def _costs_by_product(client: TestClient, headers: dict[str, str]) -> dict[str, str]:
    r = client.get(
        f"{settings.API_V1_STR}/products/purchase-costs", headers=headers
    )
    assert r.status_code == 200, r.text
    return {row["product_id"]: row["latest_purchase_cost_thb"] for row in r.json()}


def test_purchase_costs_forbidden_for_staff(
    client: TestClient, staff_token_headers: dict[str, str]
) -> None:
    r = client.get(
        f"{settings.API_V1_STR}/products/purchase-costs",
        headers=staff_token_headers,
    )
    assert r.status_code == 403, r.text


def test_purchase_costs_latest_quantity_batch_wins(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _ensure_locations(db)
    product_id = _new_product(db, TrackingMode.QUANTITY)
    supplier_id = _new_supplier(db)
    _receive_quantity(client, superuser_token_headers, product_id, supplier_id, "5.00")
    _receive_quantity(client, superuser_token_headers, product_id, supplier_id, "7.00")
    costs = _costs_by_product(client, superuser_token_headers)
    assert Decimal(costs[str(product_id)]) == Decimal("7.00")


def test_purchase_costs_latest_serialized_unit_wins(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _ensure_locations(db)
    product_id = _new_product(db, TrackingMode.SERIALIZED)
    supplier_id = _new_supplier(db)
    _receive_serialized(client, superuser_token_headers, product_id, supplier_id, "900.00")
    _receive_serialized(client, superuser_token_headers, product_id, supplier_id, "1100.00")
    costs = _costs_by_product(client, superuser_token_headers)
    assert Decimal(costs[str(product_id)]) == Decimal("1100.00")


def test_purchase_costs_absent_without_receipts(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    product_id = _new_product(db, TrackingMode.QUANTITY)
    costs = _costs_by_product(client, superuser_token_headers)
    assert str(product_id) not in costs


def test_products_list_exposes_no_cost_to_staff(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    _new_product(db, TrackingMode.QUANTITY)
    r = client.get(f"{settings.API_V1_STR}/products/", headers=staff_token_headers)
    assert r.status_code == 200, r.text
    blob = str(r.json()).lower()
    assert "purchase_cost" not in blob
    assert "latest_purchase_cost_thb" not in blob
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && pytest tests/api/routes/test_purchase_costs.py -v`
Expected: FAIL — `GET /products/purchase-costs` returns 404 (route not defined) for the admin tests; the staff-403 test fails (404 not 403); the no-leak test may already pass.

- [ ] **Step 3: Add the `ProductPurchaseCost` schema**

In `backend/app/models.py`, immediately after `class ProductPublic(ProductBase): / id: uuid.UUID` (~line 409):

```python
class ProductPurchaseCost(SQLModel):
    # Admin-only: latest receipt cost (COGS). Never added to ProductPublic,
    # which is served by the staff-accessible GET /products/.
    product_id: uuid.UUID
    latest_purchase_cost_thb: Decimal
```

(`Decimal` and `uuid` are already imported in models.py.)

- [ ] **Step 4: Add the `latest_purchase_costs` crud function**

In `backend/app/crud.py` (e.g. just after `list_products`). `sa_select`, `col`,
`PartBatch`, `Unit`, `Decimal`, `datetime`, `uuid` are already imported:

```python
def latest_purchase_costs(*, session: Session) -> dict[uuid.UUID, Decimal]:
    """Latest purchase cost per product — the purchase_cost_thb of the most
    recent receipt: newest PartBatch (QUANTITY) or newest Unit (SERIALIZED) by
    received_at. COGS / admin-only data. Set-based via Postgres DISTINCT ON (one
    row per product per source), merged in Python; no N+1. Products with no
    receipts are absent from the result."""
    latest: dict[uuid.UUID, tuple[datetime, Decimal]] = {}
    batch_rows = session.execute(
        sa_select(
            PartBatch.product_id, PartBatch.received_at, PartBatch.purchase_cost_thb
        )
        .order_by(PartBatch.product_id, PartBatch.received_at.desc())
        .distinct(PartBatch.product_id)
    ).all()
    unit_rows = session.execute(
        sa_select(Unit.product_id, Unit.received_at, Unit.purchase_cost_thb)
        .order_by(Unit.product_id, Unit.received_at.desc())
        .distinct(Unit.product_id)
    ).all()
    for source in (batch_rows, unit_rows):
        for r in source:
            product_id, received_at, cost = r[0], r[1], r[2]
            current = latest.get(product_id)
            if current is None or received_at > current[0]:
                latest[product_id] = (received_at, cost)
    return {pid: value[1] for pid, value in latest.items()}
```

- [ ] **Step 5: Add the admin-only route**

In `backend/app/api/routes/products.py`, add `ProductPurchaseCost` to the
`from app.models import (...)` block, then add this route immediately AFTER the
`read_products` function and BEFORE the `/{product_id}/label.pdf` route (a static
path must precede param paths):

```python
@router.get(
    "/purchase-costs",
    response_model=list[ProductPurchaseCost],
    dependencies=[Depends(get_admin)],
)
def read_purchase_costs(session: SessionDep) -> list[ProductPurchaseCost]:
    """Latest purchase cost per product (admin-only COGS). One entry per product
    that has at least one receipt."""
    costs = crud.latest_purchase_costs(session=session)
    return [
        ProductPurchaseCost(product_id=pid, latest_purchase_cost_thb=cost)
        for pid, cost in costs.items()
    ]
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && pytest tests/api/routes/test_purchase_costs.py -v`
Expected: all 5 PASS.

- [ ] **Step 7: Typecheck and lint changed files**

Run: `cd backend && uv run mypy app/crud.py app/models.py app/api/routes/products.py`
Expected: `Success: no issues found`.
Run: `cd backend && uv run ruff check app/crud.py app/models.py app/api/routes/products.py`
Expected: clean. (Do NOT run `ruff format` on the whole files — it reformats unrelated lines; only fix lints your change introduced.)

- [ ] **Step 8: Commit**

```bash
git add backend/app/models.py backend/app/crud.py backend/app/api/routes/products.py backend/tests/api/routes/test_purchase_costs.py
git commit -m "feat(products): admin-only latest-purchase-cost endpoint"
```

---

### Task 2: Regenerate the SDK

**Files:**
- Modify: `frontend/src/client/` (auto-generated)

**Interfaces:**
- Consumes: `GET /products/purchase-costs` from Task 1.
- Produces: `ProductsService.readPurchaseCosts()` returning `Array<ProductPurchaseCost>` where `ProductPurchaseCost = { product_id: string; latest_purchase_cost_thb: number | string }`.

- [ ] **Step 1: Regenerate**

The script builds the OpenAPI spec from the app directly (no running server needed). From repo root:

Run: `bash scripts/generate-client.sh`

- [ ] **Step 2: Verify the new type and service method**

Run: `grep -n "ProductPurchaseCost\|readPurchaseCosts\|purchase-costs" frontend/src/client/*.gen.ts`
Expected: a `ProductPurchaseCost` type with `product_id` + `latest_purchase_cost_thb`, and a `readPurchaseCosts` method on the products service. **Note the exact generated method name** (hey-api derives it from the operationId; if it differs from `readPurchaseCosts`, use the generated name in Task 3).

- [ ] **Step 3: Revert any unrelated lint churn and commit only the client**

The generate script runs `bun run lint`, which may auto-fix unrelated files. Revert anything outside `frontend/src/client/`:

```bash
git add frontend/src/client
git checkout -- $(git diff --name-only | grep -v '^frontend/src/client/' || true)
git status --short
git commit -m "chore(client): regenerate SDK for product purchase-costs"
```

---

### Task 3: Frontend — "Purchase" column on the catalog

**Files:**
- Modify: `frontend/src/routes/_layout/products.tsx`

**Interfaces:**
- Consumes: `ProductsService.readPurchaseCosts()` (or the exact name confirmed in Task 2) and `formatThb` (already imported).

- [ ] **Step 1: Fetch purchase costs and build a lookup map**

In `Products()`, just after the existing `const { data: products } = useQuery({ queryKey: ["products"], ... })`, add:

```tsx
  const { data: purchaseCosts } = useQuery({
    queryKey: ["product-purchase-costs"],
    queryFn: () => ProductsService.readPurchaseCosts(),
  })
  const costByProductId = new Map(
    (purchaseCosts ?? []).map((c) => [
      c.product_id,
      String(c.latest_purchase_cost_thb),
    ]),
  )
```

- [ ] **Step 2: Add the "Purchase" header**

In the Catalog `<TableHeader>`, add a Purchase head immediately before the Retail head:

```tsx
                <TableHead className="text-right">Purchase</TableHead>
                <TableHead className="text-right">Retail</TableHead>
```

- [ ] **Step 3: Add the "Purchase" cell**

In the product `.map(...)` row, add a Purchase cell immediately before the
existing Retail cell (`<TableCell className="num text-right">{formatThb(p.retail_price_thb)}</TableCell>`):

```tsx
                  <TableCell className="num text-right">
                    {costByProductId.has(p.id)
                      ? formatThb(costByProductId.get(p.id) as string)
                      : "—"}
                  </TableCell>
```

- [ ] **Step 4: Typecheck and lint the one file**

Run (from `frontend/`): `bunx tsc --noEmit`
Expected: no errors.
Run (from `frontend/`): `bunx biome check src/routes/_layout/products.tsx`
Expected: clean (if it flags import order from Task 1's earlier edit, run `bunx biome check --write src/routes/_layout/products.tsx`, scoped to this file only).

- [ ] **Step 5: Manual verification**

With `docker compose watch` running, open the Admin Catalog as an admin:
- A "Purchase" column appears just before Retail/Repair.
- A product with at least one received batch/unit shows its latest receipt cost in `฿` format; the value matches the newest delivery's cost.
- A product never received shows `—`.
- Log in as staff and confirm the catalog page is not reachable (already `requireAdmin`) and that the network has no purchase-cost data for staff.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/_layout/products.tsx
git commit -m "feat(catalog): show latest purchase cost column"
```

---

## Self-Review

**Spec coverage:**
- Latest purchase cost per product (newest batch/unit) → Task 1 `latest_purchase_costs`. ✅
- Admin-only, no COGS leak → route `Depends(get_admin)`; `ProductPublic` untouched; staff-403 + no-leak tests (Task 1 Steps 1/6). ✅
- Separate endpoint, merged client-side → Tasks 1-3. ✅
- "Purchase" column before Retail/Repair, `—` when absent, THB → Task 3. ✅
- No migration; set-based no N+1 → Task 1 Step 4 (DISTINCT ON ×2, merge). ✅
- High-risk review (database + security reviewers) → Global Constraints. ✅

**Placeholder scan:** none — full code in every code step.

**Type consistency:** `latest_purchase_costs -> dict[uuid.UUID, Decimal]` feeds `ProductPurchaseCost(product_id, latest_purchase_cost_thb: Decimal)` → SDK `{ product_id: string; latest_purchase_cost_thb: number|string }` → frontend stores `String(...)` in `Map<string,string>` → `formatThb(string)`. Route method name `read_purchase_costs` → SDK `readPurchaseCosts` (Task 2 Step 2 confirms the exact name before Task 3 uses it). DISTINCT ON requires the leading ORDER BY column to be `product_id` — satisfied in both queries.
