# Sync-Review Producer + Pulls Offline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the client half of PRD §8.3 — make project-pull fulfillment work offline, divert offline-origin 409 conflicts and >7-day-stale queued actions into the existing admin review queue, and enforce the 7-day cap.

**Architecture:** A pure, unit-testable helper module (`sync-producer.ts`) computes what to divert; the runtime wiring in `query-client.ts` (an extended mutation error handler + a resume-time stale gate) and `main.tsx` feeds the existing backend ingest endpoint. Offline actions carry hidden `{submittedAt, queuedOffline, idempotencyKey}` metadata that never reaches the server. No backend changes.

**Tech Stack:** React + TypeScript, TanStack Query v5 (`onlineManager`, `MutationCache`, persisted paused mutations), generated `@hey-api` SDK, Playwright (unit + E2E), biome, bun.

**Design spec:** `docs/superpowers/specs/2026-07-11-sync-review-producer-design.md` (read it before starting).

## Global Constraints

- **No backend change.** Ingest/list/resolve endpoints, models, migrations, and `sync-review.tsx` are untouched. SDK is not regenerated.
- **Status-only triage** — never re-execute a held mutation (PRD-confirmed).
- **Only offline-origin 409s divert.** A live/online 409 keeps its existing plain-language error toast; only `meta.queuedOffline === true` + status 409 diverts as `CONFLICT`.
- **7-day cap is a fixed constant** `SYNC_STALE_MS = 7 * 24 * 60 * 60 * 1000`. Not configurable.
- **Stale primary guarantee:** a stale queued action is **removed before replay** so it can never replay against current stock; the review POST is best-effort. Stale divert runs **only when `onlineManager.isOnline()`**.
- **Divert POSTs are best-effort:** errors are caught + logged, never thrown; server ingest is idempotent on `idempotency_key`.
- **`sync-producer.ts` stays pure** — `import type` only (relative `../client/types.gen`, mirroring `receive-form.ts`), no runtime imports — so its Playwright unit spec loads without app/browser globals.
- **Single-queued-action scope** — mirror the shipped sales design (`sale.tsx:197-200`); no multi-action-offline handling.
- **TDD, DRY, YAGNI, frequent commits.** One commit per task.

### Worktree setup (do this once, before Task 1)

This plan runs in the `feat/sync-review-producer` worktree, which has no installed dependencies yet.

- [ ] Install deps: `cd frontend && bun install`
- [ ] Confirm a clean baseline: `cd frontend && bunx playwright test tests/receive-form.spec.ts tests/sale.spec.ts --reporter=line` → all pass. If anything fails before you change code, stop and report.

---

## File Structure

| File | Created/Modified | Responsibility |
|---|---|---|
| `frontend/src/lib/sync-producer.ts` | Create | Pure helpers: `SYNC_STALE_MS`, `QueueMeta`/`Queued` types, `isStale`, `buildSyncReviewItem`, `staleItemFor`, `shouldDivertConflict`. Type-only imports. |
| `frontend/tests/sync-producer.spec.ts` | Create | Unit tests for all of the above (pure-logic style, like `receive-form.spec.ts`). |
| `frontend/src/lib/query-client.ts` | Modify | Runtime wiring: `queued()` factory, `postSyncReviewItem()`, `divertStaleMutations()`, split `handleQueryError`/`handleMutationError`; `["pull-fulfill"]` default; wrap `["sales"]`/`["receipts"]` defaults to strip meta. |
| `frontend/src/main.tsx` | Modify | Call `divertStaleMutations()` before `resumePausedMutations()` at both replay trigger points. |
| `frontend/src/routes/_layout/sale.tsx` | Modify | Wrap mutate variables with `queued(...)`. |
| `frontend/src/routes/_layout/receive.tsx` | Modify | Wrap the serialized mutate variables with `queued(...)`. |
| `frontend/src/routes/_layout/pulls.tsx` | Modify | Switch `fulfillMutation` to `mutationKey: ["pull-fulfill"]` + `queued(...)`; drop inline `mutationFn`. |
| `frontend/tests/pulls-offline.spec.ts` | Create | E2E: pull offline replay + conflict divert (mirrors `sale.spec.ts`). |

