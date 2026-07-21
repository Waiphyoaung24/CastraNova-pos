# Sale Price-Override Request Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let staff request a price override from the Sale cart (FR-010): tap a line's price → dialog → auto-approved within threshold or held PENDING with live status polling; checkout blocked while pending.

**Architecture:** One new backend read endpoint (`GET /pricing-overrides/{override_id}`, creator-or-admin) so staff can poll their request; SDK regen; pure cart-lib extensions carrying an optional `override` per line; a `PriceOverrideDialog` opened from the ScanCart price cell; per-pending-line `PendingOverrideWatcher` components polling via TanStack Query `refetchInterval`.

**Tech Stack:** FastAPI + SQLModel (backend), pytest, @hey-api generated SDK, React + TanStack Query v5, shadcn/ui, Playwright (browserless lib specs + docker-stack E2E).

**Spec:** `docs/superpowers/specs/2026-07-21-sale-price-override-request-design.md`

## Global Constraints

- Branch: `feat/sale-price-override` (already exists, has the spec commits). PR target: `dev`. Never touch `master`.
- ⚠️ **Backend pytest TRUNCATEs the dev database** (conftest wipes all domain data). The owner is mid-manual-acceptance-pass with hand-seeded data — **confirm with the owner before the first pytest run** (they approved implementation knowing this; re-confirm only if unclear).
- ⚠️ **Never run backend tests via a stale container.** The dev stack must be running under `docker compose watch` (syncs `./backend` → `/app/backend`). Verify the container sees your new code before trusting green (e.g. `docker compose exec backend grep -n "get_pricing_override_endpoint" /app/backend/app/api/routes/pricing_overrides.py`).
- Baselines (do not chase as regressions): backend 576 passed / 3 failed; E2E 253 passed / 17 failed (pre-existing auth-flow specs).
- E2E runs: **always** `E2E_SKIP_DB_RESET=1` (otherwise global.setup truncates + reseeds the shared dev DB).
- The 5% threshold value must **never** appear in UI copy — server-side only.
- Never hand-edit `frontend/src/client/**` — regenerate with `bun run generate-client`. (`schemas.gen.ts` already has an unrelated uncommitted modification in the working tree — leave it alone; only commit the files your regen changes plus it if regen rewrites it.)
- Biome (`bun run lint`) rewrites the whole repo cosmetically on Windows — if you run it, commit only your files.
- All DB access via `crud.py`; routes never query directly. `crud.get_pricing_override` already exists (crud.py:1290) — do not add a new CRUD function.

---

### Task 1: Backend `GET /pricing-overrides/{override_id}` (creator-or-admin)

**Files:**
- Modify: `backend/app/api/routes/pricing_overrides.py`
- Test: `backend/tests/api/routes/test_pricing_overrides.py`

**Interfaces:**
- Consumes: `crud.get_pricing_override(*, session, override_id)` → `PricingOverrideRequest | None` (exists); `app.api.deps.is_admin(user)` (exists); `PricingOverridePublic` (exists).
- Produces: `GET /api/v1/pricing-overrides/{override_id}` → `PricingOverridePublic`; 403 for a non-admin who isn't the creator; 404 for unknown id. Route function name `get_pricing_override_endpoint` with `operation_id`/generated SDK method **`getPricingOverride`** (Task 2 depends on this exact name).

- [ ] **Step 1: Write the four failing tests**

Append to `backend/tests/api/routes/test_pricing_overrides.py` (it already has `_seed_product` and `_create_payload` helpers — reuse them):

```python
def test_get_pricing_override_as_creator(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    pid = _seed_product(db)
    created = client.post(
        "/api/v1/pricing-overrides",
        headers=staff_token_headers,
        json=_create_payload(pid, "970.00"),  # 3% -> AUTO_APPROVED
    ).json()
    r = client.get(
        f"/api/v1/pricing-overrides/{created['id']}", headers=staff_token_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == created["id"]
    assert body["state"] == "AUTO_APPROVED"
    assert body["product_sku"].startswith("OVRAPI-")


def test_get_pricing_override_as_admin(
    client: TestClient,
    staff_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    pid = _seed_product(db)
    created = client.post(
        "/api/v1/pricing-overrides",
        headers=staff_token_headers,
        json=_create_payload(pid, "900.00"),  # 10% -> PENDING
    ).json()
    r = client.get(
        f"/api/v1/pricing-overrides/{created['id']}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "PENDING"


def test_get_pricing_override_other_user_forbidden(
    client: TestClient, staff_token_headers: dict[str, str], db: Session
) -> None:
    from app.models import UserRole
    from tests.utils.user import authentication_token_from_email_with_role

    pid = _seed_product(db)
    created = client.post(
        "/api/v1/pricing-overrides",
        headers=staff_token_headers,
        json=_create_payload(pid, "970.00"),
    ).json()
    other_staff = authentication_token_from_email_with_role(
        client=client, email="staff2@example.com", db=db, role=UserRole.YGN_STAFF
    )
    r = client.get(
        f"/api/v1/pricing-overrides/{created['id']}", headers=other_staff
    )
    assert r.status_code == 403


def test_get_pricing_override_not_found(
    client: TestClient, staff_token_headers: dict[str, str]
) -> None:
    r = client.get(
        f"/api/v1/pricing-overrides/{uuid.uuid4()}", headers=staff_token_headers
    )
    assert r.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose exec backend bash -c "cd /app/backend && pytest tests/api/routes/test_pricing_overrides.py -v"`
Expected: the 4 new tests FAIL with `405 Method Not Allowed` (route missing); the 6 existing tests PASS.

- [ ] **Step 3: Implement the endpoint**

In `backend/app/api/routes/pricing_overrides.py`, extend the deps import and add the route **between** `list_pricing_overrides` and `decide_pricing_override`:

