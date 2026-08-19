# Stock Page Category + Brand Columns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show Category and Brand as per-row columns on the Inventory > Stock page so sales staff can see them at a glance.

**Architecture:** `category` already ships in the `StockOnHandRow` payload (frontend just doesn't render it). `brand` is added to the row schema and the read-only `stock_on_hand()` query (the column already exists on `Product`, so no migration). The SDK is regenerated, then `stock.tsx` renders both as columns (desktop table) and a subtext line (mobile card).

**Tech Stack:** FastAPI + SQLModel (backend), `@hey-api/openapi-ts` SDK, React + TanStack + shadcn/ui (frontend).

## Global Constraints

- All DB access goes through `crud.py`; routes never run raw SQL. (CLAUDE.md)
- `stock_on_hand()` stays a single set-based pass — no N+1, no per-row property. (existing docstring)
- No cost/COGS/price fields in this both-roles view. (existing docstring; Brand is not financial.)
- This view is read-only — **no Alembic migration** (`Product.brand` already exists).
- mypy strict: annotate everything. Lint/format: ruff (backend), biome (frontend).
- Never hand-edit `frontend/src/client/` — regenerate with `bun run generate-client`.

---

### Task 1: Add `brand` to the stock-on-hand payload

**Files:**
- Modify: `backend/app/models.py:1540-1546` (`StockOnHandRow`)
- Modify: `backend/app/crud.py:3520-3541` (`stock_on_hand()` select + row build)
- Test: `backend/tests/api/routes/test_dashboards.py`

**Interfaces:**
- Produces: `StockOnHandRow.brand: str | None` — present on every row of the
  `GET /dashboards/stock-on-hand` response (`{"rows": [{..., "brand": ...}]}`).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/api/routes/test_dashboards.py` (imports `crud`, `ProductCreate`, `TrackingMode`, `settings`, `uuid` already exist in this file):

```python
def test_stock_on_hand_includes_brand(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
) -> None:
    branded_sku = f"BRAND-{uuid.uuid4().hex[:8]}"
    crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=branded_sku,
            model_name="Bearing",
            brand="Acme",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="50.00",
            repair_price_thb="10.00",
        ),
    )
    r = client.get(
        f"{settings.API_V1_STR}/dashboards/stock-on-hand",
        headers=staff_token_headers,
    )
    assert r.status_code == 200, r.text
    rows = {row["sku"]: row for row in r.json()["rows"]}
    assert rows[branded_sku]["brand"] == "Acme"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/api/routes/test_dashboards.py::test_stock_on_hand_includes_brand -v`
Expected: FAIL with `KeyError: 'brand'` (field not in response).

- [ ] **Step 3: Add `brand` to the row schema**

In `backend/app/models.py`, `StockOnHandRow` becomes:

```python
class StockOnHandRow(SQLModel):
    product_id: uuid.UUID
    sku: str
    model_name: str
    brand: str | None
    category: str | None
    tracking_mode: TrackingMode
    quantity_on_hand: int
