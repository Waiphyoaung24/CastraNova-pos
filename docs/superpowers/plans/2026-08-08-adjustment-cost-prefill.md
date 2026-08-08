# Adjustment Purchase-Cost Prefill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On the Stock adjustment screen, when an admin types a positive quantity delta for a SKU, prefill the Purchase cost (THB) field with that SKU's most recent batch cost, editable.

**Architecture:** Frontend only. The admin-scoped `GET /search/sku/{sku}` response already carries `batches[]` (oldest-first) with `purchase_cost_thb`, so no backend or SDK change is needed. A pure helper picks the newest batch; the route component derives an "effective draft" from the fetched value rather than syncing it into form state with an effect.

**Tech Stack:** React 19, TypeScript, TanStack Query v5, TanStack Router, vitest, biome, bun.

**Spec:** `docs/superpowers/specs/2026-08-08-adjustment-cost-prefill-design.md`

## Global Constraints

- Never hand-edit `frontend/src/client/` or `frontend/src/routeTree.gen.ts` — both are generated. This plan touches neither.
- No backend change, no Alembic migration, no `bun run generate-client`.
- Lint/format is biome, not ESLint/Prettier: `bun run lint` from `frontend/`.
- Unit tests are vitest: `bun run test:unit` from `frontend/`. Playwright specs in `frontend/tests/` are never collected by vitest.
- All commands in this plan run from `frontend/` unless stated otherwise.
- Currency copy uses the `฿` symbol and the `num` CSS class on numeric spans/inputs, matching the rest of `stock-adjustment.tsx`.
- Work on a fresh branch cut from `dev` (see Task 0). Never target or push `master`.

---

## File Structure

| File | Responsibility | Action |
| --- | --- | --- |
| `frontend/src/lib/stock-adjustment.ts` | Pure form logic for the adjustment screen. Gains `latestCostBatch`, which picks the newest cost-bearing batch out of a SKU search result. | Modify |
| `frontend/src/lib/stock-adjustment.test.ts` | vitest coverage for the above. | Create |
| `frontend/src/routes/_layout/stock-adjustment.tsx` | The screen. Gains the cost lookup query, the derived effective draft, the helper line, and a mutation that takes the draft as a variable. | Modify |
| `docs/superpowers/specs/2026-08-08-adjustment-cost-prefill-design.md` | The approved design. Already written, needs committing. | Commit |

Two tasks. Task 1 is pure logic with real unit tests. Task 2 is the wiring, which a reviewer could reject independently (it changes how the existing mutation is invoked).

---

## Task 0: Branch off `dev` and commit the spec

**Files:**
- Commit: `docs/superpowers/specs/2026-08-08-adjustment-cost-prefill-design.md`

**Interfaces:**
- Consumes: nothing.
- Produces: a branch named `feat/adjustment-cost-prefill` based on `origin/dev`, with the spec committed as its first commit.

- [ ] **Step 1: Cut the branch from `dev`**

The current working branch (`feat/product-delete-superuser`) is unrelated work. Run from the repo root:

```bash
git fetch origin
git checkout -b feat/adjustment-cost-prefill origin/dev
```

The untracked spec file follows the checkout — it is untracked, so it is not left behind.

- [ ] **Step 2: Verify the spec file is present and the branch is right**

```bash
git status --short --branch
```

Expected: branch line shows `## feat/adjustment-cost-prefill...origin/dev`, and the spec appears as `?? docs/superpowers/specs/2026-08-08-adjustment-cost-prefill-design.md`.

- [ ] **Step 3: Commit the spec**

```bash
git add docs/superpowers/specs/2026-08-08-adjustment-cost-prefill-design.md
git commit -m "docs(stock-adjustment): design for purchase-cost prefill"
```

---

## Task 1: `latestCostBatch` helper

**Files:**
- Modify: `frontend/src/lib/stock-adjustment.ts` (add the import line at the top and the new export at the end; do not touch the existing functions)
- Create: `frontend/src/lib/stock-adjustment.test.ts`

**Interfaces:**
- Consumes: generated types `SkuBatchAdminPublic`, `SkuSearchAdminResult`, `SkuSearchResult` from `@/client/types.gen`.
- Produces:
  ```ts
  export function latestCostBatch(
    res: SkuSearchAdminResult | SkuSearchResult | undefined,
  ): SkuBatchAdminPublic | null
  ```
  Task 2 calls this with `costQuery.data` and reads `.purchase_cost_thb` (a `string`) and `.received_at` (an ISO `string`) off the result.

**Background the implementer needs:**