---

### Task 1: Pure sync-producer helpers

**Files:**
- Create: `frontend/src/lib/sync-producer.ts`
- Test: `frontend/tests/sync-producer.spec.ts`

**Interfaces:**
- Consumes: `SyncReviewItemCreate`, `SyncReviewReason` (types) from `../client/types.gen`. Confirmed shapes: `SyncReviewItemCreate = { idempotency_key: string; mutation_kind: string; payload: {[key: string]: unknown}; reason: SyncReviewReason }`; `SyncReviewReason = 'STALE' | 'CONFLICT'`.
- Produces:
  - `SYNC_STALE_MS: number`
  - `type QueueMeta = { submittedAt: number; queuedOffline: boolean; idempotencyKey: string }`
  - `type Queued<TBody> = { body: TBody; meta: QueueMeta }`
  - `isStale(submittedAt: number | undefined, now: number): boolean`
  - `buildSyncReviewItem(mutationKey: readonly unknown[] | undefined, variables: Queued<unknown> | undefined, reason: SyncReviewReason): SyncReviewItemCreate | null`
  - `staleItemFor(isPaused: boolean, mutationKey: readonly unknown[] | undefined, variables: Queued<unknown> | undefined, now: number): SyncReviewItemCreate | null`
  - `shouldDivertConflict(status: number, meta: QueueMeta | undefined): boolean`

- [ ] **Step 1: Write the failing test** — `frontend/tests/sync-producer.spec.ts`

```ts
import { expect, test } from "@playwright/test"
import {
  buildSyncReviewItem,
  isStale,
  type Queued,
  shouldDivertConflict,
  staleItemFor,
  SYNC_STALE_MS,
} from "../src/lib/sync-producer"

// Pure-logic coverage of the offline sync-review producer. No browser/React/
// backend required — mirrors receive-form.spec.ts.

const NOW = 1_000_000_000_000 // fixed clock; Date.now() is never called here.

function q(body: unknown, meta: Partial<Queued<unknown>["meta"]>): Queued<unknown> {
  return {
    body,
    meta: {
      submittedAt: NOW,
      queuedOffline: true,
      idempotencyKey: "idem-1",
      ...meta,
    },
  }
}

// --- isStale ---------------------------------------------------------------

test("isStale: false just under the 7-day cap", () => {
  expect(isStale(NOW - (SYNC_STALE_MS - 60_000), NOW)).toBe(false)
})

test("isStale: true just over the 7-day cap", () => {
  expect(isStale(NOW - (SYNC_STALE_MS + 60_000), NOW)).toBe(true)
})

test("isStale: false for undefined submittedAt", () => {
  expect(isStale(undefined, NOW)).toBe(false)
})

// --- buildSyncReviewItem ---------------------------------------------------

test("buildSyncReviewItem maps kind, payload, key, reason", () => {
  const item = buildSyncReviewItem(
    ["pull-fulfill"],
    q({ pullId: "p1", body: { lines: [] } }, { idempotencyKey: "k9" }),
    "CONFLICT",
  )
  expect(item).toEqual({
    idempotency_key: "k9",
    mutation_kind: "pull-fulfill",
    payload: { pullId: "p1", body: { lines: [] } },
    reason: "CONFLICT",
  })
})

test("buildSyncReviewItem returns null when meta or key is missing", () => {
  expect(buildSyncReviewItem(["sales"], undefined, "STALE")).toBeNull()
  expect(buildSyncReviewItem(undefined, q({}, {}), "STALE")).toBeNull()
  expect(buildSyncReviewItem([], q({}, {}), "STALE")).toBeNull()
})

// --- staleItemFor ----------------------------------------------------------

test("staleItemFor diverts a paused, stale mutation as STALE", () => {
  const item = staleItemFor(
    true,
    ["sales"],
    q({ x: 1 }, { submittedAt: NOW - (SYNC_STALE_MS + 1), idempotencyKey: "s1" }),
    NOW,
  )
  expect(item).toEqual({
    idempotency_key: "s1",
    mutation_kind: "sales",
    payload: { x: 1 },
    reason: "STALE",
  })
})

test("staleItemFor ignores a fresh mutation", () => {
  expect(staleItemFor(true, ["sales"], q({ x: 1 }, { submittedAt: NOW }), NOW)).toBeNull()
})

test("staleItemFor ignores a non-paused (in-flight) mutation", () => {
  expect(
    staleItemFor(false, ["sales"], q({ x: 1 }, { submittedAt: NOW - (SYNC_STALE_MS + 1) }), NOW),
  ).toBeNull()
})

// --- shouldDivertConflict --------------------------------------------------

test("shouldDivertConflict: offline-origin 409 diverts", () => {
  expect(shouldDivertConflict(409, { submittedAt: NOW, queuedOffline: true, idempotencyKey: "i" })).toBe(true)
})

test("shouldDivertConflict: online 409 does not divert", () => {
  expect(shouldDivertConflict(409, { submittedAt: NOW, queuedOffline: false, idempotencyKey: "i" })).toBe(false)
})

test("shouldDivertConflict: non-409 does not divert", () => {
  expect(shouldDivertConflict(400, { submittedAt: NOW, queuedOffline: true, idempotencyKey: "i" })).toBe(false)
})

test("shouldDivertConflict: undefined meta does not divert", () => {
  expect(shouldDivertConflict(409, undefined)).toBe(false)
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && bunx playwright test tests/sync-producer.spec.ts --reporter=line`
Expected: FAIL — cannot resolve `../src/lib/sync-producer`.