```

- [ ] **Step 4: Add `Product.brand` to the query and row build**

In `backend/app/crud.py` `stock_on_hand()`, update the `select(...)` and the row
construction (note every index shifts by one after `model_name`):

```python
    stmt = select(  # type: ignore[call-overload]
        Product.id,
        Product.sku,
        Product.model_name,
        Product.brand,
        Product.category,
        Product.tracking_mode,
        on_hand.label("quantity_on_hand"),
    ).where(col(Product.is_active).is_(True))
    if category is not None:
        stmt = stmt.where(col(Product.category) == category)
    stmt = stmt.order_by(col(Product.sku))
    rows = [
        StockOnHandRow(
            product_id=r[0],
            sku=r[1],
            model_name=r[2],
            brand=r[3],
            category=r[4],
            tracking_mode=r[5],
            quantity_on_hand=int(r[6] or 0),
        )
        for r in session.exec(stmt).all()
    ]
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd backend && pytest tests/api/routes/test_dashboards.py -v`
Expected: PASS (new test green, existing stock tests still green).

- [ ] **Step 6: Commit**

```bash
git add backend/app/models.py backend/app/crud.py backend/tests/api/routes/test_dashboards.py
git commit -m "feat(stock): add brand to stock-on-hand payload"
```

---

### Task 2: Regenerate the SDK

**Files:**
- Modify: `frontend/src/client/` (auto-generated — do not hand-edit)

**Interfaces:**
- Consumes: `StockOnHandRow.brand` from Task 1.
- Produces: TypeScript `StockOnHandRow` type with `brand: string | null`, used by `stock.tsx` in Task 3.

- [ ] **Step 1: Regenerate the client**

The backend must be running (`docker compose watch`) so the OpenAPI schema is current. From `frontend/`:

Run: `bun run generate-client`

- [ ] **Step 2: Verify `brand` is in the generated type**

Run: `grep -n "brand" frontend/src/client/types.gen.ts`
Expected: a `brand?: string | null` (or `brand: string | null`) line within the `StockOnHandRow` type.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/client
git commit -m "chore(client): regenerate SDK for stock-on-hand brand"
```

---

### Task 3: Render Brand + Category columns on the Stock page

**Files:**
- Modify: `frontend/src/routes/_layout/stock.tsx`

**Interfaces:**
- Consumes: `r.brand` / `r.category` from the regenerated `StockOnHandRow`.

- [ ] **Step 1: Add `brand` to `StockItemProps`**

In `stock.tsx`, the `StockItemProps` interface (currently has `category: string | null`) gains `brand`:

```typescript
interface StockItemProps {
  productId: string
  sku: string
  modelName: string
  brand: string | null
  category: string | null
  trackingMode: string
  quantityOnHand: number
  isQuantity: boolean
  isOpen: boolean
  onToggle: () => void
}
```

- [ ] **Step 2: Pass `brand` when rendering rows and cards**

In both the mobile `.map` (`<StockCard ... />`) and the desktop `.map`
(`<StockRow ... />`), add `brand={r.brand}` alongside the existing
`category={r.category}` prop. Both call sites get the same one-line addition:

```tsx
                  brand={r.brand}
                  category={r.category}
```

- [ ] **Step 3: Add the desktop column headers**

In `StockOnHand`, update the desktop `<TableHeader>` to insert Brand and Category between Product and In stock:

```tsx
          <TableHeader>
            <TableRow>
              <TableHead className="w-8" />
              <TableHead>Product</TableHead>
              <TableHead>Brand</TableHead>
              <TableHead>Category</TableHead>
              <TableHead className="text-right">In stock</TableHead>
              <TableHead className="w-0" aria-label="Labels" />
            </TableRow>
          </TableHeader>
```

- [ ] **Step 4: Render the desktop cells and fix the colSpan**

In `StockRow`, destructure `brand` and `category` from props, add two cells
after the Product cell, and bump the drill-down `colSpan` from 4 to 6:

```tsx
function StockRow({
  productId,
  sku,
  modelName,
  brand,
  category,
  trackingMode,
  quantityOnHand,
  isQuantity,
  isOpen,
  onToggle,
}: StockItemProps) {
  return (
    <>
      <TableRow>
        <TableCell>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-8"
            aria-label={isOpen ? `Collapse ${sku}` : `Expand ${sku}`}
            aria-expanded={isOpen}
            onClick={onToggle}
          >
            {isOpen ? <ChevronDown /> : <ChevronRight />}
          </Button>
        </TableCell>
        <TableCell>
          <div className="font-medium">{modelName}</div>
          <div className="text-muted-foreground num text-xs">
            {sku} · {trackingModeLabel(trackingMode)}
          </div>
        </TableCell>
        <TableCell className="text-muted-foreground">{brand ?? "—"}</TableCell>
        <TableCell className="text-muted-foreground">
          {category ?? "—"}
        </TableCell>
        <TableCell className="num text-right">{quantityOnHand}</TableCell>
        <TableCell className="text-right">
          {isQuantity ? (
            <PrintLabelButton target={{ kind: "sku", productId, sku }} />
          ) : null}
        </TableCell>
      </TableRow>
      {isOpen ? (
        <TableRow>
          <TableCell colSpan={6} className="bg-muted/30">
            <StockDrillDown productId={productId} isQuantity={isQuantity} />
          </TableCell>
        </TableRow>
      ) : null}
    </>
  )
}
```

