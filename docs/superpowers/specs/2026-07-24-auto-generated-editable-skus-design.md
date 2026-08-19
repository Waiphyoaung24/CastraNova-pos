# Auto-generated, editable-while-fresh product SKUs

**Date:** 2026-07-24
**Status:** Design approved, pending spec review

## Problem

Product SKUs are typed by hand at create time and are immutable forever after.
Two gaps:

1. **No help at create.** Staff invent a SKU string manually, so formats drift
   and typos are easy.
2. **No way to fix a mistake.** If a SKU is wrong (e.g. because the model name
   was mistyped), it can never be corrected — there isn't even a product delete
   endpoint to fall back on.

Goal: **auto-suggest** the SKU from other fields at create time while keeping it
a normal editable input, and **allow correcting** the SKU after create, but only
while the product is still "fresh" (no stock, no transactions).

## Key facts established during exploration

- Everything references a product by its **UUID** foreign key — *except* one
  artifact: `PartBatch.batch_no`, which bakes the SKU string in at receive time
  (`crud.next_batch_no` → `YYYYMMDD-{SKU}-###`). Unit barcodes are `CN-{random}`
  (no SKU). So changing the SKU string can only ever desync `batch_no`, nothing
  else.
- `batch_no` rows only exist after a **receive** (which creates a `PartBatch` or
  `Unit`). No sale line, movement, service-ticket part, or project pull can
  exist without stock first. Therefore **"no `Unit` rows AND no `PartBatch`
  rows" ⇒ the product has zero SKU-embedded or SKU-referencing history** = safe
  to rename.
- There is **no product delete endpoint**, so "delete + recreate" is not a
  cheaper alternative — it would need its own freshness-guarded endpoint and has
  worse UX.
- `ProductUpdate` today has **no `sku` field** (SKU immutable post-create).
- Price changes (`PriceChange`) don't embed the SKU and aren't stock usage, so
  they do **not** count against freshness.

## Part A — Auto-suggest SKU at create (frontend only)

No backend/API/migration change. The SKU is still a required, unique string the
backend receives as-is.

### Pure helpers — `frontend/src/lib/product-create.ts`

- `slugify(s: string): string` — uppercase; replace each run of non-`[A-Z0-9]`
  with a single `-`; strip leading/trailing `-`.
- `generateSkuBase({ brand, modelName }): string` —
  `slugify([brand, modelName].filter(Boolean).join(" "))`. Empty brand ⇒ model
  only; empty model ⇒ `""`.
- `randomSkuSuffix(): string` — 4 chars from `A–Z0–9` via
  `crypto.getRandomValues` (browser runtime).
- `buildAutoSku(base, suffix): string` — `` base ? `${base}-${suffix}` : "" ``.

Format chosen: **Brand + Model + 4-char random suffix**, e.g.
`APPLE-IPHONE-15-PRO-7K2A`. The suffix keeps auto-generated SKUs from colliding;
the existing create-time 409-on-duplicate path remains the backstop.

### `ProductCreateDialog.tsx`

- New state: `skuDirty` (bool, default `false`) and `skuSuffix` (minted once via
  lazy `useState(randomSkuSuffix)`).
- Effect (deps `brand`, `modelName`, `skuSuffix`, `skuDirty`): while `!skuDirty`,
  `setSku(buildAutoSku(generateSkuBase({ brand, modelName }), skuSuffix))`.
- SKU `onChange(v)`: `setSku(v); setSkuDirty(v.trim() !== "")` — a manual
  non-empty edit locks auto-fill; clearing the field to empty resumes it.
- `reset()` additionally does `setSkuDirty(false)` and
  `setSkuSuffix(randomSkuSuffix())` (fresh suffix per dialog session).
- Hint under the SKU field: *"Auto-generated from brand + model — edit to
  override."*

`canCreateProduct` is unchanged (still requires a non-empty SKU — now satisfied
automatically once a model name is entered).

### Tests

`frontend/src/lib/product-create.test.ts` (vitest, pure): slugify cases (spaces,
symbols, leading/trailing separators, empty), base fallback with no brand,
suffix length/charset, `buildAutoSku` empty-base ⇒ `""`.

## Part B — Edit SKU while fresh (backend + frontend)

### Backend

- `crud.is_product_fresh(*, session, product_id) -> bool` — `True` iff no `Unit`
  and no `PartBatch` row references the product (two existence queries).
- `crud.products_fresh_ids(*, session, product_ids) -> set[UUID]` — batched
  version for the list: the given ids minus any appearing in `Unit` or
  `PartBatch` (one `.in_(...)` query each, no N+1).
- `ProductUpdate` gains `sku: str | None = Field(default=None, max_length=64)`.
- `crud.update_product`: when `sku` is present in the update and differs from the
  current value:
  - if `not is_product_fresh(...)` → `HTTPException(409, "SKU can only be changed
    before the product has any stock or transactions.")`
  - otherwise apply it and wrap `session.commit()` in `try/except IntegrityError`
    → `rollback()` + `HTTPException(409, "SKU already exists")` (mirrors
    `create_product`; required because a duplicate SKU on update would otherwise
    surface as a 500).
- `ProductPublic` gains `is_fresh: bool`. It is **computed, not stored** (no
  migration). `products.py` builds `ProductPublic` explicitly at each return
  site:
  - `read_products` (list): batched via `products_fresh_ids`; `is_fresh = id in
    fresh`.
  - `create_product`: `is_fresh = True` (brand new).
  - `update_product` / `set_min_stock_level` responses: `is_fresh =
    is_product_fresh(...)`.

### Frontend

- Regenerate the SDK on the host (never in the frontend container).
- `EditProductDialog.tsx`: render the SKU field. Editable only when
  `product.is_fresh`; otherwise disabled/read-only with hint *"Locked — product
  already has stock or history."* Add `sku` to the draft/patch state and include
  it in the update payload only when it changed. The products list already
  carries `is_fresh` per row, which feeds the dialog.

### Tests

- Backend (`tests/api/routes/test_products.py`): fresh-product SKU edit succeeds;
  after a receive, SKU edit → 409; duplicate SKU on update → 409; list `is_fresh`
  is `True` before any receive and `False` after.
- Frontend: Part A unit tests cover the pure logic. Dialog gating is stack-level
  (backend-enforced); no new unit test — optional E2E only if requested.

### Migration

None. `ProductUpdate` and `ProductPublic` are schemas, not tables, and `is_fresh`
is derived at read time.

## Out of scope

- SKU editing on products that already have stock/history (intentionally
  blocked).
- A product delete endpoint.
- Changing how `batch_no` embeds the SKU (historical batch numbers are immutable
  audit records and are unaffected, since editing is only allowed pre-receive).
