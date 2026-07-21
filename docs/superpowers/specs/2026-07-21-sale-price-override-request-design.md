# FR-010 — Staff price-override request in the Sale cart

**Date:** 2026-07-21 · **Status:** draft (pending owner review)

## Problem

FR-010's backend is complete: `POST /pricing-overrides` is staff-accessible
("Staff request it mid-sale/ticket"), auto-approves within the
`override_deviation_threshold_pct` system setting (5%) and otherwise goes
PENDING with an `OVERRIDE_PENDING` Telegram to admins; `SaleLineInput` accepts
`pricing_override_request_id` and the sale is refused at creation until the
override is approved (recorded design call — no "awaiting approval" sale
status). The admin approval queue (`/pricing-overrides`) and the
override-exceptions report are built.

The staff-side entry point was never built. `sale.tsx` prices lines strictly
from `product.retail_price_thb`; `createPricingOverride` exists in the SDK but
is called nowhere; the cart cannot carry an override. Staff cannot request an
override at all — acceptance items S3.5 and S3.6 are unrunnable, and S7.6 has
no data. The gap analysis marks FR-010 "Built"; that is true of the backend
and admin queue only — correct it alongside this work.

## Decisions (owner, 2026-07-21)

- **Scope:** sales only first. Service tickets (S4.3) are a follow-up reusing
  the same dialog (`target_kind: "SERVICE_TICKET_PART"`).
- **Trigger:** tap the line's price in the cart → dialog (new price, live
  deviation %, required reason).
- **Submit timing:** request-on-save — the dialog immediately calls
  `createPricingOverride`; the response state drives the UX.
- **Pending UX:** auto-refresh the pending request every few seconds
  (TanStack Query `refetchInterval`); checkout blocked while any line is
  PENDING.

## Design

### 1. Backend — `GET /pricing-overrides/{override_id}` (new)

The only read endpoint today is the admin-gated list, so staff have no way to
observe their request's state. Add to
`backend/app/api/routes/pricing_overrides.py`:

- `GET /pricing-overrides/{override_id}` → `PricingOverridePublic`
  (same `product_sku` enrichment as create).
- Permission: requester (`created_by_user_id == current_user.id`) **or**
  admin; anyone else → 403. Unknown id → 404.
- CRUD getter exists (`crud.get_pricing_override` backs `decide`); no
  migration, no model change.
- Regenerate the SDK afterwards (`bun run generate-client`).

### 2. Cart line model — `frontend/src/lib/sale-cart.ts` (pure logic)

`CartLineBase` gains an optional override:

```ts
override?: {
  id: string            // PricingOverridePublic.id
  state: OverrideState  // AUTO_APPROVED | PENDING | APPROVED | REJECTED
  requestedPriceThb: number
}
```

New/changed pure functions (all immutable, mirroring the existing style):

- `applyOverride(lines, key, override)` — set/replace a line's override;
  unknown key returns `lines` unchanged.
- `clearOverride(lines, key)` — drop a line's override (used on REJECTED).
- `lineUnitPriceThb(line)` — requested price when override state is
  `AUTO_APPROVED`/`APPROVED`, else the retail `unitPriceThb`. PENDING and
  REJECTED do **not** change the effective price.
- `cartSubtotalThb` — now sums `lineUnitPriceThb(line) × quantity`.
- `cartHasPendingOverride(lines)` — true if any line's override state is
  PENDING; gates checkout.
- `buildSaleRequest` — adds `pricing_override_request_id: override.id` to a
  line's `SaleLineInput` only when the override state is
  `AUTO_APPROVED`/`APPROVED`. The display subtotal stays display-only; the
  backend remains price-authoritative.
- `setLineQuantity` / `removeLine` — unchanged behavior, must preserve the
  `override` field.

### 3. `PriceOverrideDialog` — `frontend/src/components/pos/PriceOverrideDialog.tsx` (new)

Follows the `CustomerCreateDialog` pattern (shadcn Dialog +
react-hook-form).

- Opened by tapping the line's price (both the desktop table cell and the
  mobile card render make the price a button).
- Fields: **New unit price (฿)** (numeric, > 0), computed **deviation %**
  against retail shown live (helper `deviationPct(retail, requested)`,
  signed, 1 decimal), **Reason** (required, non-blank after trim).
- Save → `PricingOverridesService.createPricingOverride({ target_kind:
  "SALE_LINE", product_id, requested_price_thb, reason })`, then by response
  state:
  - `AUTO_APPROVED` → `applyOverride`, success toast "Price updated", close.
  - `PENDING` → `applyOverride`, info toast "Sent for admin approval", close;
    the line shows an amber **Pending approval** badge with the requested
    price.
- Copy says large deviations need admin approval **without naming 5%** — the
  threshold lives server-side only.
- Re-editing a line simply creates a fresh request and replaces the line's
  override client-side (no cancel endpoint; see Edge cases).
- Network failure → error toast, dialog stays open. Overrides require
  connectivity (approval is an online workflow by nature); the offline sale
  path (§10) is unaffected when no override is attempted.