- [ ] **Step 3: Write the minimal implementation** — `frontend/src/lib/sync-producer.ts`

```ts
import type { SyncReviewItemCreate, SyncReviewReason } from "../client/types.gen"

// Pure, runtime-import-free producer logic for the offline sync-review queue.
// The runtime wiring (posting, cache scanning, the queued() factory) lives in
// query-client.ts; keeping this module type-only lets its unit spec load in
// node the same way receive-form.spec.ts does.

/** Offline queue is capped at 7 days (PRD §8.3). */
export const SYNC_STALE_MS = 7 * 24 * 60 * 60 * 1000

/** Hidden metadata carried with a queued mutation; never sent to the server. */
export type QueueMeta = {
  submittedAt: number
  queuedOffline: boolean
  idempotencyKey: string
}

/** A queued mutation's variables: the real request body plus hidden metadata. */
export type Queued<TBody> = { body: TBody; meta: QueueMeta }

export function isStale(submittedAt: number | undefined, now: number): boolean {
  return typeof submittedAt === "number" && now - submittedAt > SYNC_STALE_MS
}

/** Build the ingest payload from a mutation's key + queued variables. */
export function buildSyncReviewItem(
  mutationKey: readonly unknown[] | undefined,
  variables: Queued<unknown> | undefined,
  reason: SyncReviewReason,
): SyncReviewItemCreate | null {
  const meta = variables?.meta
  const kind = mutationKey && mutationKey.length > 0 ? String(mutationKey[0]) : ""
  if (!meta || kind === "") return null
  return {
    idempotency_key: meta.idempotencyKey,
    mutation_kind: kind,
    payload: (variables?.body ?? {}) as { [key: string]: unknown },
    reason,
  }
}

/** A STALE review item for a paused mutation past the cap, else null. */
export function staleItemFor(
  isPaused: boolean,
  mutationKey: readonly unknown[] | undefined,
  variables: Queued<unknown> | undefined,
  now: number,
): SyncReviewItemCreate | null {
  if (!isPaused) return null
  if (!isStale(variables?.meta?.submittedAt, now)) return null
  return buildSyncReviewItem(mutationKey, variables, "STALE")
}

/** Only an offline-origin 409 (a lost write-conflict on replay) diverts. */
export function shouldDivertConflict(
  status: number,
  meta: QueueMeta | undefined,
): boolean {
  return status === 409 && meta?.queuedOffline === true
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && bunx playwright test tests/sync-producer.spec.ts --reporter=line`
Expected: PASS (13 tests).