`GET /search/sku/{sku}` returns a union — `SkuSearchAdminResult` for admins (batches carry `purchase_cost_thb`) and `SkuSearchResult` for staff (batches do not). The generated response type is `SkuSearchAdminResult | SkuSearchResult`, so TypeScript will not let you read `purchase_cost_thb` off a batch without narrowing. Narrow with an `in` check, not a cast.

The backend orders batches **oldest-first** (`crud.search_sku`, `.order_by(PartBatch.received_at, PartBatch.id)`), so the newest batch is the **last** element. SERIALIZED products return `batches: []`.

`frontend/tsconfig.json` sets `"lib": ["ES2020", ...]`, and `Array.prototype.at` is ES2022 — it will not typecheck. Index with `batches[batches.length - 1]` instead.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/stock-adjustment.test.ts`:

```ts
import { describe, expect, it } from "vitest"

import type {
  SkuBatchAdminPublic,
  SkuBatchPublic,
  SkuSearchAdminResult,
  SkuSearchResult,
} from "@/client/types.gen"

import { latestCostBatch } from "./stock-adjustment"

function adminBatch(
  batchNo: string,
  receivedAt: string,
  cost: string,
): SkuBatchAdminPublic {
  return {
    batch_no: batchNo,
    received_at: receivedAt,
    received_qty: 10,
    remaining_qty: 10,
    is_adjustment: false,
    purchase_cost_thb: cost,
  }
}

function adminResult(batches: SkuBatchAdminPublic[]): SkuSearchAdminResult {
  return {
    sku: "HPEOK-D-48-O93D",
    product_id: "11111111-1111-1111-1111-111111111111",
    tracking_mode: "QUANTITY",
    total_on_hand: 20,
    batches,
    consumption: [],
  }
}

