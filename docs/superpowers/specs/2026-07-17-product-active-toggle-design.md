# Product active/inactive toggle — UI only

**Date:** 2026-07-17 · **Status:** approved (owner, 2026-07-17)

## Problem

A product's `is_active` flag decides whether it can be sold, received, or used
on a service ticket. Nothing in the frontend can set it.

The flag is reachable only by hand:

```
PATCH /api/v1/products/{id}  {"is_active": false}
```

That is how the 2026-07-17 test data was retired — there is no other way. An
admin running the shop cannot retire a discontinued product, and cannot bring
one back.

The catalog is also silent about it. `products.tsx` renders SKU, Model, Brand,
Category, Tracking, Purchase, Retail, Repair, History — no status. It fetches
**without** `activeOnly`, so retired products *are* listed, just
indistinguishable from live ones. In the seeded data the only clue is the word
"(retired)" typed into the model name by the seed script — a convention, not a
feature. With a real catalog an admin cannot tell a retired SKU from a live
one, or find retired SKUs to reactivate.

Accidental UI gap. Same shape as FR-012: backend complete end to end, control
never built.

## What already exists

Verified, not assumed:

| Layer | State |
|---|---|
| `models.py:447` | `ProductUpdate.is_active: bool \| None` |
| `models.py:414` | `ProductBase.is_active` → so `ProductPublic` carries it |
| `products.py:129` | `update_product` is `AdminUser`-gated |
| `types.gen.ts` | SDK has `is_active` on `ProductPublic` **and** `ProductUpdate` |
| `receive.tsx:139` | pickers already fetch `{ activeOnly: true }` |

So: **no backend change, no migration, no `generate-client` run.** Frontend
only. Verify the OpenAPI/SDK genuinely does not drift rather than assuming it.

Precedent to mirror — the Users admin already solves this exact problem:

- `Admin/columns.tsx:51-62` — status dot (`bg-green-500` / `bg-gray-400`) +
  "Active"/"Inactive", muted text when inactive.
- `EditUser.tsx:243-257` — a **`Checkbox`** labelled "Is active?" inside the
  edit dialog. There is no `switch.tsx` in `components/ui/`; Checkbox is the
  house pattern.

## Design

Three files.

### 1. `frontend/src/lib/product-edit.ts`

Add `isActive: boolean` to `ProductEditDraft`. `productToDraft` seeds it from
`p.is_active`; `buildProductUpdate` emits `is_active`. Pure logic, no new
dependency, no change to `canSaveProduct` — a retired product is still valid.

### 2. `frontend/src/components/products/EditProductDialog.tsx`

One `Checkbox` row labelled **"Active"**, mirroring `EditUser`, with static
helper text:

> Retired products can't be sold, received, or used on tickets. Existing stock
> stays and can still be drained via Adjust.

The existing mutation, toast, `handleError`, and cache invalidation are reused
unchanged. `isUnchanged` (`EditProductDialog.tsx:103`) compares the whole
draft, so it picks up `isActive` with no edit.

### 3. `frontend/src/routes/_layout/products.tsx`

A **Status** column rendering the dot + "Active"/"Inactive", mirroring
`Admin/columns.tsx:51-62`. Data is already on `ProductPublic` — no new query.

## Rejected alternatives

- **Row-level Retire/Reactivate button + confirm dialog.** One click and states
  the consequence explicitly, but adds a new mutation surface and a second path
  to the same field, and breaks the pattern Users set. Two ways to write one
  flag drift apart.
- **Both (dialog switch + row action).** YAGNI (CLAUDE.md §2) unless the shop
  retires in bulk. Nothing suggests it does.
- **Hide retired by default + "Show retired" toggle**, or a **Status filter
  (All/Active/Retired)**. Owner chose neither: keep today's listing behaviour
  and add only the missing signal. Revisit the filter only if the list gets
  noisy.
- **Live on-hand count in the helper text** ("1 unit still on hand").
  `ProductPublic` carries no stock figure, so this needs a new query wired into
  the dialog for a cosmetic line. Static text instead.

## Deliberately not in scope

- **No confirmation dialog.** Retiring is reversible and `EditUser` sets the
  precedent. The helper text carries the consequence.
- **No stock guard on retire.** Retiring a product *with* stock is normal and
  required — `CN-RELAY-OLD` holds 12 units, and stock adjustments are the
  documented drain path for discontinued stock (`notes.md`, `crud.py:2065`).
  Blocking on remaining stock would break that path.
- **No change to `products.tsx` fetching.** It keeps listing all products
  (no `activeOnly`).
- The catalog's inactive-SKU exception for the audit picker is untouched.

## Error handling

Nothing new. `handleError` already covers the PATCH. `update_product` is
`AdminUser`-gated, so a non-admin gets `403` from the existing path; the edit
dialog is only rendered for admins today.

## Testing

Matches this repo's split (no unit runner; `lib/*` pure logic runs as
browserless Playwright specs with `--no-deps`, browser specs need the docker
stack).

1. **Browserless spec** for `product-edit.ts`: `is_active` round-trips
   true→false→true through `productToDraft` → `buildProductUpdate`; an
   untouched draft still emits the product's current value (so opening and
   saving the dialog never silently flips the flag).
2. **Browser spec**: admin edits a product → unchecks Active → Save → the
   Status column reads "Inactive" → the product no longer appears in the
   Receive **serialized** picker. That last step is the one that matters: it
   proves the flag reaches the real active-only picker rather than just
   round-tripping through the form.

Gates before the PR:

- Both specs fail first, then pass (TDD, CLAUDE.md §5 stage 3).
- Full backend suite unchanged. This is a frontend-only change, so it should
  not move the suite at all — but compare failure **names**, never the pass
  count. Three tests fail on a clean tree and are not regressions:
  `test_staff_redaction_lock::test_staff_get_sweep_carries_no_financial_keys`
  (`[/products/]` and `[/project-pulls]`) and
  `test_reports::test_adjacent_month_not_counted`. The pass count depends on
  the branch point (576 on `dev` @ `82e2351`; 580 on `dev-kwg` once the QA
  follow-up tests land), which is exactly why the names are the gate.
- `ecc:react-reviewer` + `ecc:typescript-reviewer` on the diff. This is not
  append-only/FIFO/role-tiering code, so the high-risk DB+security review pair
  is not required.

**Environment trap:** `docker compose up` serves a stale image — `tests/` are
not COPYed into it and arrive only via `docker compose watch` sync, and
Compose syncs on *change*, so files edited before the watch starts never land.
Confirm the container/bundle actually has the symbol under test before
trusting any result.

## Out of scope — tracked separately

Found while seeding the test data for this work; neither is caused by it:

- **FR-012 misses serialized purchases.** `create_sale` writes UNIT lines with
  `unit_id` set and `product_id` NULL, but `_filter_rows_by_customer`
  (`crud.py:4419-4426`) selects `SaleLine.product_id WHERE product_id IS NOT
  NULL`, never joining `unit_id → Unit.product_id`. A customer who bought a
  serialized item does not show that product in the `?customer=` filter —
  exactly the high-value SKUs. Confirmed live: Golden Dragon Hotel bought
  `CN-BOLT-M8` (PART) + `CN-COMP-500` (UNIT); the filter returns only the bolt.
- **Stock-adjustment restock gap.** `create_stock_adjustment` skips the
  inactive guard for *both* signs of `quantity_delta`, so a positive delta
  restocks a retired product. Confirmed live: `+5` on a retired SKU → `200`,
  leaving 11 units that the stock dashboard does not show (it excludes inactive
  products). Owner decision pending; see `notes.md`.