- [ ] **Step 5: Render Brand · Category on the mobile card**

In `StockCard`, destructure `brand` and `category` and add a subtext line under
the model name. Build it so neither, one, or both render cleanly:

```tsx
function StockCard({
  productId,
  sku,
  modelName,
  brand,
  category,
  trackingMode,
  quantityOnHand,
  isQuantity,
  isOpen,
  onToggle,
}: StockItemProps) {
  const brandCategory = [brand, category].filter(Boolean).join(" · ")
  return (
    <div className="bg-card overflow-hidden rounded-lg border">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={isOpen}
        aria-label={isOpen ? `Collapse ${sku}` : `Expand ${sku}`}
        className="flex w-full items-center gap-3 p-4 text-left"
      >
        <span className="text-muted-foreground shrink-0">
          {isOpen ? (
            <ChevronDown className="size-4" />
          ) : (
            <ChevronRight className="size-4" />
          )}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="num font-medium">{sku}</span>
          </div>
          <p className="truncate text-sm">{modelName}</p>
          {brandCategory ? (
            <p className="text-muted-foreground truncate text-xs">
              {brandCategory}
            </p>
          ) : null}
          <p className="text-muted-foreground text-xs">
            {trackingModeLabel(trackingMode)}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <div className="num text-lg leading-none font-semibold">
            {quantityOnHand}
          </div>
          <div className="text-muted-foreground mt-1 text-xs">in stock</div>
        </div>
      </button>
      {isOpen ? (
        <div className="bg-muted/30 space-y-3 border-t p-4">
          {isQuantity ? (
            <PrintLabelButton target={{ kind: "sku", productId, sku }} />
          ) : null}
          <StockDrillDown productId={productId} isQuantity={isQuantity} />
        </div>
      ) : null}
    </div>
  )
}
```

- [ ] **Step 6: Typecheck / lint / build**

Run (from `frontend/`): `bun run build` (or `npx tsc --noEmit && bunx biome check src/routes/_layout/stock.tsx`)
Expected: no type errors, no biome errors.

- [ ] **Step 7: Manual verification**

With `docker compose watch` running, open Inventory > Stock:
- Desktop: Brand and Category columns appear between Product and In stock; a product with no brand/category shows `—`.
- Mobile (narrow viewport): a `Brand · Category` line shows under the model; a product with neither shows no extra line.
- Drill-down (expand a row) still spans the full table width with no layout break.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/routes/_layout/stock.tsx
git commit -m "feat(stock): show brand and category columns"
```

---

## Self-Review

**Spec coverage:**
- Category column → Task 3 (already in payload). ✅
- Brand column → Task 1 (payload) + Task 2 (SDK) + Task 3 (render). ✅
- No prices on Stock → none added. ✅
- Admin Catalog untouched → `products.tsx` not in any task. ✅
- No migration → Task 1 adds a read-only select field only. ✅

**Placeholder scan:** none — every code step shows full code.

**Type consistency:** `StockOnHandRow.brand: str | None` (Py) → `brand: string | null` (TS) → `StockItemProps.brand: string | null` → `brand={r.brand}`. Indices in `stock_on_hand()` row build re-mapped consistently (`r[3]` brand … `r[6]` qty). desktop `colSpan` updated 4 → 6 to match the two new columns.