- [ ] **Step 5: Lint + commit**

```bash
cd frontend && bunx biome check src/lib/sync-producer.ts tests/sync-producer.spec.ts --write
git add frontend/src/lib/sync-producer.ts frontend/tests/sync-producer.spec.ts
git commit -m "feat(offline): pure sync-review producer helpers"
```

---

### Task 2: Producer wiring in query-client.ts

**Files:**
- Modify: `frontend/src/lib/query-client.ts` (whole file rewritten below)

**Interfaces:**
- Consumes: `staleItemFor`, `buildSyncReviewItem`, `shouldDivertConflict`, `type Queued` from `./sync-producer`; `onlineManager`, `MutationCache`, `QueryCache`, `QueryClient` from `@tanstack/react-query`; `SyncReviewService`, `ApiError` from `@/client`.
- Produces (new exports used by later tasks):
  - `queued<TBody>(body: TBody, idempotencyKey: string): Queued<TBody>`
  - `divertStaleMutations(now?: number): void`

This task adds the wiring but leaves the `["sales"]`/`["receipts"]` call sites unwrapped, so `handleMutationError` reads `meta === undefined` and diverts nothing yet (dormant until Task 4/5). The app still builds and the existing sales/receipts offline path is unchanged.

- [ ] **Step 1: Rewrite `frontend/src/lib/query-client.ts`**

```ts
import { createAsyncStoragePersister } from "@tanstack/query-async-storage-persister"
import {
  MutationCache,
  onlineManager,
  QueryCache,
  QueryClient,
} from "@tanstack/react-query"
import { del, get, set } from "idb-keyval"
import {
  ApiError,
  ReceiptsService,
  type ReceiveSerializedRequest,
  type SaleCreateRequest,
  SalesService,
  SyncReviewService,
} from "@/client"
import {
  buildSyncReviewItem,
  type Queued,
  shouldDivertConflict,
  staleItemFor,
} from "./sync-producer"

/** Wrap a request body with hidden offline-queue metadata (stripped before the
 *  server call by the registered mutationFn). `idempotencyKey` reuses the
 *  action's own key where it has one; pull-fulfill passes a generated one. */
export function queued<TBody>(body: TBody, idempotencyKey: string): Queued<TBody> {
  return {
    body,
    meta: {
      submittedAt: Date.now(),
      queuedOffline: !onlineManager.isOnline(),
      idempotencyKey,
    },
  }
}

const endSession = () => {
  localStorage.removeItem("access_token")
  window.location.href = "/login"
}

// Best-effort: a failed divert must never throw (it runs inside error handling
// and replay). Server ingest is idempotent on idempotency_key, so a dropped
// POST is safe to lose; log it and move on.
async function postSyncReviewItem(
  item: Parameters<typeof SyncReviewService.ingestSyncReviewItem>[0]["requestBody"],
): Promise<void> {
  try {
    await SyncReviewService.ingestSyncReviewItem({ requestBody: item })
  } catch (err) {
    console.error("sync-review ingest failed", err)
  }
}

// Queries: only 401 ends the session (unchanged behavior).
const handleQueryError = (error: Error) => {
  if (error instanceof ApiError && error.status === 401) endSession()
}

// Mutations: 401 ends the session; an offline-origin 409 on replay is diverted
// to the admin review queue as CONFLICT. A live (online) 409 falls through to
// the screen's own onError toast, unchanged.
const handleMutationError = (
  error: Error,
  variables: unknown,
  _context: unknown,
  mutation: { options: { mutationKey?: readonly unknown[] } },
) => {
  if (error instanceof ApiError && error.status === 401) {
    endSession()
    return
  }
  const vars = variables as Queued<unknown> | undefined
  if (error instanceof ApiError && shouldDivertConflict(error.status, vars?.meta)) {
    const item = buildSyncReviewItem(mutation.options.mutationKey, vars, "CONFLICT")
    if (item) void postSyncReviewItem(item)
  }
}

export const queryClient = new QueryClient({
  defaultOptions: {
    // 24h cache so persisted queries survive an offline reload.
    queries: { gcTime: 1000 * 60 * 60 * 24 },
  },
  queryCache: new QueryCache({ onError: handleQueryError }),
  mutationCache: new MutationCache({ onError: handleMutationError }),
})

// Remove any paused mutation older than the 7-day cap BEFORE replay, so a
// forgotten device can never replay a stale action against current stock
// (PRD §8.3, primary guarantee). Record it for admin review (best-effort).
// Runs only when online — offline we can't post, and resume is a no-op anyway.
export function divertStaleMutations(now = Date.now()): void {
  if (!onlineManager.isOnline()) return
  const cache = queryClient.getMutationCache()
  for (const mutation of cache.getAll()) {
    const item = staleItemFor(
      mutation.state.isPaused,
      mutation.options.mutationKey,
      mutation.state.variables as Queued<unknown> | undefined,
      now,
    )
    if (!item) continue
    cache.remove(mutation)
    void postSyncReviewItem(item)
  }
}

// idb-keyval's get/set/del match the async-storage interface; storing the
// client in IndexedDB keeps queued mutations across reloads.
export const persister = createAsyncStoragePersister({
  storage: { getItem: get, setItem: set, removeItem: del },
})

// Paused (offline) mutations can't be serialized, so their fns must be
// re-registered by key for resumePausedMutations() to replay them after a
// reload. Every offline mutation carries a client idempotency_key, so the
// backend dedupes replays (no app-level encryption — S4).
queryClient.setMutationDefaults(["sales"], {
  mutationFn: (requestBody: SaleCreateRequest) =>
    SalesService.createSale({ requestBody }),
})
queryClient.setMutationDefaults(["receipts"], {
  mutationFn: (requestBody: ReceiveSerializedRequest) =>
    ReceiptsService.receiveSerialized({ requestBody }),
})
```

