# Sync-Review Producer + Pulls Offline — Design

**Status:** Approved design (brainstorming), 2026-07-11. Not yet planned or implemented.
**Branch:** `feat/sync-review-producer` (off `dev`).
**Author context:** Closes the client half of PRD §8.3, flagged as "Severity 2 — offline is the largest functional gap" in the 2026-07-10 PRD-conformance audit (`notes.md`).

---

## 1. Problem

PRD §8.3 advertises three offline guarantees. The **backend** for all three is built and correct
(`sync_review.py`, M020), and the **admin review screen** exists (`sync-review.tsx`). But the
**client half that would ever populate the queue was knowingly deferred** to "Part 5"
(`docs/superpowers/plans/2026-06-06-castranova-part4.3-sync-review.md:8`) and never built. Today:

- Only **sales** and **serialized receipts** survive offline. Project-pull fulfillment and
  maintenance tickets have **no offline queue key** (`query-client.ts` registers only `["sales"]`
  and `["receipts"]`) — offline, they simply fail.
- **No client code detects a 409 on replay** or posts to the ingest endpoint. The admin review
  queue has no producer — it is a fully-built inbox that never receives mail.
- **No 7-day cap** is enforced client-side.

The most dangerous consequence: if two staff collide offline, the losing write **silently vanishes**
on sync — no error, no review, no trace.

## 2. Scope

**In:**
1. **Pulls offline** — project-pull fulfillment is queued offline and replayed, mirroring the shipped
   sales/receipts mechanism.
2. **Conflict-capture producer** — an offline-origin `409` on replay is diverted into the existing
   admin review queue as `CONFLICT` instead of vanishing.
3. **7-day stale cap** — a queued action older than 7 days is held for review (`STALE`) instead of
   being replayed against current stock.

**Out (explicitly):**
- **Maintenance tickets offline.** Ticket submission is a 3-call orchestration
  (`openServiceTicket` → `addServiceTicketPart`×N → `closeServiceTicket`, `tickets.tsx:117-138`) and
  `addServiceTicketPart` is **not idempotent** (the code says so at `tickets.tsx:107-109`; CLAUDE.md
  lists it as backlog). Making it replay-safe requires a **backend redesign into one atomic,
  idempotent submit endpoint** (migration touching FIFO consumption → full high-risk gate). That is
  its own spec, and it **blocks** any offline-tickets work.
- **Auto-re-apply on "Keep."** PRD-confirmed status-only triage (see §3).
- **Multi-action-offline.** Single-queued-action scope, matching the shipped sales design
  (`sale.tsx:197-200`).
- **Any backend change.** Ingest / list / resolve endpoints, models, migrations, and the admin
  screen are untouched.

## 3. Decisions & rationale

**D1 — "Keep" is status-only triage (no re-execution).** PRD §8.3 says the system "surfaces [the
conflict] for review" and stale items are "held back for admin review"; the success metric counts the
queue as the log of events "needing the admin to step in" (§ lines 335, 337, 136). It never promises
auto-re-apply — and for a genuine conflict, re-applying is usually *impossible* (the item is already
consumed). Matches the shipped backend (plan line 9). **No backend re-execution engine.**

**D2 — Only *offline-origin* 409s are diverted.** A live/online 409 (real-time oversell) must keep its
existing plain-language error toast ("This unit is already sold"); only a 409 on a *replayed offline*
action is a reviewable conflict. Distinguished by a `queuedOffline` flag stamped at submit time.

**D3 — Centralized producer, not per-screen.** All divert logic lives in one module. "Each screen
wires its own offline handling" is precisely how pulls and tickets were missed; centralizing prevents
recurrence.

**D4 — 7 days is a fixed constant** (`SYNC_STALE_MS`), per PRD §8.3 ("capped at 7 days"). Not
configurable (YAGNI).

## 4. Architecture & components

### New — `frontend/src/lib/sync-producer.ts` (mostly pure, unit-testable)

- `SYNC_STALE_MS = 7 * 24 * 60 * 60 * 1000`
- `isStale(submittedAt: number, now: number): boolean` — pure.
- `buildSyncReviewItem(mutation, reason): SyncReviewItemCreate` — pure. Maps `mutation_kind` from the
  mutation key (`"sales" | "receipts" | "pull-fulfill"`), `payload` = the request body,
  `idempotency_key` from queue metadata, `reason`.
- `postSyncReviewItem(item)` — calls `SyncReviewService.ingestSyncReviewItem` (SDK method confirmed at
  `client/sdk.gen.ts:1353`). **Best-effort**: errors are logged, never thrown — a failed divert must
  not crash replay of other actions. Server ingest is idempotent on `idempotency_key`, so retries are
  safe.
- `divertStaleMutations(queryClient, now)` — scans `getMutationCache().getAll()`; for each **paused**
  mutation whose `meta.submittedAt` is stale: post `STALE`, then `remove()` it so it never replays.
- `captureConflict(mutation)` — posts `CONFLICT` for an offline-origin 409.

### Modified

- **`frontend/src/lib/query-client.ts`**
  - Register a `["pull-fulfill"]` mutation default (strips meta, calls
    `ProjectPullsService.fulfillProjectPull`).
  - Split the shared error handler: the **mutation** cache also detects *offline-origin* `409 →
    captureConflict`. `401`-logout and live-error behavior are unchanged; the **query** cache stays
    401-only.
- **`frontend/src/main.tsx`** — at both replay trigger points (the `window "online"` listener and the
  `PersistQueryClientProvider` `onSuccess`), call `divertStaleMutations(queryClient, Date.now())`
  **before** `resumePausedMutations()`.