```python
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request

from app.api.deps import AdminUser, CurrentUser, SessionDep, get_admin, is_admin
```

```python
@router.get("/{override_id}", response_model=PricingOverridePublic)
def get_pricing_override_endpoint(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    override_id: uuid.UUID,
) -> PricingOverridePublic:
    """Read one override request (FR-010). The requester polls this while their
    request is PENDING; admins may read any. Anyone else gets 403."""
    override = crud.get_pricing_override(session=session, override_id=override_id)
    if not override:
        raise HTTPException(status_code=404, detail="Override request not found")
    if override.created_by_user_id != current_user.id and not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    product = crud.get_product(session=session, product_id=override.product_id)
    return PricingOverridePublic.model_validate(
        override, update={"product_sku": product.sku if product else ""}
    )
```

(The function is named `get_pricing_override_endpoint` to avoid shadowing confusion with `crud.get_pricing_override`; the SDK method name comes from the operation id, so pass `operation_id` explicitly if the generated name isn't `getPricingOverride` — check in Task 2 Step 1 and, if the generated method is not exactly `PricingOverridesService.getPricingOverride`, rename the route function to `get_pricing_override` instead.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose exec backend bash -c "cd /app/backend && pytest tests/api/routes/test_pricing_overrides.py -v"`
Expected: all 10 PASS.

- [ ] **Step 5: Lint + typecheck backend**

Run: `docker compose exec backend bash -c "cd /app/backend && ruff check app tests && mypy app"`
Expected: no new errors.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/pricing_overrides.py backend/tests/api/routes/test_pricing_overrides.py
git commit -m "feat(overrides): staff-readable GET /pricing-overrides/{id} (FR-010)"
```

---

### Task 2: Regenerate the SDK

**Files:**
- Modify (generated): `frontend/src/client/sdk.gen.ts`, `frontend/src/client/types.gen.ts`, `frontend/src/client/schemas.gen.ts`

**Interfaces:**
- Produces: `PricingOverridesService.getPricingOverride({ overrideId: string })` → `CancelablePromise<PricingOverridePublic>` (Tasks 4–6 depend on this exact call shape).

- [ ] **Step 1: Regenerate**

Run: `cd frontend && bun run generate-client`
Expected: exits 0; `git diff frontend/src/client/sdk.gen.ts` shows a new `getPricingOverride` method on `PricingOverridesService` hitting `GET /api/v1/pricing-overrides/{override_id}` with `path: { override_id: data.overrideId }`.

If the method name is anything other than `getPricingOverride` (e.g. `getPricingOverrideEndpoint`), rename the backend route function to `get_pricing_override` in `pricing_overrides.py` (module-qualified `crud.get_pricing_override` calls inside it still resolve fine), re-run Task 1 Steps 4–5, and regenerate again.

- [ ] **Step 2: Typecheck the frontend**

Run: `cd frontend && bunx tsc -p tsconfig.build.json --noEmit`
Expected: no output (clean).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/client
git commit -m "chore(client): regenerate SDK for getPricingOverride"
```

---

### Task 3: Pure cart + override helpers (TDD, browserless spec)

**Files:**
- Modify: `frontend/src/lib/sale-cart.ts`
- Modify: `frontend/src/lib/pricing-overrides.ts`
- Test: `frontend/tests/sale-cart-override.spec.ts` (new)

**Interfaces:**
- Consumes: `OverrideState` from `@/client/types.gen`; existing `CartLine`/`buildSaleRequest`/`cartSubtotalThb` in `sale-cart.ts`.
- Produces (Tasks 4–5 depend on these exact signatures):
  - `type LineOverride = { id: string; state: OverrideState; requestedPriceThb: number }` (exported from `sale-cart.ts`)
  - `applyOverride(lines: CartLine[], key: string, override: LineOverride): CartLine[]`
  - `clearOverride(lines: CartLine[], key: string): CartLine[]`
  - `lineUnitPriceThb(line: CartLine): number`
  - `cartHasPendingOverride(lines: CartLine[]): boolean`
  - `deviationPct(retailThb: number, requestedThb: number): number` (in `pricing-overrides.ts`)
  - `canSubmitOverride(input: { priceThb: string; reason: string }): boolean` (in `pricing-overrides.ts`)

- [ ] **Step 1: Write the failing spec**

Create `frontend/tests/sale-cart-override.spec.ts`:

```ts
import { expect, test } from "@playwright/test"
import type { OverrideState } from "../src/client/types.gen"
import { canSubmitOverride, deviationPct } from "../src/lib/pricing-overrides"
import {
  applyOverride,
  buildSaleRequest,
  type CartLine,
  cartHasPendingOverride,
  cartSubtotalThb,
  clearOverride,
  type LineOverride,
  lineUnitPriceThb,
  removeLine,
  setLineQuantity,
} from "../src/lib/sale-cart"

// Pure-logic coverage of the FR-010 staff override in the sale cart.
// No browser / React / backend required — mirrors receive-form.spec.ts.

function partLine(key: string, price: number, quantity = 1): CartLine {
  return {
    key,
    lineKind: "PART",
    sku: key,
    productId: `prod-${key}`,
    quantity,
    unitPriceThb: price,
  }
}

function unitLine(key: string, price: number): CartLine {
  return {
    key,
    lineKind: "UNIT",
    barcode: key,
    sku: `sku-${key}`,
    productId: `prod-${key}`,
    quantity: 1,
    unitPriceThb: price,
  }
}

function override(state: OverrideState, requestedPriceThb = 1750): LineOverride {
  return { id: `ovr-${state}`, state, requestedPriceThb }
}

// --- applyOverride / clearOverride -----------------------------------------

test("applyOverride sets the override on the matching line without mutating input", () => {
  const input = [partLine("a", 1800), partLine("b", 500)]
  const next = applyOverride(input, "a", override("AUTO_APPROVED"))
  expect(next[0].override).toEqual(override("AUTO_APPROVED"))
  expect(next[1].override).toBeUndefined()
  expect(input[0].override).toBeUndefined()
  expect(next).not.toBe(input)
})

test("applyOverride with an unknown key returns the same reference", () => {
  const input = [partLine("a", 1800)]
  expect(applyOverride(input, "missing", override("AUTO_APPROVED"))).toBe(input)
})

test("applyOverride replaces an existing override (re-edit)", () => {
  const withPending = applyOverride(
    [partLine("a", 1800)],
    "a",
    override("PENDING", 900),
  )
  const next = applyOverride(withPending, "a", override("APPROVED", 900))
  expect(next[0].override?.state).toBe("APPROVED")
})

test("clearOverride removes the override and restores the retail price", () => {
  const withOverride = applyOverride(
    [partLine("a", 1800)],
    "a",
    override("PENDING", 900),
  )
  const next = clearOverride(withOverride, "a")
  expect(next[0].override).toBeUndefined()
  expect(lineUnitPriceThb(next[0])).toBe(1800)
})

// --- lineUnitPriceThb -------------------------------------------------------

test("lineUnitPriceThb: no override -> retail", () => {
  expect(lineUnitPriceThb(partLine("a", 1800))).toBe(1800)
})

test("lineUnitPriceThb: AUTO_APPROVED and APPROVED -> requested price", () => {
  for (const state of ["AUTO_APPROVED", "APPROVED"] as OverrideState[]) {
    const [line] = applyOverride([partLine("a", 1800)], "a", override(state))
    expect(lineUnitPriceThb(line)).toBe(1750)
  }
})

test("lineUnitPriceThb: PENDING and REJECTED -> retail", () => {
  for (const state of ["PENDING", "REJECTED"] as OverrideState[]) {
    const [line] = applyOverride([partLine("a", 1800)], "a", override(state))
    expect(lineUnitPriceThb(line)).toBe(1800)
  }
})

// --- subtotal / pending gate (S3.5 numbers) ---------------------------------

test("cartSubtotalThb uses approved override prices (2 x 1750 = 3500)", () => {
  const lines = applyOverride(
    [partLine("GAS-R404A", 1800, 2)],
    "GAS-R404A",
    override("AUTO_APPROVED", 1750),
  )
  expect(cartSubtotalThb(lines)).toBe(3500)
})

test("cartSubtotalThb ignores a pending override", () => {
  const lines = applyOverride(
    [partLine("GAS-R404A", 1800, 2)],
    "GAS-R404A",
    override("PENDING", 1750),
  )
  expect(cartSubtotalThb(lines)).toBe(3600)
})

test("cartHasPendingOverride is true only while a PENDING override exists", () => {
  const base = [partLine("a", 1800), unitLine("b", 12000)]
  expect(cartHasPendingOverride(base)).toBe(false)
  const pending = applyOverride(base, "b", override("PENDING", 10000))
  expect(cartHasPendingOverride(pending)).toBe(true)
  for (const state of [
    "AUTO_APPROVED",
    "APPROVED",
    "REJECTED",
  ] as OverrideState[]) {
    expect(cartHasPendingOverride(applyOverride(base, "b", override(state)))).toBe(
      false,
    )
  }
})

// --- buildSaleRequest -------------------------------------------------------

test("buildSaleRequest sends pricing_override_request_id only for AUTO_APPROVED/APPROVED", () => {
  for (const state of ["AUTO_APPROVED", "APPROVED"] as OverrideState[]) {
    const lines = applyOverride([partLine("a", 1800)], "a", override(state))
    const req = buildSaleRequest(lines, "cust-1", "idem-1")
    expect(req.lines[0].pricing_override_request_id).toBe(`ovr-${state}`)
  }
  for (const state of ["PENDING", "REJECTED"] as OverrideState[]) {
    const lines = applyOverride([partLine("a", 1800)], "a", override(state))
    const req = buildSaleRequest(lines, "cust-1", "idem-1")
    expect(req.lines[0].pricing_override_request_id).toBeUndefined()
  }
  const noOverride = buildSaleRequest([partLine("a", 1800)], "cust-1", "idem-1")
  expect(noOverride.lines[0].pricing_override_request_id).toBeUndefined()
})

test("buildSaleRequest still sends no price fields (backend authoritative)", () => {
  const lines = applyOverride(
    [unitLine("BC-1", 12000)],
    "BC-1",
    override("APPROVED", 10000),
  )
  const req = buildSaleRequest(lines, "cust-1", "idem-1")
  expect(req.lines[0]).toEqual({
    line_kind: "UNIT",
    castranova_barcode: "BC-1",
    quantity: 1,
    pricing_override_request_id: "ovr-APPROVED",
  })
})

// --- quantity / removal preserve the override --------------------------------

test("setLineQuantity preserves the override; quantity edits keep the approved unit price", () => {
  const lines = applyOverride(
    [partLine("a", 1800)],
    "a",
    override("AUTO_APPROVED", 1750),
  )
  const next = setLineQuantity(lines, "a", 3)
  expect(next[0].override).toEqual(override("AUTO_APPROVED", 1750))
  expect(cartSubtotalThb(next)).toBe(5250)
})

test("removeLine drops the line together with its override", () => {
  const lines = applyOverride([partLine("a", 1800)], "a", override("PENDING", 900))
  expect(removeLine(lines, "a")).toEqual([])
})

// --- dialog helpers (S3.5 / S3.6 numbers) ------------------------------------

test("deviationPct is signed: (1800 -> 1750) ~ -2.8, (12000 -> 10000) ~ -16.7", () => {
  expect(deviationPct(1800, 1750)).toBeCloseTo(-2.78, 1)
  expect(deviationPct(12000, 10000)).toBeCloseTo(-16.67, 1)
  expect(deviationPct(1000, 1100)).toBeCloseTo(10, 5)
  expect(deviationPct(0, 500)).toBe(0)
})

test("canSubmitOverride requires a positive price and a non-blank reason", () => {
  expect(canSubmitOverride({ priceThb: "1750", reason: "matched quote" })).toBe(true)
  expect(canSubmitOverride({ priceThb: "", reason: "matched quote" })).toBe(false)
  expect(canSubmitOverride({ priceThb: "0", reason: "matched quote" })).toBe(false)
  expect(canSubmitOverride({ priceThb: "-5", reason: "matched quote" })).toBe(false)
  expect(canSubmitOverride({ priceThb: "abc", reason: "matched quote" })).toBe(false)
  expect(canSubmitOverride({ priceThb: "1750", reason: "" })).toBe(false)
  expect(canSubmitOverride({ priceThb: "1750", reason: "   " })).toBe(false)
})
```

- [ ] **Step 2: Run the spec to verify it fails**

Run: `cd frontend && bunx playwright test tests/sale-cart-override.spec.ts --project=chromium --no-deps`
Expected: FAIL — TypeScript/import errors (`applyOverride` etc. not exported).

- [ ] **Step 3: Implement the lib changes**

In `frontend/src/lib/sale-cart.ts` — add the import, the type, extend `CartLineBase`, add the helpers, and update `cartSubtotalThb` / `buildSaleRequest`:

```ts
import type { OverrideState } from "@/client/types.gen"
```

```ts
/** A price-override request attached to a line (FR-010). */
export type LineOverride = {
  /** PricingOverridePublic.id */
  id: string
  state: OverrideState
  requestedPriceThb: number
}
```

`CartLineBase` gains one optional field (after `unitPriceThb`):

```ts
  /** Price-override request for this line, if the operator made one. */
  override?: LineOverride
```

New helpers (place after `removeLine`):

```ts
/** AUTO_APPROVED / APPROVED change the effective price; PENDING / REJECTED don't. */
function overrideActive(o: LineOverride | undefined): o is LineOverride {
  return o !== undefined && (o.state === "AUTO_APPROVED" || o.state === "APPROVED")
}

/** Set/replace the override on the line with `key`; unknown key returns `lines`. */
export function applyOverride(
  lines: CartLine[],
  key: string,
  override: LineOverride,
): CartLine[] {
  if (!lines.some((l) => l.key === key)) return lines
  return lines.map((l) => (l.key === key ? { ...l, override } : l))
}

/** Drop the override on the line with `key` (used when a request is REJECTED). */
export function clearOverride(lines: CartLine[], key: string): CartLine[] {
  return lines.map((l) => (l.key === key ? { ...l, override: undefined } : l))
}

/** Effective unit price: the requested price once approved, else retail. */
export function lineUnitPriceThb(line: CartLine): number {
  return overrideActive(line.override)
    ? line.override.requestedPriceThb
    : line.unitPriceThb
}

/** True while any line's override awaits an admin decision; gates checkout. */
export function cartHasPendingOverride(lines: CartLine[]): boolean {
  return lines.some((l) => l.override?.state === "PENDING")
}
```

Replace `cartSubtotalThb`'s body:

```ts
/** Σ effective unit price × quantity across all lines (display-only). */
export function cartSubtotalThb(lines: CartLine[]): number {
  return lines.reduce((sum, l) => sum + lineUnitPriceThb(l) * l.quantity, 0)
}
```

Replace the `lines.map` inside `buildSaleRequest`:

```ts
    lines: lines.map((l): SaleLineInput => {
      const base =
        l.lineKind === "UNIT"
          ? {
              line_kind: "UNIT" as const,
              castranova_barcode: l.barcode,
              quantity: l.quantity,
            }
          : { line_kind: "PART" as const, sku: l.sku, quantity: l.quantity }
      // Only a decided-approved override is referenced; the backend re-validates
      // it (state, product match) and stays price-authoritative.
      return overrideActive(l.override)
        ? { ...base, pricing_override_request_id: l.override.id }
        : base
    }),
```

In `frontend/src/lib/pricing-overrides.ts` — append:

```ts
/** Signed % deviation of `requested` from `retail`; 0 when retail is not positive. */
export function deviationPct(retailThb: number, requestedThb: number): number {
  if (retailThb <= 0) return 0
  return ((requestedThb - retailThb) / retailThb) * 100
}

/** Override-dialog submit gate: a positive price and a non-blank reason. */
export function canSubmitOverride(input: {
  priceThb: string
  reason: string
}): boolean {
  const price = Number(input.priceThb)
  return (
    input.priceThb.trim() !== "" &&
    Number.isFinite(price) &&
    price > 0 &&
    input.reason.trim() !== ""
  )
}
```

- [ ] **Step 4: Run the spec to verify it passes**

Run: `cd frontend && bunx playwright test tests/sale-cart-override.spec.ts --project=chromium --no-deps`
Expected: all tests PASS.

- [ ] **Step 5: Run the neighbouring pure specs (no regressions)**

Run: `cd frontend && bunx playwright test tests/sale-cart.spec.ts tests/pricing-overrides.spec.ts --project=chromium --no-deps`
Expected: PASS.

- [ ] **Step 6: Typecheck + commit**

Run: `cd frontend && bunx tsc -p tsconfig.build.json --noEmit` — expected clean.

```bash
git add frontend/src/lib/sale-cart.ts frontend/src/lib/pricing-overrides.ts frontend/tests/sale-cart-override.spec.ts
git commit -m "feat(sale): cart override model + pure helpers (FR-010)"
```

---

### Task 4: `PriceOverrideDialog` + ScanCart price trigger and pending badge

**Files:**
- Create: `frontend/src/components/pos/PriceOverrideDialog.tsx`
- Modify: `frontend/src/components/pos/ScanCart.tsx`

**Interfaces:**
- Consumes: `PricingOverridesService.createPricingOverride` (SDK), `canSubmitOverride`/`deviationPct` (Task 3), `CartLine`/`LineOverride`/`lineUnitPriceThb` (Task 3), shadcn `Dialog`/`Badge`/`Button`/`Input`/`Label`, `useCustomToast`.
- Produces (Task 5 depends on these):
  - `PriceOverrideDialog({ line: CartLine | null, onOpenChange: (open: boolean) => void, onCreated: (key: string, override: LineOverride) => void, targetKind: OverrideTargetKind })` — renders open iff `line !== null`.
  - `ScanCart` gains optional prop `onPriceClick?: (key: string) => void`; when set, the price cell is a button labelled `Change price of ${code}`; a PENDING line shows a "Pending approval" badge with the requested price; price/line-total/subtotal all use effective prices.
  - `formatThb` becomes exported from `ScanCart.tsx`.

This task is visual composition over already-tested pure logic — its behavior is covered by the Task 6 E2E; here the gate is a clean typecheck.

- [ ] **Step 1: Create the dialog**

Create `frontend/src/components/pos/PriceOverrideDialog.tsx`:

```tsx
import { useMutation } from "@tanstack/react-query"
import { useEffect, useId, useState } from "react"

import { type OverrideTargetKind, PricingOverridesService } from "@/client"
import { formatThb } from "@/components/pos/ScanCart"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import useCustomToast from "@/hooks/useCustomToast"
import { canSubmitOverride, deviationPct } from "@/lib/pricing-overrides"
import type { CartLine, LineOverride } from "@/lib/sale-cart"

interface PriceOverrideDialogProps {
  /** The cart line being repriced; null keeps the dialog closed. */
  line: CartLine | null
  onOpenChange: (open: boolean) => void
  /** Called with the created override so the caller applies it to the line. */
  onCreated: (key: string, override: LineOverride) => void
  /** "SALE_LINE" on the Sale screen; tickets will reuse with "SERVICE_TICKET_PART". */
  targetKind: OverrideTargetKind
}

/**
 * Staff price-override request (FR-010), opened by tapping a cart line's
 * price. Submits immediately (request-on-save): within the server-side
 * deviation threshold the request comes back AUTO_APPROVED; larger changes
 * come back PENDING for an admin decision. The threshold value itself is
 * intentionally absent from the copy.
 */
export function PriceOverrideDialog({
  line,
  onOpenChange,
  onCreated,
  targetKind,
}: PriceOverrideDialogProps) {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const priceId = useId()
  const reasonId = useId()
  const [price, setPrice] = useState("")
  const [reason, setReason] = useState("")

  // Selecting a line (the parent nulls it on close) starts a fresh form.
  useEffect(() => {
    setPrice("")
    setReason("")
  }, [line?.key])

  const mutation = useMutation({
    mutationFn: (l: CartLine) =>
      PricingOverridesService.createPricingOverride({
        requestBody: {
          target_kind: targetKind,
          product_id: l.productId,
          requested_price_thb: price,
          reason: reason.trim(),
        },
      }),
    onSuccess: (created, l) => {
      onCreated(l.key, {
        id: created.id,
        state: created.state,
        requestedPriceThb: Number(created.requested_price_thb),
      })
      showSuccessToast(
        created.state === "PENDING"
          ? "Sent for admin approval."
          : "Price updated.",
      )
      onOpenChange(false)
    },
    onError: () =>
      showErrorToast("Could not request the price change. Please try again."),
  })

  const parsed = Number(price)
  const pct =
    line !== null &&
    price.trim() !== "" &&
    Number.isFinite(parsed) &&
    parsed > 0
      ? deviationPct(line.unitPriceThb, parsed)
      : null
  const canSubmit =
    line !== null &&
    canSubmitOverride({ priceThb: price, reason }) &&
    !mutation.isPending

  return (
    <Dialog open={line !== null} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Change price</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <p className="text-muted-foreground text-sm">
            Current price: {line ? formatThb(line.unitPriceThb) : ""}. Large
            changes are sent to an admin for approval.
          </p>
          <div className="space-y-2">
            <Label htmlFor={priceId}>New unit price (฿)</Label>
            <Input
              id={priceId}
              inputMode="decimal"
              value={price}
              placeholder={line ? String(line.unitPriceThb) : ""}
              onChange={(e) => setPrice(e.target.value)}
            />
            <p
              aria-live="polite"
              className="text-muted-foreground min-h-5 text-sm"
            >
              {pct !== null
                ? `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}% vs. current price`
                : ""}
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor={reasonId}>Reason</Label>
            <Input
              id={reasonId}
              value={reason}
              maxLength={512}
              placeholder="e.g. matched competitor quote"
              onChange={(e) => setReason(e.target.value)}
            />
          </div>
        </div>
        <DialogFooter>
          <Button
            type="button"
            disabled={!canSubmit}
            onClick={() => line && mutation.mutate(line)}
          >
            {mutation.isPending ? "Saving…" : "Save price"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default PriceOverrideDialog
```