- [ ] **Step 2: Type-check + lint**

Run: `cd frontend && bunx tsc --noEmit && bunx biome check src/lib/query-client.ts`
Expected: no errors.

- [ ] **Step 3: Regression — the existing offline path still works**

Run: `cd frontend && bunx playwright test tests/sale.spec.ts --reporter=line`
Expected: PASS (sales offline replay unaffected — defaults and variable shapes unchanged this task).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/query-client.ts
git commit -m "feat(offline): wire sync-review producer into query-client"
```

---

### Task 3: Run the stale gate before replay in main.tsx

**Files:**
- Modify: `frontend/src/main.tsx:19-47`

**Interfaces:**
- Consumes: `divertStaleMutations` from `./lib/query-client`.

- [ ] **Step 1: Edit `frontend/src/main.tsx`**

Change the import line 11 and the two replay trigger points.

Import (line 11) becomes:

```ts
import { divertStaleMutations, persister, queryClient } from "./lib/query-client"
```

The `window "online"` listener (lines 19-22) becomes:

```ts
// Replay offline-queued mutations as soon as the network returns — but first
// hold back anything older than the 7-day cap for admin review.
window.addEventListener("online", () => {
  divertStaleMutations()
  queryClient.resumePausedMutations()
})
```

The `PersistQueryClientProvider` `onSuccess` (lines 37-41) becomes:

```ts
        onSuccess={() => {
          // Once the persisted cache is restored, hold back stale mutations,
          // then resume any that were paused while offline before the reload.
          divertStaleMutations()
          queryClient.resumePausedMutations()
        }}
```

- [ ] **Step 2: Type-check + lint**

Run: `cd frontend && bunx tsc --noEmit && bunx biome check src/main.tsx`
Expected: no errors.

- [ ] **Step 3: Regression**

Run: `cd frontend && bunx playwright test tests/sale.spec.ts --reporter=line`
Expected: PASS (fresh sales are never stale, so the gate is a no-op for them).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/main.tsx
git commit -m "feat(offline): hold back stale mutations before replay"
```