- **`frontend/src/routes/_layout/pulls.tsx`** — switch `fulfillMutation` to
  `mutationKey: ["pull-fulfill"]` (drop the inline `mutationFn`), wrap variables with queue metadata,
  and gate the fulfill button on `!isPending` (locks while queued), mirroring `sale.tsx`.
- **`frontend/src/routes/_layout/sale.tsx`** and **`receive.tsx`** — wrap their mutate variables with
  queue metadata (see §5). Their registered defaults strip it.

### Unchanged

All backend (`sync_review.py`, `crud.py`, `models.py`, migrations), the admin screen
(`sync-review.tsx`), and the generated SDK.

## 5. Data flow — the queue-metadata trick

Metadata (`submittedAt`, offline-origin, a stable key) must travel **with** each queued action so it
survives a reload — but must **never** reach the server. Solution: wrap the variables and strip the
meta inside the registered `mutationFn`.

```ts
type QueueMeta = { submittedAt: number; queuedOffline: boolean; idempotencyKey: string }
type Queued<T> = { body: T; meta: QueueMeta }

function queued<T>(body: T, idempotencyKey: string): Queued<T> {
  return { body, meta: { submittedAt: Date.now(), queuedOffline: !onlineManager.isOnline(), idempotencyKey } }
}

// registered default — meta is stripped before the server call
queryClient.setMutationDefaults(["pull-fulfill"], {
  mutationFn: ({ body }: Queued<{ pullId: string; body: ProjectPullFulfill }>) =>
    ProjectPullsService.fulfillProjectPull(body),
})
// call site:  fulfillMutation.mutate(queued({ pullId, body }, idempotencyKey))
```

- **Stale gate** (reconnect): `divertStaleMutations` reads each paused mutation's `meta.submittedAt`;
  stale ones are POSTed `STALE` and removed; the rest `resumePausedMutations()` as today.
- **Conflict catch**: a replayed mutation that 409s → the mutation-cache `onError` sees
  `meta.queuedOffline === true` + status 409 → `captureConflict` POSTs `CONFLICT`. A live 409
  (`queuedOffline === false`) is untouched → the screen's existing toast fires.
- **`idempotencyKey`** in meta reuses the action's own key where it has one (sales/receipts). Pull
  fulfill has **no** request idempotency key — its backend replay-safety comes from *deterministic
  movement keys* derived at fulfill (`models.py:1319-1321`) — so it gets a generated key used **only**
  to dedupe the review-queue record.

## 6. Error handling & edge cases

- **Failed divert POST** — swallowed + logged; idempotent ingest makes a later retry safe; never
  blocks other replays.
- **Non-409 replay failure (e.g. 5xx)** — out of scope; falls through to the normal error toast, not
  diverted. Known boundary: PRD specifies only conflict + stale. (A truly-still-offline network causes
  TanStack to re-pause, not error, so this only bites on a genuine server error during a live
  connection.)
- **Online 409** — unchanged plain-language error; no admin divert.
- **Offline-origin marker edge** — a mutation submitted *online* that drops mid-flight and replays is
  marked `queuedOffline:false`; a 409 there is treated as a live conflict. Rare; acceptable.

## 7. Testing (TDD)

- **Unit** — `frontend/tests/sync-producer.spec.ts`, pure-logic style like `receive-form.spec.ts`:
  - `isStale` boundary (6d 59m → false, 7d 01m → true).
  - `buildSyncReviewItem` kind/payload/key mapping for all three kinds.
  - `divertStaleMutations` against a fake mutation cache: diverts stale, leaves fresh, removes
    diverted, ignores non-paused.
  - Error-handler branch table: offline-409 → capture; online-409 → ignore; 401 → logout.
- **E2E** — mirror `sale.spec.ts`'s harness (synthetic `window "offline"` event + IndexedDB-persist
  reload; network-level offline can't be used because dev runs without a service worker,
  `sale.spec.ts:195-206`):
  - **(a)** pull offline → reload → reconnect → replays exactly once (idempotent).
  - **(b)** conflict: fulfill a pull offline while it is fulfilled online meanwhile → on reconnect a
    `CONFLICT` item appears in the admin queue.
  - Staleness is covered by unit tests (no real 7-day wait); an optional E2E may inject a past
    `submittedAt`.

## 8. Risk gate (CLAUDE.md §5)

**Not** an append-only / FIFO / stock-movement change: no consumption code is modified — pulls only
*queue the existing fulfill call*, and the producer only *reads failures* and posts to an existing
queue. So `ecc:database-reviewer` is **not** warranted (no schema/movement changes). Standard
`superpowers:requesting-code-review` applies. Because a queued **sale** payload can carry prices,
add **`ecc:security-reviewer`** (payload handling) as belt-and-suspenders, matching the original
sync-review plan's caution.

## 9. References

- PRD v3.0 §8.3 offline claims: `docs/client/2026-06-02-castranova-pos-v3.0-prd.md:332-337`; success
  metric line 136.
- Backend queue: `backend/app/api/routes/sync_review.py`; models `backend/app/models.py:1015-1092`
  (`SyncReviewItem`, `SyncReviewItemCreate`, enums `:110-117`).
- Shipped offline mechanism: `frontend/src/lib/query-client.ts:37-48`,
  `frontend/src/main.tsx:19-47`, template `frontend/src/routes/_layout/sale.tsx:173-202`.
- Offline E2E harness to mirror: `frontend/tests/sale.spec.ts:195-233`.
- Deferral of record: `docs/superpowers/plans/2026-06-06-castranova-part4.3-sync-review.md:8`.
- Deferred sibling (blocks tickets-offline): CLAUDE.md backlog — `ServiceTicketPart` idempotency.

## 10. Open questions

None blocking. The tickets-offline follow-on spec depends on a prior backend decision (atomic submit
endpoint vs. adding `idempotency_key` to `ServiceTicketPart`); out of scope here.