- [ ] **Step 2: Wire the trigger + badge into ScanCart**

In `frontend/src/components/pos/ScanCart.tsx`:

1. Export the formatter (change `function formatThb` to `export function formatThb`).
2. Extend imports:

```tsx
import { Badge } from "@/components/ui/badge"
import {
  type CartLine,
  cartSubtotalThb,
  lineUnitPriceThb,
} from "@/lib/sale-cart"
```

3. Add to `ScanCartProps` and the destructured props:

```tsx
  /** When set, the price cell becomes a tap target to request an override. */
  onPriceClick?: (key: string) => void
```

4. Replace the price `TableCell` (currently `{formatThb(line.unitPriceThb)}`):

```tsx
                <TableCell className="num text-right">
                  {onPriceClick ? (
                    <Button
                      type="button"
                      variant="ghost"
                      className="num h-auto px-2 py-1 underline decoration-dotted underline-offset-4"
                      aria-label={`Change price of ${code}`}
                      onClick={() => onPriceClick(line.key)}
                    >
                      {formatThb(lineUnitPriceThb(line))}
                    </Button>
                  ) : (
                    formatThb(lineUnitPriceThb(line))
                  )}
                  {line.override?.state === "PENDING" ? (
                    <Badge
                      variant="outline"
                      className="mt-1 block w-fit border-amber-500 text-amber-600 dark:text-amber-400"
                    >
                      Pending approval ·{" "}
                      {formatThb(line.override.requestedPriceThb)}
                    </Badge>
                  ) : null}
                </TableCell>
```