---

### Task 4: Wrap sales + receipts variables with queue metadata

Now the sales and serialized-receipt offline paths carry `meta`, so the producer covers them (a stale or conflicted queued sale is diverted instead of silently lost).

**Files:**
- Modify: `frontend/src/lib/query-client.ts` (the `["sales"]` and `["receipts"]` defaults)
- Modify: `frontend/src/routes/_layout/sale.tsx:208-209`
- Modify: `frontend/src/routes/_layout/receive.tsx:205-211`

**Interfaces:**
- Consumes: `queued` from `@/lib/query-client`; `type Queued` from `@/lib/sync-producer`.

- [ ] **Step 1: Update the registered defaults in `query-client.ts`**

Replace the two `setMutationDefaults` blocks with meta-stripping versions:

```ts
queryClient.setMutationDefaults(["sales"], {
  mutationFn: ({ body }: Queued<SaleCreateRequest>) =>
    SalesService.createSale({ requestBody: body }),
})
queryClient.setMutationDefaults(["receipts"], {
  mutationFn: ({ body }: Queued<ReceiveSerializedRequest>) =>
    ReceiptsService.receiveSerialized({ requestBody: body }),
})
```

- [ ] **Step 2: Wrap the sale mutate call — `sale.tsx`**

Add the import (with the other `@/lib` imports):

```ts
import { queued } from "@/lib/query-client"
```

Change `handleCheckout` (lines 208-209) to wrap the request, reusing its own idempotency key:

```ts
    const request = buildSaleRequest(lines, customerId, crypto.randomUUID())
    mutation.mutate(queued(request, request.idempotency_key))
```

- [ ] **Step 3: Wrap the serialized-receive mutate call — `receive.tsx`**

Add the import:

```ts
import { queued } from "@/lib/query-client"
```

Change the serialized `handleSubmit` (lines 205-211) to wrap the request:

```ts
    const request = buildReceiveSerializedRequest(
      pieces,
      productId,
      supplierId,
      crypto.randomUUID(),
    )
    mutation.mutate(queued(request, request.idempotency_key))
```

(Leave the quantity-receive mutation at `receive.tsx:496-524` untouched — it is intentionally online-only with no `mutationKey`.)

- [ ] **Step 4: Type-check + lint**

Run: `cd frontend && bunx tsc --noEmit && bunx biome check src`
Expected: no errors.

- [ ] **Step 5: Regression — sales offline replay still passes with the new variable shape**

