# Product Edit UI — Design

**Date:** 2026-06-19
**Status:** Approved (brainstorming)
**Scope:** Frontend-only. The backend `PATCH /products/{id}` already exists, is admin-only, and records price history.

## Problem

The Products page can **create** and **list** products, but the catalog table is
read-only — there is no UI to edit a product. Because of that, the per-row
**Price history** dialog is always empty ("No price changes recorded"): price
history is only written when a product's `retail_price_thb` / `repair_price_thb`
actually changes via `PATCH /products/{id}` (`crud.update_product`, FR-002), and
nothing in the frontend calls that endpoint.

Add a product **edit** UI so admins can change product details/prices, which makes
the existing price-history feature functional.

## Backend (already in place — no changes)

- `PATCH /products/{id}` → `update_product` route, gated `AdminUser`, passes
  `current_user.id` as `changed_by_user_id`.
- `crud.update_product` writes a `PriceChange` row for each of
  `retail_price_thb` / `repair_price_thb` that changes, in the same transaction.
- `ProductUpdate` accepts: `model_name`, `brand`, `category`, `tracking_mode`,
  `specs`, `retail_price_thb`, `repair_price_thb`, `default_min_stock_level`,
  `is_active`. **`sku` is not editable** (identity).
- SDK: `ProductsService.updateProduct({ productId, requestBody })` → `ProductPublic`.

## Decisions (locked in brainstorming)

- **Editable fields:** Model name (required), Brand, Category, Min stock level
  (int ≥ 0), Retail price THB (required, ≥ 0), Repair price THB (required, ≥ 0).
- **Read-only (shown, disabled):** SKU and Tracking mode — immutable for data
  integrity (changing tracking mode breaks existing units/batches/movements).
- **Trigger:** an **Edit** button per catalog row, beside the existing History
  button, opening a dialog (mirrors the `EditUser` dialog pattern).
- **Out of scope (YAGNI):** `is_active`/deactivate, `specs`, tracking-mode change.

## Components

1. **`src/lib/product-edit.ts`** (new, pure — mirrors `src/lib/product-create.ts`)
   - `ProductEditDraft` — `{ modelName, brand, category, minStock, retailPrice, repairPrice }` (all strings; SKU/tracking are not edited).
   - `canSaveProduct(draft): boolean` — `modelName` non-empty AND `retailPrice` & `repairPrice` are valid non-negative numbers (reuse the create form's `isValidPrice` rule).
   - `buildProductUpdate(draft): ProductUpdate` — trims; always sends `model_name`, `retail_price_thb`, `repair_price_thb` (prices as trimmed strings, like `buildProductPayload`); for `brand`/`category` sends the trimmed value when non-empty else `null` (so clearing a field persists); sets `default_min_stock_level` to the parsed number when valid, else `null` when blank.

2. **`src/components/products/EditProductDialog.tsx`** (new)
   - Props: `{ product: ProductPublic }`.
   - react-hook-form + zod (mirror `EditUser.tsx`): zod schema enforces required `model_name`, optional `brand`/`category`, and `retail_price`/`repair_price` as non-negative-number strings, `min_stock` optional non-negative int.
   - `defaultValues` seeded from `product` (prices via `String(product.retail_price_thb)` etc.).
   - Read-only display of SKU and Tracking mode (disabled `Input`s).
   - Mutation: `updateProduct({ productId: product.id, requestBody: buildProductUpdate(...) })`; `onSuccess` → success toast, close, and `invalidateQueries` for `["products"]` and `["price-history", product.id]`; `onError` → `handleError` toast.
   - Trigger: an outline "Edit" `Button` (a `DialogTrigger`), suitable to sit beside the History button in a table cell.

3. **`src/routes/_layout/products.tsx`** (modify — minimal)
   - In the catalog table's existing History cell, render `<EditProductDialog product={p} />` next to `<PriceHistoryDialog ... />` (wrap the two in a small flex container).
   - This file carries unrelated uncommitted WIP; the change is isolated and only this feature is committed (the WIP is preserved untouched).

## Data flow

Edit click → dialog opens seeded from the row's product → admin edits a price →
Save → `PATCH /products/{id}` → backend writes `PriceChange` rows for changed
prices + updates the product → on success the `["products"]` and
`["price-history", id]` queries are invalidated → catalog shows the new price and
the History dialog now lists the change.

## Error handling

- Backend validation / 4xx → shared `handleError` toast (same as AddUser/EditUser).
- Price `CHECK (>= 0)` is also enforced client-side by the zod schema, so a negative
  price can't be submitted.

## Testing

- **Unit (Playwright pure-logic spec, like `product-create`/`useRole`):**
  `buildProductUpdate` + `canSaveProduct` — required model_name, price validation
  (reject blank/negative/non-numeric), blank brand/category → `null`, min-stock
  number coercion / blank → `null`, prices emitted as trimmed strings.
- **E2E:** as admin, open a product's Edit dialog, change the Retail price, Save,
  then open that product's History dialog and assert it lists a `retail_price_thb`
  row with the old → new values. (Mirror the auth/setup pattern in existing specs.)

## Out of scope / backlog

- Deactivating products (`is_active`), editing `specs`, changing tracking mode.
- Bulk edit. Inline-table editing (a dialog is sufficient).
