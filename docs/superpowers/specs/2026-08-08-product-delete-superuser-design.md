# Product Delete (Superuser Only) — Design

**Date:** 2026-08-08
**Status:** Approved design, pending implementation plan
**Scope:** Hard-delete a product that has never entered the stock system. Superuser only. No migration, no new model, no new component file.

## Problem

The catalog is append-only in practice: a product created by mistake (wrong SKU, wrong brand, a typo made while learning the form) can only be marked Inactive. It stays in the products list, in every product picker, and in the `/products/options` lookup forever. There is no `DELETE /products/{id}` endpoint at all.

Deactivating is the right answer for a product that was real and is now discontinued. It is the wrong answer for a product that never existed as a physical thing.

## Decisions (user-approved)

| Question | Decision |
|---|---|
| Who may delete | **Superuser only** (`is_superuser`). BKK_ADMIN may still create and edit products but sees no delete affordance. |
| Products with history | **Blocked.** Delete is allowed only when the product has never entered the stock system. The append-only ledgers are never touched. Cascade-delete was rejected outright — it would corrupt past sale totals and margin reports. |
| Definition of "no history" | The existing `crud.is_product_fresh()` — no `Unit` row and no `PartBatch` row references the product. This is already the exact condition under which the SKU is editable. |
| Soft vs hard delete | **Hard.** `is_active=false` already covers the soft case; a second soft-delete state would be redundant. |
| Placement | Footer of the existing `EditProductDialog`, not a new table column. |
| Confirmation | **Two-step button** ("Delete" → "Click again to delete"), not a modal. A fresh product has no stock, no sales and no ledger rows, so the blast radius is a name and a price. |
| Audit entry | None. The audit trail is derived from the movement ledgers, and a fresh product by definition has no movements to explain. |

## Backend

One new endpoint in `backend/app/api/routes/products.py`. No change to `models.py`, therefore **no Alembic migration**.

```
DELETE /products/{product_id}
  dependencies=[Depends(get_current_active_superuser)]
  status_code=204, response_class=Response
```

Behaviour:

| Condition | Result |
|---|---|
| Caller is not `is_superuser` | 403 `"The user doesn't have enough privileges"` (from the existing dependency) |
| Caller is unauthenticated | 401 (from the existing dependency chain) |
| Product id does not exist | 404 `"Product not found"` |
| `not crud.is_product_fresh(...)` | 409 `"Product has stock history and cannot be deleted"` |
| Otherwise | 204, product row gone |

The deletion itself lives in `crud.delete_product(*, session, db_product)` per the "all DB access goes through `crud.py`" convention:

1. Delete the product's `PriceChange` rows. They are the only child rows a fresh product is expected to have (`update_product` writes one per changed price field), and they are meaningless once the product is gone.
2. `session.delete(db_product)`, then commit.
3. Wrap the commit in `try/except IntegrityError` → re-raise as HTTP 409 with the same "has history" message. This is the backstop for an unexpected referencing row — most plausibly a `PricingOverrideRequest`, whose `product_id` is not covered by the `is_fresh` check. A 409 is the honest answer there; a 500 is not.

The `is_fresh` re-check inside the endpoint is authoritative. The flag returned to the client on the list response is a rendering hint only and is never trusted.

### Why not a DB-level `ON DELETE CASCADE` on `price_change.product_id`

It would be the more idiomatic database answer, but it costs a migration and an FK rewrite for two lines of application code that only ever run on this one path. If more child tables need the same treatment later, revisit it then.

## Frontend

### `EditProductDialog.tsx` (the only file that changes)

The products table row already opens this dialog on click, so nothing changes in `products.tsx` — no new column, no per-row click-bubbling wrapper (the boundary `PriceHistoryDialog` needs), no duplicate affordance in the mobile card branch.

Footer becomes:

```
[ Cancel ]                                      [ Delete ] [ Save ]
```

- The Delete button renders only when `useRole().isSuperuser && product.is_fresh`. Both conditions must hold; either one false means the button is absent from the DOM, not merely disabled.
- First click switches the button to `variant="destructive"` with the label **"Click again to delete"**. A 4-second timer reverts it to the idle label, so a stray click cannot leave a live confirm sitting in the footer. The timer is cleared on unmount.
- Second click fires the mutation.
- On success: success toast, close the dialog, `queryClient.invalidateQueries({ queryKey: ["products"] })`.
- On error: the existing `handleError` toast. A 409 surfaces as the backend's message, which is the correct thing to show if the product gained stock in another tab between render and click.
- Delete is disabled while a Save mutation is pending, and Save is disabled while a delete is pending.

### SDK

`bun run generate-client` after the backend endpoint exists. `frontend/src/client/` is regenerated, never hand-edited.

## Testing

**Backend** (`backend/tests/api/routes/test_products.py`, matching the existing file's fixtures):

1. Superuser deletes a fresh product → 204, and a follow-up `GET` returns 404.
2. Superuser deletes a fresh product that has price-history rows → 204 (the `PriceChange` children are removed, not left dangling).
3. Superuser deletes a product that has a received unit or part batch → 409, and the product still exists afterwards.
4. BKK_ADMIN (admin but not superuser) → 403.
5. YGN_STAFF → 403.
6. Unknown product id → 404.

**Frontend:** the visibility rule is extracted into a pure `canDeleteProduct(product, isSuperuser)` in `lib/product-edit.ts` — beside the existing `canSaveProduct` — and covered by vitest (`bun run test:unit`). Four cases: superuser + fresh → true; non-superuser + fresh → false; superuser + non-fresh → false; `is_fresh` absent → false (fails closed, matching the reasoning in `hooks/useRole.ts`).

No component-render test: the repo has no jsdom and no React Testing Library, and vitest is scoped to `src/**/*.test.ts`. No Playwright spec either — the E2E suite needs the full stack and carries known pre-existing failures, and a button-visibility assertion adds nothing over the predicate tests plus the backend's four permission tests.

## Out of scope

- Bulk delete, and delete from the list view.
- Any relaxation of the rule for products that *do* have history — that stays a deactivate.
- Restoring or undoing a delete. There is no trash.
