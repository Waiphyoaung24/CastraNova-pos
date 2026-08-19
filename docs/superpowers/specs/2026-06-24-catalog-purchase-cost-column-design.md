# Admin Catalog — "Purchase" (latest cost) column

**Date:** 2026-06-24
**Status:** Approved for planning
**Risk:** HIGH (cost/COGS data) — run test → review with `ecc:database-reviewer` + `ecc:security-reviewer`.

## Problem

The Admin Catalog (`products.tsx`) shows Retail and Repair prices but not what
the shop *paid*. Admin wants a "purchase price" column to eyeball margin.

## Key facts (drove the design)

- A `Product` has **no single purchase cost** (`models.py:368`: "No
  purchase_cost: SERIALIZED cost lives on unit, QUANTITY on part_batch").
  Purchase cost is recorded per receipt — `PartBatch.purchase_cost_thb`
  (QUANTITY) or `Unit.purchase_cost_thb` (SERIALIZED) — and varies per delivery.
  Both carry `received_at` (the FIFO sort key).
- **"Purchase price" = the latest purchase cost** (most recent receipt by
  `received_at`). Products never received show `—`. (Decided.)
- `GET /products/` is gated by `get_current_user` — **staff-accessible**. The
  catalog *page* is admin-only on the frontend, but the API is not. Therefore
  cost MUST NOT be added to `ProductPublic` (would leak COGS to staff via the
  API). COGS-stays-admin-only is a project-wide invariant.

## Approach (decided)

Separate admin-only endpoint, merged client-side. `ProductPublic` and
`GET /products/` are left unchanged.

### Backend
- `crud.latest_purchase_costs(*, session) -> dict[uuid.UUID, Decimal]`:
  for each product, the `purchase_cost_thb` of the most recent receipt — newest
  `PartBatch` (QUANTITY) or newest `Unit` (SERIALIZED) by `received_at DESC`.
  Set-based, **no N+1** (e.g. `DISTINCT ON (product_id) ... ORDER BY product_id,
  received_at DESC` per source, combined; product wins = max `received_at`
  across whichever source applies). Never-received products are absent from the
  map.
- New response schema `ProductPurchaseCost` (SQLModel): `product_id: uuid.UUID`,
  `latest_purchase_cost_thb: Decimal`.
- New route `GET /products/purchase-costs`,
  `response_model=list[ProductPurchaseCost]`,
  `dependencies=[Depends(get_admin)]`. Returns one entry per product that has at
  least one receipt.
- Regenerate the SDK (`bun run generate-client`).

### Frontend (`products.tsx`)
- Add a TanStack Query for the new endpoint; build `Map<product_id, cost>`.
- Add a **"Purchase"** column (header right-aligned), placed immediately before
  Retail and Repair so the money columns group together. Cell:
  `num text-right`, `formatThb(cost)`, or `—` when the product id is absent
  from the map. THB only (matches Retail/Repair).
- No new frontend role logic — page is already `requireAdmin`.

## Verification (high-risk)

- **Security:** `GET /products/purchase-costs` returns **403 for staff**, 200
  for admin.
- **No leak:** `ProductPublic` / `GET /products/` response is unchanged — no
  cost field present (assert in a staff-token product-list test).
- **Correctness:** QUANTITY product with two batches → newest batch's cost wins;
  SERIALIZED product with multiple units → newest unit's cost wins; product
  with no receipts → absent from the response.
- Frontend: tsc + biome clean; column renders `—` for never-received products.

## Out of scope

- Weighted-average / range cost, or a manual standard-cost field on Product.
- Any change to the Stock page or to `ProductPublic`.
- Showing cost to non-admin users anywhere.