5. Replace the line-total cell body: `{formatThb(lineUnitPriceThb(line) * line.quantity)}` (the subtotal below already flows through the updated `cartSubtotalThb`).

- [ ] **Step 3: Typecheck**

Run: `cd frontend && bunx tsc -p tsconfig.build.json --noEmit`
Expected: clean. (If `Badge` import fails, the primitive is `frontend/src/components/ui/badge.tsx` — check its export name.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/pos/PriceOverrideDialog.tsx frontend/src/components/pos/ScanCart.tsx
git commit -m "feat(sale): price-override dialog + tappable price with pending badge"
```

---

### Task 5: Sale screen integration — dialog wiring, pending polling, checkout gate

**Files:**
- Modify: `frontend/src/routes/_layout/sale.tsx`

**Interfaces:**
- Consumes: `PriceOverrideDialog` (Task 4), `applyOverride`/`clearOverride`/`cartHasPendingOverride`/`LineOverride` (Task 3), `PricingOverridesService.getPricingOverride` (Task 2), `useQuery` from `@tanstack/react-query`, `PricingOverridePublic` type.
- Produces: the complete staff flow; `CheckoutPanel` gains `waitingForOverride: boolean`.

- [ ] **Step 1: Extend imports and CheckoutPanel**

In `frontend/src/routes/_layout/sale.tsx`, extend the imports:

```tsx
import { useMutation, useQuery } from "@tanstack/react-query"
import type {
  ApiError,
  CustomerOption,
  PricingOverridePublic,
  SaleCreateRequest,
  SalePublic,
  SaleStaffPublic,
} from "@/client"
import { PricingOverridesService } from "@/client"
import { PriceOverrideDialog } from "@/components/pos/PriceOverrideDialog"
import {
  addScanToCart,
  applyOverride,
  buildSaleRequest,
  cartHasPendingOverride,
  type CartLine,
  clearOverride,
  type LineOverride,
  removeLine,
  setLineQuantity,
} from "@/lib/sale-cart"
```

Add `waitingForOverride: boolean` to `CheckoutPanelProps` and its destructuring, and render helper text under the checkout button (inside the panel's outer `div`, after the `<Button>`):

```tsx
      {waitingForOverride ? (
        <p className="text-muted-foreground text-center text-sm">
          Waiting for override approval
        </p>
      ) : null}
```

- [ ] **Step 2: Add the watcher component**

At the bottom of `sale.tsx` (after the `Sale` component):

```tsx
/**
 * Polls one PENDING override until the admin decides it (FR-010). One instance
 * is rendered per pending line — a component per query keeps hooks out of
 * loops. Unmounts once the decision is applied (the line stops being PENDING).
 */
function PendingOverrideWatcher({
  overrideId,
  lineKey,
  onDecided,
}: {
  overrideId: string
  lineKey: string
  onDecided: (key: string, decided: PricingOverridePublic) => void
}) {
  const { data } = useQuery({
    queryKey: ["pricing-override", overrideId],
    queryFn: () => PricingOverridesService.getPricingOverride({ overrideId }),
    // v5 function form — keep polling every 4s until a decision lands.
    refetchInterval: (query) =>
      query.state.data === undefined || query.state.data.state === "PENDING"
        ? 4_000
        : false,
  })

  useEffect(() => {
    if (data && data.state !== "PENDING") onDecided(lineKey, data)
  }, [data, lineKey, onDecided])

  return null
}
```

- [ ] **Step 3: Wire state, callbacks, gate, and render into `Sale`**

Inside the `Sale` component:

```tsx
  const [overrideKey, setOverrideKey] = useState<string | null>(null)
  const overrideLine = lines.find((l) => l.key === overrideKey) ?? null
```

```tsx
  const handleOverrideCreated = useCallback(
    (key: string, override: LineOverride) => {
      setLines((prev) => applyOverride(prev, key, override))
    },
    [],
  )

  const handleOverrideDecided = useCallback(
    (key: string, decided: PricingOverridePublic) => {
      if (decided.state === "APPROVED") {
        setLines((prev) =>
          applyOverride(prev, key, {
            id: decided.id,
            state: decided.state,
            requestedPriceThb: Number(decided.requested_price_thb),
          }),
        )
        showSuccessToast("Override approved.")
      } else if (decided.state === "REJECTED") {
        setLines((prev) => clearOverride(prev, key))
        showErrorToast("Override rejected — price reverted.")
      }
    },
    [showSuccessToast, showErrorToast],
  )
```

Update the gate:

```tsx
  const waitingForOverride = cartHasPendingOverride(lines)
  const canCheckout =
    lines.length > 0 &&
    customerId !== "" &&
    !mutation.isPending &&
    !waitingForOverride
```

In the JSX: pass `onPriceClick={setOverrideKey}` to `<ScanCart …>`, pass `waitingForOverride={waitingForOverride}` to **both** `CheckoutPanel` instances, and render the dialog + watchers right after `<ScanCart …/>`:

```tsx
          <PriceOverrideDialog
            line={overrideLine}
            onOpenChange={(open) => {
              if (!open) setOverrideKey(null)
            }}
            onCreated={handleOverrideCreated}
            targetKind="SALE_LINE"
          />
          {lines
            .filter((l) => l.override?.state === "PENDING")
            .map((l) =>
              l.override ? (
                <PendingOverrideWatcher
                  key={l.override.id}
                  overrideId={l.override.id}
                  lineKey={l.key}
                  onDecided={handleOverrideDecided}
                />
              ) : null,
            )}
```

- [ ] **Step 4: Typecheck + commit**

Run: `cd frontend && bunx tsc -p tsconfig.build.json --noEmit` — expected clean.

```bash
git add frontend/src/routes/_layout/sale.tsx
git commit -m "feat(sale): wire override dialog, pending polling, checkout gate (FR-010)"
```

---

### Task 6: E2E — auto-approve, pending→approve (live flip), pending→reject

**Files:**
- Test: `frontend/tests/sale-override.spec.ts` (new)

**Interfaces:**
- Consumes: the running docker stack (`docker compose watch`), storageState superuser session (auth.setup), Node-side SDK seeding exactly as `sale.spec.ts` does, `PricingOverridesService.listPricingOverrides`/`decidePricingOverride` for the admin decision.

Note: the browser session is the superuser, but `POST /pricing-overrides` is role-agnostic (CurrentUser) and the decision still comes from the admin API — the flow under test (request → poll → decide → live flip) is identical for staff. The staff-permission split is covered by the Task 1 pytest.

- [ ] **Step 1: Write the spec**

Create `frontend/tests/sale-override.spec.ts`:

```ts
import { expect, test } from "@playwright/test"

import {
  CustomersService,
  LoginService,
  OpenAPI,
  PricingOverridesService,
  ProductsService,
  ReceiptsService,
  SuppliersService,
} from "../src/client"
import { firstSuperuser, firstSuperuserPassword } from "./config.ts"

// FR-010 staff override flow on the Sale screen (S3.5/S3.6 shapes). Node-side
// SDK seeding + admin decisions, browser drives the staff-facing flow.
OpenAPI.BASE = `${process.env.VITE_API_URL}`

const rand = () => Math.random().toString(36).slice(2, 10)

async function authSeedClient() {
  const tok = await LoginService.loginAccessToken({
    formData: { username: firstSuperuser, password: firstSuperuserPassword },
  })
  OpenAPI.TOKEN = tok.access_token
}

interface SeededPart {
  sku: string
  productId: string
  customerName: string
}

/** Seed a sellable QUANTITY (PART) product at ฿1,800 retail with stock. */
async function seedSellablePart(): Promise<SeededPart> {
  const r = rand()
  const product = await ProductsService.createProduct({
    requestBody: {
      sku: `OVR-${r}`,
      model_name: `Override ${r}`,
      tracking_mode: "QUANTITY",
      retail_price_thb: "1800.00",
      repair_price_thb: "500.00",
    },
  })
  const supplier = await SuppliersService.createSupplier({
    requestBody: { name: `Supplier ${r}` },
  })
  const customerName = `Customer ${r}`
  await CustomersService.createCustomer({ requestBody: { name: customerName } })
  await ReceiptsService.receiveQuantity({
    requestBody: {
      product_id: product.id,
      supplier_id: supplier.id,
      received_qty: 10,
      purchase_cost_thb: "900.00",
      idempotency_key: crypto.randomUUID(),
    },
  })
  return { sku: product.sku, productId: product.id, customerName }
}

async function scanCode(page: import("@playwright/test").Page, code: string) {
  const input = page.getByRole("textbox", { name: "Scan barcode" })
  await expect(input).toBeVisible()
  await input.fill(code)
  await input.press("Enter")
}

async function startSale(
  page: import("@playwright/test").Page,
  seeded: SeededPart,
) {
  await page.goto("/sale")
  await page.getByRole("combobox", { name: "Customer" }).click()
  await page
    .getByRole("option", { name: seeded.customerName, exact: true })
    .click()
  await scanCode(page, seeded.sku)
  await expect(
    page.getByRole("cell", { name: seeded.sku, exact: true }),
  ).toBeVisible()
}

/** Fill and submit the override dialog for the line with `sku`. */
async function requestOverride(
  page: import("@playwright/test").Page,
  sku: string,
  price: string,
  reason: string,
) {
  await page.getByRole("button", { name: `Change price of ${sku}` }).click()
  await page.getByLabel("New unit price (฿)").fill(price)
  await page.getByLabel("Reason").fill(reason)
  await page.getByRole("button", { name: "Save price" }).click()
}

/** The browser creates the override; poll the admin list until it appears. */
async function pendingOverrideIdFor(productId: string): Promise<string> {
  let id: string | undefined
  await expect
    .poll(
      async () => {
        const res = await PricingOverridesService.listPricingOverrides({
          state: "PENDING",
          limit: 100,
        })
        id = res.data.find((o) => o.product_id === productId)?.id
        return id
      },
      { timeout: 10_000, intervals: [250, 500, 1_000] },
    )
    .toBeTruthy()
  if (!id) throw new Error("PENDING override not found")
  return id
}

test.describe("Sale price override (FR-010)", () => {
  test.beforeAll(async () => {
    await authSeedClient()
  })

  test("within threshold: override auto-approves and reprices immediately (S3.5 shape)", async ({
    page,
  }) => {
    const seeded = await seedSellablePart()
    await startSale(page, seeded)
    // Second scan merges into the same PART line (quantity 2).
    await scanCode(page, seeded.sku)

    await requestOverride(page, seeded.sku, "1750", "matched competitor quote")

    await expect(page.getByText("Price updated.")).toBeVisible()
    // Effective price + line total + subtotal all show the override (2 × 1750).
    await expect(
      page.getByRole("button", { name: `Change price of ${seeded.sku}` }),
    ).toHaveText("฿1,750.00")
    await expect(page.getByText("฿3,500.00")).toHaveCount(2) // line total + subtotal

    await page.getByRole("button", { name: "Complete sale" }).click()
    await expect(page.getByText("Sale completed.")).toBeVisible()
  })

  test("over threshold: pending blocks checkout, approval flips the price live (S3.6 shape)", async ({
    page,
  }) => {
    const seeded = await seedSellablePart()
    await startSale(page, seeded)

    await requestOverride(page, seeded.sku, "900", "bulk discount")

    await expect(page.getByText("Sent for admin approval.")).toBeVisible()
    await expect(page.getByText(/Pending approval/)).toBeVisible()
    await expect(
      page.getByRole("button", { name: "Complete sale" }),
    ).toBeDisabled()
    await expect(page.getByText("Waiting for override approval")).toBeVisible()

    // Admin decides via the API (Node side) — no reload in the browser.
    const overrideId = await pendingOverrideIdFor(seeded.productId)
    await PricingOverridesService.decidePricingOverride({
      overrideId,
      requestBody: { decision: "APPROVED" },
    })

    // The 4s poll picks the decision up and flips the line without a reload.
    await expect(page.getByText("Override approved.")).toBeVisible({
      timeout: 15_000,
    })
    await expect(
      page.getByRole("button", { name: `Change price of ${seeded.sku}` }),
    ).toHaveText("฿900.00")
    await expect(page.getByText(/Pending approval/)).toHaveCount(0)

    await page.getByRole("button", { name: "Complete sale" }).click()
    await expect(page.getByText("Sale completed.")).toBeVisible()
  })

  test("over threshold: rejection reverts to retail and unlocks checkout", async ({
    page,
  }) => {
    const seeded = await seedSellablePart()
    await startSale(page, seeded)

    await requestOverride(page, seeded.sku, "900", "bulk discount")
    await expect(page.getByText(/Pending approval/)).toBeVisible()

    const overrideId = await pendingOverrideIdFor(seeded.productId)
    await PricingOverridesService.decidePricingOverride({
      overrideId,
      requestBody: { decision: "REJECTED" },
    })

    await expect(
      page.getByText("Override rejected — price reverted."),
    ).toBeVisible({ timeout: 15_000 })
    await expect(
      page.getByRole("button", { name: `Change price of ${seeded.sku}` }),
    ).toHaveText("฿1,800.00")
    await expect(
      page.getByRole("button", { name: "Complete sale" }),
    ).toBeEnabled()
  })
})
```

- [ ] **Step 2: Run the new spec (stack must be up under `docker compose watch`)**

Run: `cd frontend && E2E_SKIP_DB_RESET=1 VITE_API_URL=http://localhost:8000 bunx playwright test tests/sale-override.spec.ts`
Expected: 3 PASS. (`E2E_SKIP_DB_RESET=1` is mandatory — see Global Constraints.)

- [ ] **Step 3: Run the neighbouring sale E2E (no regressions)**

Run: `cd frontend && E2E_SKIP_DB_RESET=1 VITE_API_URL=http://localhost:8000 bunx playwright test tests/sale.spec.ts`
Expected: PASS (this file is not in the 17 known-failing set).

- [ ] **Step 4: Commit**

```bash
git add frontend/tests/sale-override.spec.ts
git commit -m "test(e2e): sale price-override flows — auto-approve, live approve, reject"
```

---

### Task 7: Correct the FR-010 row in the gap analysis (no commit)

**Files:**
- Modify: `docs/plans/2026-07-16-prd-conformance-gap-analysis.md:59` — **do not commit** (the file is intentionally untracked; it belongs to a separate docs workstream).

- [ ] **Step 1: Amend row 010**

Replace line 59:

```
| 010 | Pricing overrides + approval | ⚠️ | Built; sort by deviation fixed. No literal "awaiting approval" status — design refuses creation until approved (confirmed judgment call; **PRD wording amend pending**). |
```

with:

```
| 010 | Pricing overrides + approval | ⚠️ | Backend + admin queue built; staff request flow (sale-cart dialog, 2026-07-21) added — see docs/superpowers/specs/2026-07-21-sale-price-override-request-design.md. Tickets-side request UI still pending (S4.3 follow-up). No literal "awaiting approval" status — design refuses creation until approved (confirmed judgment call; **PRD wording amend pending**). |
```

---

## Final Verification (before review/PR)

- [ ] Backend suite: `docker compose exec backend bash -c "cd /app/backend && pytest"` — expect the 576-passed baseline plus the 4 new tests (3 known failures unchanged). ⚠️ Truncates dev DB — owner already warned.
- [ ] Browserless specs: `cd frontend && bunx playwright test tests/sale-cart-override.spec.ts tests/sale-cart.spec.ts tests/pricing-overrides.spec.ts tests/receive-form.spec.ts --project=chromium --no-deps` — all PASS.
- [ ] E2E: the two runs from Task 6.
- [ ] `cd frontend && bunx tsc -p tsconfig.build.json --noEmit` — clean.
- [ ] Review stage per CLAUDE.md: `requesting-code-review` dispatching `ecc:fastapi-reviewer`, `ecc:react-reviewer`, `ecc:typescript-reviewer`. (Not an append-only/FIFO/role-tiering change — sale consumption paths untouched.)
- [ ] Ship: `create-pr` into `dev` from `feat/sale-price-override`.