### 4. Pending auto-refresh — `sale.tsx`

For each line whose override is PENDING, one query. Rules of Hooks: don't
call `useQuery` in a loop — render one tiny `PendingOverrideWatcher`
component per pending line (each owns its own hook and reports via an
`onDecided` callback), or use `useQueries`. Per watcher:

```ts
useQuery({
  queryKey: ["pricing-override", override.id],
  queryFn: () => PricingOverridesService.getPricingOverride({ overrideId }),
  refetchInterval: (query) =>
    query.state.data?.state === "PENDING" ? 4_000 : false,
})
```

(v5 function form — return `false` to stop polling once decided.) On result:

- `APPROVED` → `applyOverride` with the new state; toast "Override approved";
  line price flips to the approved price; checkout unlocks.
- `REJECTED` → `clearOverride`; toast "Override rejected — price reverted";
  checkout unlocks at retail.

Checkout button: `disabled` while `cartHasPendingOverride(lines)` (in
addition to the existing conditions), with helper text "Waiting for override
approval".

## Edge cases

- **Removing a line with a PENDING override** drops it client-side; the
  request stays undecided in the admin queue (no cancel endpoint — accepted;
  admins can reject stale requests). Same applies to abandoning the sale.
- **Re-edit while PENDING** replaces the tracked override with the new
  request's; the superseded one is likewise left for the admin queue.
- **Override is per-unit price**; quantity edits after approval keep the
  approved unit price (`lineUnitPriceThb × quantity`).
- **UNIT and PART lines** both support overrides (S3.6 overrides a
  serialized compressor).
- **Backend re-validation:** sale creation re-checks the referenced override
  server-side (state, product match) — existing `test_sale_override.py`
  coverage; the client never sends a price.

## Out of scope

- Service-ticket overrides (S4.3) — follow-up; the dialog and lib helpers are
  written to be reusable (`target_kind` is a prop).
- A cancel/withdraw endpoint for abandoned PENDING requests.
- Exposing the threshold value via API or UI copy.
- Offline queueing of override requests.

## Test plan

TDD per CLAUDE.md — tests written first in each area.

### Backend (pytest, `backend/tests/api/routes/test_pricing_overrides.py`)

- `test_get_pricing_override_as_creator` — staff creates an override, GET by
  id as the same user → 200, correct `state` and `product_sku`.
- `test_get_pricing_override_as_admin` — GET by id as superuser → 200.
- `test_get_pricing_override_other_user_forbidden` — a different non-admin
  user → 403.
- `test_get_pricing_override_not_found` — random uuid → 404.

### Pure cart logic (browserless Playwright, `frontend/tests/sale-cart-override.spec.ts`)

Mirrors `receive-form.spec.ts` (no browser/backend, run with `--no-deps`):

- `applyOverride` sets the override on the matching line without mutating the
  input array; unknown key returns the same reference.
- `clearOverride` removes the override and restores the retail effective
  price.
- `lineUnitPriceThb`: no override → retail; AUTO_APPROVED and APPROVED →
  requested price; PENDING and REJECTED → retail.
- `cartSubtotalThb` reflects approved override prices and ignores pending
  ones (2 × 1,750 = 3,500 for the S3.5 numbers).
- `cartHasPendingOverride` true only while a PENDING override exists.
- `buildSaleRequest` includes `pricing_override_request_id` only for
  AUTO_APPROVED/APPROVED lines; PENDING/REJECTED/absent send none.
- `setLineQuantity` and `removeLine` preserve/drop the override with the
  line.
- `deviationPct(1800, 1750)` ≈ −2.8; `deviationPct(12000, 10000)` ≈ −16.7
  (S3.5/S3.6 numbers); reason blank/whitespace → dialog invalid.

### E2E (Playwright, `frontend/tests/sale-override.spec.ts`, docker stack)

- **Auto-approve (S3.5):** seed product, sale cart with a PART line, tap
  price, enter within-threshold price + reason → line shows the new price
  immediately; checkout completes; receipt shows the override price.
- **Pending → approve (S3.6):** over-threshold price → Pending badge,
  checkout disabled; approve via the admin API; badge flips to the approved
  price without a reload (poll) and checkout completes.
- **Pending → reject:** reject via the admin API → line reverts to retail,
  toast shown, checkout unlocks.

### Manual acceptance

S3.5 and S3.6 run exactly as written in the test plan (within-threshold
accepted immediately; over-threshold held, OVERRIDE_PENDING Telegram, admin
approves, sale completes at ฿10,000).

## Verification

- All new pytest + Playwright suites green; existing sale/cart specs
  unaffected.
- `bash scripts/test.sh` baseline: 3 pre-existing failures only (known).
- Review stage per CLAUDE.md: `requesting-code-review` dispatching
  `ecc:fastapi-reviewer`, `ecc:react-reviewer`, `ecc:typescript-reviewer`.
  (Not an append-only/FIFO/role-tiering change — sale consumption paths are
  untouched; the FIFO concurrency test still runs in CI-less local suite as
  part of the full pass.)