describe("latestCostBatch", () => {
  it("returns the last batch — the backend orders them oldest-first", () => {
    const res = adminResult([
      adminBatch("B-1", "2026-05-01T00:00:00Z", "50.00"),
      adminBatch("B-2", "2026-06-01T00:00:00Z", "55.00"),
      adminBatch("B-3", "2026-07-12T00:00:00Z", "58.00"),
    ])
    expect(latestCostBatch(res)?.purchase_cost_thb).toBe("58.00")
  })

  it("returns the only batch when there is one", () => {
    const res = adminResult([adminBatch("B-1", "2026-07-12T00:00:00Z", "58.00")])
    expect(latestCostBatch(res)?.batch_no).toBe("B-1")
  })

  it("returns null for a SKU with no batches (SERIALIZED, or never received)", () => {
    expect(latestCostBatch(adminResult([]))).toBeNull()
  })

  it("returns null for a staff-shaped result, which carries no cost", () => {
    const staffBatch: SkuBatchPublic = {
      batch_no: "B-1",
      received_at: "2026-07-12T00:00:00Z",
      received_qty: 10,
      remaining_qty: 10,
      is_adjustment: false,
    }
    const res: SkuSearchResult = {
      sku: "HPEOK-D-48-O93D",
      product_id: "11111111-1111-1111-1111-111111111111",
      tracking_mode: "QUANTITY",
      total_on_hand: 10,
      batches: [staffBatch],
    }
    expect(latestCostBatch(res)).toBeNull()
  })

  it("returns null while the query has not resolved", () => {
    expect(latestCostBatch(undefined)).toBeNull()
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
bun run test:unit -- src/lib/stock-adjustment.test.ts
```

Expected: FAIL. The import of `latestCostBatch` does not resolve — vitest reports something like `No "latestCostBatch" export is defined on the "./stock-adjustment" mock` or a transform/type error naming the missing export.

- [ ] **Step 3: Write the minimal implementation**

In `frontend/src/lib/stock-adjustment.ts`, extend the existing type-only import at the top of the file:

```ts
import type {
  AdjustmentTarget,
  SkuBatchAdminPublic,
  SkuSearchAdminResult,
  SkuSearchResult,
  StockAdjustmentCreate,
} from "@/client/types.gen"
```

Append at the end of the file:

```ts
/** A bare `in` check leaves the staff shape in the union (TS widens it to
 *  `SkuBatchPublic & Record<"purchase_cost_thb", unknown>`), so the narrowing
 *  is spelled out as a predicate. */
function hasCost(
  batch: SkuBatchAdminPublic | SkuBatchPublic,
): batch is SkuBatchAdminPublic {
  return "purchase_cost_thb" in batch
}

/** Newest batch for a SKU — the search endpoint returns batches oldest-first,
 *  so that is the last one. This is the default cost basis for a positive
 *  adjustment. Null for staff-scoped results (no cost in the payload),
 *  SERIALIZED SKUs, and SKUs that have never been received. */
export function latestCostBatch(
  res: SkuSearchAdminResult | SkuSearchResult | undefined,
): SkuBatchAdminPublic | null {
  const batches = res?.batches ?? []
  // Not .at(-1): tsconfig targets ES2020 and Array.prototype.at is ES2022.
  const newest = batches[batches.length - 1]
  return newest && hasCost(newest) ? newest : null
}
```

`SkuBatchPublic` joins the type-only import for the predicate's parameter.

- [ ] **Step 4: Run the test to verify it passes**

```bash
bun run test:unit -- src/lib/stock-adjustment.test.ts
```

Expected: PASS, 5 tests.

- [ ] **Step 5: Lint and typecheck**

```bash
bun run lint
bunx tsc -p tsconfig.build.json --noEmit
```

Expected: both clean. `bun run lint` reformats with `--write` and is known to touch unrelated files cosmetically — only stage the two files this task owns.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/stock-adjustment.ts frontend/src/lib/stock-adjustment.test.ts
git commit -m "feat(stock-adjustment): latestCostBatch helper for cost prefill"
```

---

## Task 2: Prefill the cost field on the adjustment screen

**Files:**
- Modify: `frontend/src/routes/_layout/stock-adjustment.tsx` — imports (line 6), the adjustment mutation (lines 96–118), the derived-state block near `showCost` (lines 146–153), and the cost field JSX (lines 438–450), plus the submit button's `onClick`/`disabled` (lines 471–477)

**Interfaces:**
- Consumes: `latestCostBatch` from Task 1; `SearchService.searchSku({ sku })` from the generated SDK; the existing `AdjustmentDraft`, `buildAdjustmentPayload`, `canSubmitAdjustment` from `@/lib/stock-adjustment`.
- Produces: nothing other tasks depend on. This is the last task.

**Background the implementer needs:**

- The route is guarded by `requireAdmin()` (line 40), so the admin variant of the search response is what arrives.
- `showCost` (line 149) is the existing condition that reveals the field: QUANTITY target, not the Return sub-tab, and a delta that parses to a positive integer. Reuse it — do not restate the condition.
- The page already uses the query key `["search-sku", sku]` shape in `search.tsx`, and this file already invalidates `["search-sku"]` on both mutation successes. Using the same key means the prefill refreshes itself after a recorded adjustment for free.
- The existing `returnMutation` (line 122) takes its draft as a mutation variable specifically so a click that changes state and submits in the same tick cannot post a stale draft. The adjustment mutation currently reads `draft` from the closure. It must switch to the variable form, otherwise it posts the empty `purchaseCost` the user never typed.

- [ ] **Step 1: Import `SearchService` and `latestCostBatch`**

Change line 6 from:

```tsx
import { ApiError, SalesService, StockAdjustmentsService } from "@/client"
```

to:

```tsx
import {
  ApiError,
  SalesService,
  SearchService,
  StockAdjustmentsService,
} from "@/client"
```

And extend the existing import block from `@/lib/stock-adjustment` (lines 31–36) to include the helper:

```tsx
import {
  type AdjustmentDraft,
  buildAdjustmentPayload,
  canSubmitAdjustment,
  emptyAdjustmentDraft,
  latestCostBatch,
} from "@/lib/stock-adjustment"
```

- [ ] **Step 2: Move the `showCost` derivation above the mutations**

`deltaNum` / `showCost` are currently computed at lines 146–153, below the mutations. The new query and the effective draft need them, and the mutation needs the effective draft. Cut this block:

```tsx
  const deltaNum = Number.parseInt(draft.qtyDelta, 10)
  const isQuantityReturn =
    draft.targetKind === "QUANTITY" && qtyAction === "RETURN"
  const showCost =
    draft.targetKind === "QUANTITY" &&
    !isQuantityReturn &&
    Number.isFinite(deltaNum) &&
    deltaNum > 0
```

and paste it immediately after the `skuReturnQuery` / `selectedLine` block (i.e. after line 94, before `const mutation = useMutation({`). Nothing else moves.

- [ ] **Step 3: Add the cost lookup query and the effective draft**

Directly below the block you just moved, add:

```tsx
  // The cost basis for a found-stock batch defaults to what this SKU last cost.
  // Same query key as the Search screen, so the two share a cache entry and the
  // invalidation below refreshes the suggestion after a recorded adjustment.
  // ponytail: no debounce — editing the SKU while a positive delta is already
  // typed fires one 404 per keystroke. Debounce, or commit the SKU on blur like
  // search.tsx does, if this admin-only screen ever gets chatty.
  const costQuery = useQuery({
    queryKey: ["search-sku", sku],
    queryFn: () => SearchService.searchSku({ sku }),
    enabled: showCost && sku.length > 0,
    retry: false,
  })
  const suggestedBatch = latestCostBatch(costQuery.data)
  // Derived, not synced into state: an untouched cost field shows the
  // suggestion, and typing over it (or clearing it) wins.
  const effectiveDraft: AdjustmentDraft =
    draft.purchaseCost === "" && suggestedBatch
      ? { ...draft, purchaseCost: suggestedBatch.purchase_cost_thb }
      : draft
```

- [ ] **Step 4: Make the adjustment mutation take the draft as a variable**

Change the mutation's `mutationFn` (lines 97–100) from the closure form to the variable form, matching `returnMutation`:

```tsx
  const mutation = useMutation({
    mutationFn: (d: AdjustmentDraft) =>
      StockAdjustmentsService.createStockAdjustment({
        requestBody: buildAdjustmentPayload(d, crypto.randomUUID()),
      }),
```

Leave `onSuccess` and `onError` exactly as they are — `onSuccess` still resets from `draft`, which is correct: it only reads `targetKind`.

- [ ] **Step 5: Render the suggestion in the field**

Replace the cost-field block (lines 438–450) with:

```tsx
                  {showCost ? (
                    <div className="space-y-2">
                      <Label htmlFor={costId}>Purchase cost (THB)</Label>
                      <Input
                        id={costId}
                        inputMode="decimal"
                        className="num"
                        value={effectiveDraft.purchaseCost}
                        onChange={(e) => set({ purchaseCost: e.target.value })}
                        placeholder="Cost basis for the new batch"
                      />
                      {suggestedBatch ? (
                        <p className="text-muted-foreground text-sm">
                          Last received at ฿
                          <span className="num">
                            {suggestedBatch.purchase_cost_thb}
                          </span>{" "}
                          on{" "}
                          {new Date(
                            suggestedBatch.received_at,
                          ).toLocaleDateString()}
                          .
                        </p>
                      ) : null}
                    </div>
                  ) : null}
```

- [ ] **Step 6: Submit the effective draft**

In the button block (lines 471–477), the guard and the click both need the effective draft:

```tsx
              <Button
                type="button"
                disabled={
                  !canSubmitAdjustment(effectiveDraft) || mutation.isPending
                }
                onClick={() => mutation.mutate(effectiveDraft)}
              >
                {mutation.isPending ? "Recording…" : "Record adjustment"}
              </Button>
```

- [ ] **Step 7: Typecheck and lint**

```bash
bun run lint
bunx tsc -p tsconfig.build.json --noEmit
```

Expected: both clean. If tsc complains that `purchase_cost_thb` does not exist on the batch type, the narrowing in Task 1 was cast away — go back and fix the helper rather than casting here.

- [ ] **Step 8: Re-run the unit suite**

```bash
bun run test:unit
```

Expected: the whole `src/lib` suite passes, including Task 1's five new tests. Nothing in this task changes pure logic, so any failure here is a real regression.

- [ ] **Step 9: Verify in the browser**

Start the stack from the repo root if it is not already up:

```bash
docker compose watch
```

Sign in as the superuser, go to **Stock adjustment** → **Quantity SKU** → **Found / Lost**, then check each case:

| Action | Expected |
| --- | --- |
| Enter a QUANTITY SKU that has been received, then type `1` | Cost field appears already filled with the last batch cost, and the line `Last received at ฿NN.NN on <date>.` shows below it |
| Type over the filled value | Your value stays; the helper line still shows the last-received figure |
| Clear the field | The suggestion comes back |
| Type `-1` instead | Cost field disappears entirely (unchanged behaviour) |
| Enter a SKU that does not exist, then type `1` | Empty field, no helper line, no error toast |
| Fill the reason and record the adjustment | Success toast, form resets, no cost field |

- [ ] **Step 10: Commit**

```bash
git add frontend/src/routes/_layout/stock-adjustment.tsx
git commit -m "feat(stock-adjustment): prefill purchase cost from the last batch"
```

---

## Review and ship

- [ ] **Run the review stage.** Use `superpowers:requesting-code-review`. This change touches an append-only ledger's cost basis, so per CLAUDE.md also dispatch `ecc:react-reviewer` and `ecc:security-reviewer` — the latter specifically on the question of whether the admin-only cost value can reach a staff-scoped session (it cannot: the route is `requireAdmin()` and the staff response shape carries no cost, but have it verified rather than asserted).
- [ ] **Open the PR** with `superpowers:create-pr`, targeting `dev`. Never `master`.

## Out of scope

- The Return sub-tab and the Serialized unit tab.
- Any backend change to how `purchase_cost_thb` is derived or validated.
- An E2E assertion in `frontend/tests/stock-adjustment.spec.ts` — only worth adding if the seed guarantees a received batch for a known QUANTITY SKU; the manual matrix in Task 2 Step 9 covers it otherwise.
