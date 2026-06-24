# Stock Table Catalog-Style Column Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the Inventory > Stock desktop table to the Admin Catalog's column layout and styling, keeping every Stock behavior.

**Architecture:** Frontend-only edit to `stock.tsx`. The combined "Product" cell splits into separate SKU / Model / Tracking columns (catalog order, catalog styling), Brand and Category keep their cells, and the expand chevron + In-stock + Print columns stay. No backend, no SDK, no shared component, no change to the Admin Catalog or the mobile cards.

**Tech Stack:** React + TypeScript, shadcn/ui `Table` + `Badge`, biome, tsc.

## Global Constraints

- Frontend-only — no backend or SDK change (`StockOnHandRow` already carries `sku, model_name, brand, category, tracking_mode, quantity_on_hand`).
- Remove nothing: expand chevron, In-stock quantity, Print-labels, tap-to-expand drill-down, and the admin supplier filter all stay.
- No Retail/Repair price columns (prices stay admin-only).
- No shared table component (catalog rows are flat; Stock rows expand — YAGNI).
- Edit/History never rendered on Stock.
- Mobile cards (`StockCard`) unchanged.
- Match existing code style (biome). Touch only `frontend/src/routes/_layout/stock.tsx`.

---

### Task 1: Restyle the Stock desktop table to the catalog layout

**Files:**
- Modify: `frontend/src/routes/_layout/stock.tsx` (desktop `<TableHeader>` in `StockOnHand`, and `StockRow`)
- Verify-only: `frontend/tests/stock-on-hand.spec.ts` (pure `filterStockRows` logic test — must still pass, unchanged)

**Interfaces:**
- Consumes: `StockItemProps` (already has `sku, modelName, brand, category, trackingMode, quantityOnHand, isQuantity, isOpen, onToggle, productId`). No prop changes.
- `Badge` and `trackingModeLabel` are already imported in `stock.tsx` (used by `StockDrillDown`) — no new imports.

- [ ] **Step 1: Replace the desktop table header**

In `StockOnHand`, the desktop branch currently has:

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

Replace it with (split Product → SKU/Model, add Tracking, in catalog order):

```tsx
          <TableHeader>
            <TableRow>
              <TableHead className="w-8" />
              <TableHead>SKU</TableHead>
              <TableHead>Model</TableHead>
              <TableHead>Brand</TableHead>
              <TableHead>Category</TableHead>
              <TableHead>Tracking</TableHead>
              <TableHead className="text-right">In stock</TableHead>
              <TableHead className="w-0" aria-label="Labels" />
            </TableRow>
          </TableHeader>
```

- [ ] **Step 2: Replace the `StockRow` body cells**

`StockRow` currently renders the chevron cell, a combined Product cell, Brand, Category, In-stock, Print, and a drill-down row with `colSpan={6}`. Replace the whole `StockRow` function with this version — separate SKU / Model / Tracking columns using the catalog's styling, `colSpan` bumped to 8, everything else identical:

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
        <TableCell className="num font-medium">{sku}</TableCell>
        <TableCell>{modelName}</TableCell>
        <TableCell className="text-muted-foreground">{brand ?? "—"}</TableCell>
        <TableCell className="text-muted-foreground">
          {category ?? "—"}
        </TableCell>
        <TableCell>
          <Badge variant="secondary">{trackingModeLabel(trackingMode)}</Badge>
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
          <TableCell colSpan={8} className="bg-muted/30">
            <StockDrillDown productId={productId} isQuantity={isQuantity} />
          </TableCell>
        </TableRow>
      ) : null}
    </>
  )
}
```

- [ ] **Step 3: Typecheck**

Run (from `frontend/`): `bunx tsc --noEmit`
Expected: no errors. (No prop signatures changed, so `StockCard` and the call sites in `StockOnHand` remain valid.)

- [ ] **Step 4: Lint the one file**

Run (from `frontend/`): `bunx biome check src/routes/_layout/stock.tsx`
Expected: clean. If biome reports fixable formatting, run `bunx biome check --write src/routes/_layout/stock.tsx` (scoped to this file only — do not run a repo-wide format).

- [ ] **Step 5: Run the page's logic test**

Run (from `frontend/`): `bunx playwright test stock-on-hand.spec.ts`
This is a pure-logic Playwright spec (it imports and calls `filterStockRows` /
`deriveCategories` directly — no browser navigation), so it runs without the dev
server. It must still pass because the filter logic is untouched; no assertion
references table columns.
Expected: PASS. (If the harness can't launch the Playwright runner here, tsc in
Step 3 already covers the unchanged types — the logic under test was not modified.)

- [ ] **Step 6: Manual verification**

With `docker compose watch` running, open Inventory > Stock on a desktop-width viewport:
- Columns appear in order: (expand) · SKU · Model · Brand · Category · Tracking · In stock · (Print).
- SKU is monospace/medium; Brand/Category show `—` when empty; Tracking shows a secondary `Badge` with the readable label (e.g. "Quantity" / "Serialized").
- Click a row's chevron: the drill-down still expands and spans the full table width (no broken layout).
- Print-labels button still renders on QUANTITY rows and still prints.
- Mobile/narrow viewport: the card view is unchanged.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/routes/_layout/stock.tsx
git commit -m "style(stock): adopt catalog column layout for the stock table"
```

---

## Self-Review

**Spec coverage:**
- Catalog column layout/order (SKU·Model·Brand·Category·Tracking) → Steps 1-2. ✅
- Catalog cell styling + Tracking `Badge` with readable label → Step 2. ✅
- Keep expand/drill-down (colSpan 6→8), In-stock, Print → Step 2. ✅
- Supplier filter / mobile cards untouched → not modified (only header + `StockRow` change). ✅
- No prices, no backend/SDK, no shared component, Admin Catalog untouched → nothing else modified. ✅

**Placeholder scan:** none — full code shown for both edits.

**Type consistency:** `StockItemProps` is unchanged, so `StockRow`'s destructure matches the interface and the `<StockRow .../>` / `<StockCard .../>` call sites in `StockOnHand` still pass the same props. `Badge` and `trackingModeLabel` are already imported. `colSpan={8}` matches the 8 `<TableHead>` cells in the new header.