Run: `cd frontend && bunx playwright test tests/sale.spec.ts --reporter=line`
Expected: PASS. (The mutation still pauses, persists `{body, meta}`, rehydrates, and replays via the meta-stripping default with its original idempotency key.)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/query-client.ts frontend/src/routes/_layout/sale.tsx frontend/src/routes/_layout/receive.tsx
git commit -m "feat(offline): carry queue metadata on sales + serialized receipts"
```

---

### Task 5: Make project-pull fulfillment offline-capable

**Files:**
- Modify: `frontend/src/lib/query-client.ts` (add the `["pull-fulfill"]` default)
- Modify: `frontend/src/routes/_layout/pulls.tsx:132-155` (mutation) and `:260-266` (mutate call)

**Interfaces:**
- Consumes: `queued` from `@/lib/query-client`; `ProjectPullsService.fulfillProjectPull({ pullId, requestBody })`, `ProjectPullFulfill`, `ProjectPullPublic` from `@/client`.

Pull fulfillment has no request-level idempotency key — its backend replay-safety comes from deterministic movement keys derived at fulfill (`models.py:1319-1321`). We generate a client key purely to dedupe the review-queue record.

- [ ] **Step 1: Register the `["pull-fulfill"]` default in `query-client.ts`**

Add these imports to the `@/client` import block: `ProjectPullsService`, and `type ProjectPullFulfill`. Then add, after the `["receipts"]` default:

```ts
queryClient.setMutationDefaults(["pull-fulfill"], {
  mutationFn: ({ body }: Queued<{ pullId: string; requestBody: ProjectPullFulfill }>) =>
    ProjectPullsService.fulfillProjectPull({
      pullId: body.pullId,
      requestBody: body.requestBody,
    }),
})
```

- [ ] **Step 2: Switch `fulfillMutation` to the offline key — `pulls.tsx`**

Add the import:

```ts
import { queued } from "@/lib/query-client"
```

Replace the `fulfillMutation` definition (lines 132-155). It drops the inline `mutationFn` (inherits the `["pull-fulfill"]` default) and its variables become the `queued(...)` wrapper shape:

```ts
  const fulfillMutation = useMutation<
    ProjectPullPublic,
    Error,
    Queued<{ pullId: string; requestBody: ProjectPullFulfill }>
  >({
    // No mutationFn: inherit the persisted ["pull-fulfill"] default from
    // query-client.ts so an offline fulfill is queued and replayed by key.
    mutationKey: ["pull-fulfill"],
    onSuccess: (pull) => {
      queryClient.invalidateQueries({ queryKey: ["project-pulls"] })
      showSuccessToast(
        pull.state === "FULFILLED"
          ? "Parts given out."
          : "Parts given out — some items still short.",
      )
      setSelectedPullId(null)
      setFulfillDraft({})
      setScanNotice("")
    },
    onError: () =>
      showErrorToast("Could not give out the parts. Please try again."),
  })
```

Add the `Queued` type import (with the other `@/lib` imports):

```ts
import type { Queued } from "@/lib/sync-producer"
```

- [ ] **Step 3: Wrap the fulfill mutate call — `pulls.tsx:260-266`**

```ts
  const handleFulfill = useCallback(() => {
    if (!selectedPull) return
    fulfillMutation.mutate(
      queued(
        {
          pullId: selectedPull.id,
          requestBody: buildFulfillPayload(fulfillDraft),
        },
        crypto.randomUUID(),
      ),
    )
  }, [selectedPull, fulfillDraft, fulfillMutation])
```

(The fulfill button already gates on `fulfillMutation.isPending` via the `PullFulfill` component's `isPending` prop at `pulls.tsx:325`, which stays true while the mutation is paused offline — mirroring the sales lock. No further UI change needed.)

- [ ] **Step 4: Type-check + lint**

Run: `cd frontend && bunx tsc --noEmit && bunx biome check src`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/query-client.ts frontend/src/routes/_layout/pulls.tsx
git commit -m "feat(offline): make project-pull fulfillment offline-capable"
```

---

### Task 6: E2E — pull offline replay + conflict divert

**Files:**
- Create: `frontend/tests/pulls-offline.spec.ts`

Mirror `sale.spec.ts`'s harness exactly: the dev server runs without a service worker, so go offline **synthetically** via a `window "offline"` event (TanStack's `onlineManager` subscribes to it), and reload only after the paused mutation is observed in IndexedDB (`REACT_QUERY_OFFLINE_CACHE`). Reuse the seeding + `waitForPersistedPausedMutation` helpers from `sale.spec.ts:88-146` (extract to a shared helper module if copy-paste is excessive; otherwise inline).

- [ ] **Step 1: Write the E2E spec**

Two tests:

1. **Offline replay (happy path):** seed a project pull with one in-stock line; open `/pulls` (the pulls screen route); select the pull; go offline (`window "offline"`); fulfill; wait for the persisted paused mutation; reload (fresh online load); assert the pull shows as fulfilled (query the backend or the UI) and that no `CONFLICT` item exists in `GET /sync-review?state=PENDING`.

2. **Conflict divert:** seed a pull; select it; go offline; fulfill offline; **before reload**, fulfill the same pull online via a direct API call (so the queued replay will 409); wait for the persisted paused mutation; reload; assert a `CONFLICT` sync-review item now appears in `GET /sync-review?state=PENDING` with `mutation_kind === "pull-fulfill"`.

