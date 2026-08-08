# Prefill purchase cost on a positive stock adjustment

**Date:** 2026-08-08
**Status:** Approved, ready for planning
**Scope:** Frontend only — `frontend/src/routes/_layout/stock-adjustment.tsx`, `frontend/src/lib/stock-adjustment.ts`, one new unit test file.

## Problem

On the Stock adjustment screen (Quantity SKU → Found / Lost), typing a positive
quantity delta reveals an empty **Purchase cost (THB)** field. The admin has to
recall or look up what that SKU last cost and type it by hand, every time. The
number is already in the system.

## Requirement

When the cost field appears — i.e. when the user types a positive quantity delta
for a SKU — fill it with that SKU's most recent purchase cost, editable.

## Data source

No backend change and no SDK regeneration.

`GET /api/v1/search/sku/{sku}` (`SearchService.searchSku`) returns
`SkuSearchAdminResult` for admins, whose `batches[]` are ordered **oldest-first**
and carry `purchase_cost_thb`. The last element is therefore the newest batch —
the same definition of "latest purchase cost" that `crud.latest_purchase_costs`
uses for the Products page.

The Stock adjustment route is guarded by `requireAdmin()`, so the admin variant
of the union is what the page receives. Staff never reach this screen, and the
staff variant of the response carries no cost, so the narrowing degrades to "no
suggestion" rather than leaking anything.

Rejected alternatives:

- `GET /products/purchase-costs` — keyed by `product_id`, which this form does
  not have. Using it would need a second full-catalog fetch to map SKU →
  product_id.
- Adding `latest_purchase_cost_thb` to `SkuSearchAdminResult` — the value is
  already derivable from `batches`; a new field means a backend change, an SDK
  regen, and a second source of truth for the same number.

## Fetch trigger

A `useQuery` in `stock-adjustment.tsx`:

- `queryKey: ["search-sku", sku]` — the same key `search.tsx` uses, so the two
  screens share a cache entry, and the existing
  `invalidateQueries({ queryKey: ["search-sku"] })` in this page's adjustment and
  return `onSuccess` handlers already refreshes the suggestion after a write.
- `queryFn: () => SearchService.searchSku({ sku })`
- `retry: false` — a 404 for a SKU that does not exist is an ordinary outcome
  here, not a transient failure.
- `enabled: showCost && sku.length > 0`, where `showCost` is the existing
  condition that reveals the field (QUANTITY target, `ADJUST` action, delta
  parses and is `> 0`).

Gating on `showCost` is what makes typing the delta the trigger, as specified.

## Prefill mechanics

No `useEffect`, no writing fetched data into form state. A pure helper in
`lib/stock-adjustment.ts`:

```ts
/** Newest batch for a SKU (search returns them oldest-first) — the default cost
 *  basis for a positive adjustment. Null for staff results, SERIALIZED SKUs, and
 *  SKUs that have never been received. */
export function latestCostBatch(
  res: SkuSearchAdminResult | SkuSearchResult | undefined,
): SkuBatchAdminPublic | null
```

Implementation: take the last element of `res?.batches`, return it only when
`"purchase_cost_thb" in batch`, else `null`. Index it rather than using
`.at(-1)` — `frontend/tsconfig.json` targets ES2020 and `Array.prototype.at` is
ES2022.

The component then derives the draft it actually uses:

```ts
const suggested = latestCostBatch(costQuery.data)
const effectiveDraft =
  draft.purchaseCost === "" && suggested
    ? { ...draft, purchaseCost: suggested.purchase_cost_thb }
    : draft
```

`effectiveDraft` feeds three places: the input's `value`,
`canSubmitAdjustment(...)`, and the submitted payload. Typing overwrites the
suggestion; clearing the field brings it back.

The submit mutation takes the draft as a mutation variable
(`mutationFn: (d: AdjustmentDraft) => ...`, called as
`mutation.mutate(effectiveDraft)`), mirroring the existing `returnMutation`
pattern in the same file. Reading `draft` from the closure would post the empty
cost the user never typed.

`onSuccess` already resets the draft, which clears the SKU and delta, disables
the query, and drops the suggestion — no extra teardown.

## Presentation

When `suggested` is non-null, a helper line under the field:

> Last received at ฿58.00 on 12 Jul 2026.

Formatted with the same `.toLocaleDateString()` used elsewhere on this page. When
`suggested` is null the field renders exactly as it does today, placeholder and
all.

## Failure modes

| Case | Behaviour |
| --- | --- |
| SKU not found (404) | No suggestion, field stays empty and manual. No toast. |
| SERIALIZED SKU | `batches` is empty → no suggestion. Server rejects the adjustment on submit as it does today. |
| Product exists, never received | `batches` empty → no suggestion. |
| Staff-shaped response | Narrowing fails → no suggestion. Unreachable in practice (admin-guarded route). |
| Request in flight | Field renders empty; the suggestion appears when it resolves, provided the user has not typed. |

A missing suggestion is not an error state and produces no error UI. Nothing that
submits today is blocked by this change.

## Accepted simplification

Editing the SKU *after* a positive delta is already entered fires one request per
keystroke, most of them 404s. No debounce: the normal flow is SKU-then-delta, and
this is a low-traffic admin-only screen. Marked in the code with a `ponytail:`
comment naming the ceiling and the upgrade path (debounce the SKU, or commit it
on blur/scan like `search.tsx` does with its `term` state).

## Testing

New `frontend/src/lib/stock-adjustment.test.ts` (vitest, `bun run test:unit`),
covering `latestCostBatch`:

- admin result with several batches → returns the last one (newest)
- admin result with one batch → returns it
- `batches: []` → `null`
- staff-shaped batches (no `purchase_cost_thb`) → `null`
- `undefined` input → `null`

The existing `canSubmitAdjustment` / `buildAdjustmentPayload` behaviour is
unchanged and needs no new coverage; the prefill reaches them as an ordinary
non-empty `purchaseCost`.

An E2E assertion in `frontend/tests/stock-adjustment.spec.ts` (positive delta on
a seeded QUANTITY SKU → field shows the seeded batch cost) is optional and only
worth adding if the seed data guarantees a received batch for a known SKU.

## Out of scope

- The Return sub-tab (refund price is the sale price and is not editable).
- The Serialized unit tab (no cost field).
- Any change to how the backend derives or validates `purchase_cost_thb`.
