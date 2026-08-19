# Stock table — adopt Admin Catalog column layout & style

**Date:** 2026-06-24
**Status:** Approved for planning

## Problem

Client wants the Inventory > Stock table to look like the Admin Catalog table
(familiar, consistent layout for sales staff), while keeping all Stock-specific
behavior. Edit/History are admin actions and must not appear on Stock.

## Scope (decided)

- **Frontend-only.** No backend or SDK change. (`StockOnHandRow` already carries
  `sku, model_name, brand, category, tracking_mode, quantity_on_hand`.)
- **Adapt columns + styling only — remove nothing.** Every current Stock feature
  stays: expand chevron, In-stock quantity, Print-labels, tap-to-expand
  drill-down (FIFO batches / serialized units), and the admin supplier filter.
- **No prices.** Retail/Repair stay admin-only on the Catalog.
- **No shared component extraction.** Catalog rows are flat; Stock rows expand
  into drill-downs — a shared table abstraction is more cost than reuse (YAGNI).
  Restyle the Stock table in place, reusing the same shadcn `Table` + `Badge`
  primitives the catalog already uses.
- **Edit/History** never rendered on Stock (they only ever lived on the catalog).

## Change (`frontend/src/routes/_layout/stock.tsx`)

### Desktop table
Current combined "Product" cell (model bold + `sku · trackingLabel` subtext)
splits into separate columns, in the catalog's order, with Stock extras kept:

`[expand] · SKU · Model · Brand · Category · Tracking · In stock · [Print]`

Column header row:
`<TableHead className="w-8" />` (expand) · `SKU` · `Model` · `Brand` · `Category`
· `Tracking` · `<TableHead className="text-right">In stock</TableHead>` ·
`<TableHead className="w-0" aria-label="Labels" />`.

Cell styling copied from the catalog (`products.tsx`):
- SKU: `<TableCell className="num font-medium">{sku}</TableCell>`
- Model: `<TableCell>{modelName}</TableCell>`
- Brand: `<TableCell className="text-muted-foreground">{brand ?? "—"}</TableCell>`
- Category: `<TableCell className="text-muted-foreground">{category ?? "—"}</TableCell>`
- Tracking: `<TableCell><Badge variant="secondary">{trackingModeLabel(trackingMode)}</Badge></TableCell>`
  (catalog's badge style, Stock's readable label inside — approved.)
- In stock: unchanged — `<TableCell className="num text-right">{quantityOnHand}</TableCell>`
- Print: unchanged — `PrintLabelButton` for QUANTITY rows.

Drill-down row `colSpan` updates **6 → 8** to span all columns.

### Mobile cards
Left as-is. The catalog has no mobile/card view to match, and the cards already
show SKU, Model, Brand · Category, Tracking, and quantity. Nothing removed.

## Verification

- `filterStockRows` unit test (`frontend/tests/stock-on-hand.spec.ts`) still
  passes — filter logic is untouched.
- `tsc --noEmit` and `biome check src/routes/_layout/stock.tsx` clean.
- Manual: columns render in catalog order; `—` shows for null brand/category;
  Tracking badge shows the readable label; expand still works and the drill-down
  spans the full table width; Print-labels still works; supplier filter (admin)
  unchanged.

## Out of scope

- Retail/Repair prices on Stock.
- Any change to the Admin Catalog page.
- Backend / SDK changes.
- A shared table component.
