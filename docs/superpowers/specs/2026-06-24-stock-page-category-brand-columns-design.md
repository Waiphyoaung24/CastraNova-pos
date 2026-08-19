# Stock page — Category + Brand columns

**Date:** 2026-06-24
**Status:** Approved for planning

## Problem

Client feedback: under **Inventory > Stock**, the list shows only product model
and amount in stock. The category Select filters the list, but category isn't
visible per-row, so staff scanning "All categories" can't tell what category an
item is in. The client wants the Stock view to carry more of the Admin Catalog
information — surfaced for sales staff — while keeping only the Print-labels
action (not the admin-only Edit/History).

## Scope (decided)

- Add **Category** and **Brand** columns to the Stock page.
- **No prices** on Stock (retail/repair stay admin-only on the Catalog).
- **Admin Catalog (`products.tsx`) is untouched** — it keeps Edit/History. The
  "replace edit/history with print labels" feedback is satisfied because the
  staff-facing Stock page already has Print-labels and never had Edit/History.

## Data facts

`StockOnHandRow` (`models.py`) currently returns: `product_id, sku, model_name,
category, tracking_mode, quantity_on_hand`.

- **Category** is already in the payload — frontend-only to display.
- **Brand** is not — requires adding it to the schema and the query. `brand`
  already exists on the `Product` table (`brand: str | None`), so this is a
  read-only field addition: **no migration**.

## Changes

### Backend
- `models.py`: add `brand: str | None` to `StockOnHandRow`.
- `crud.py` `stock_on_hand()`: add `Product.brand` to the `select(...)` and map
  it into the constructed `StockOnHandRow` (`brand=r[...]`). No new query, no
  new filter, no migration.
- Regenerate the SDK: `bun run generate-client`.

### Frontend (`frontend/src/routes/_layout/stock.tsx`)
- Desktop table columns become:
  `[expand] · Product (model + SKU·tracking) · Brand · Category · In stock · [Print]`
- Mobile `StockCard`: add a small `Brand · Category` line under the model name.
- Null brand/category render as `—`.
- `StockItemProps` gains `brand: string | null` (category prop already exists).
- No change to search, the category filter Select, drill-down, or print logic.

## Verification

- Existing Stock pytest + E2E pass unchanged.
- Manually confirm Category and Brand render per row, and `—` shows for a
  product with no brand/category.

## Out of scope (add later if asked)

- Retail/Repair prices on Stock.
- Brand-based search.
- Any Admin Catalog edits.