```ts
import { expect, test } from "@playwright/test"
// Reuse the offline harness pattern + API helpers from sale.spec.ts
// (seed via the authenticated API; go offline via window "offline"; reload
// once the paused mutation is persisted in IndexedDB).

// NOTE: fill in seeding using the same authenticated-request helpers sale.spec.ts
// uses (create project, product with stock, pull with one line). Keep the exact
// window-"offline" + waitForPersistedPausedMutation flow from sale.spec.ts:195-233.

test("pull offline → reload → reconnect → replays once (fulfilled)", async ({ page }) => {
  // 1. seed a pull with one in-stock line
  // 2. await page.goto("/pulls"); select the pull
  // 3. await page.evaluate(() => window.dispatchEvent(new Event("offline")))
  // 4. click Give out; await waitForPersistedPausedMutation(page)
  // 5. await page.reload()  // online again → rehydrate → replay
  // 6. assert pull state FULFILLED via API, and no PENDING sync-review item
})

test("pull fulfilled online while queued offline → CONFLICT in review queue", async ({ page }) => {
  // 1. seed a pull with one in-stock line
  // 2. goto /pulls; select the pull
  // 3. dispatch window "offline"; click Give out; waitForPersistedPausedMutation
  // 4. via API, fulfill the SAME pull online (consumes the stock)
  // 5. page.reload() → replay 409s → producer posts CONFLICT
  // 6. GET /sync-review?state=PENDING → expect one item, mutation_kind "pull-fulfill"
})
```

- [ ] **Step 2: Run it, watch it fail (before the producer works end-to-end), then pass**

Run: `cd frontend && bunx playwright test tests/pulls-offline.spec.ts --reporter=line`
Expected: PASS once Tasks 1-5 are in place. If the conflict test fails because no item is produced, debug the `handleMutationError` path (confirm `meta.queuedOffline` is `true` on the replayed mutation and the 409 is an `ApiError`).

- [ ] **Step 3: Full regression**

Run: `cd frontend && bunx playwright test tests/sync-producer.spec.ts tests/receive-form.spec.ts tests/sale.spec.ts tests/pulls-offline.spec.ts --reporter=line`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/tests/pulls-offline.spec.ts
git commit -m "test(offline): E2E for pull replay + conflict divert"
```

---

## Review gate (after Task 6, before PR)

Per the spec §8 and CLAUDE.md §5:
- `superpowers:requesting-code-review`
- `ecc:security-reviewer` (queued sale payloads carry prices).
- `ecc:database-reviewer` is **not** required (no schema/movement/FIFO changes).

Then `create-pr` into `dev` (never `master`).

## Self-Review (plan vs spec)

- **Spec coverage:** §2 pulls-offline → Task 5 + 6; §2 conflict producer → Task 2 (`handleMutationError`) + Task 6 test 2; §2 stale cap → Task 2 (`divertStaleMutations`) + Task 3 + Task 1 unit tests; §5 metadata trick → Task 4 + 5; §4 components → Tasks 1-5 match the file table; §7 testing → Task 1 (unit) + Task 6 (E2E); §8 risk gate → Review gate section. Sales/receipts producer coverage (spec §2 "what's already queued") → Task 4. No uncovered requirement.
- **Placeholder scan:** Task 6's E2E bodies are intentionally described as steps because they depend on `sale.spec.ts`'s seeding helpers (which must be read at implementation time); the offline mechanics and assertions are fully specified. All other steps contain complete code.
- **Type consistency:** `Queued<TBody>`, `QueueMeta`, `staleItemFor`, `buildSyncReviewItem`, `shouldDivertConflict`, `queued`, `divertStaleMutations` names/signatures are identical across Tasks 1-6. `["sales"]`/`["receipts"]`/`["pull-fulfill"]` keys and the `{body, requestBody}` pull shape are consistent between the default (Task 5 Step 1) and the mutate call (Task 5 Step 3).
