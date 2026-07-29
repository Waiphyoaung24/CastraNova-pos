# Sync-Review Pending Notification — Design

**Status:** Approved design (brainstorming), 2026-07-29. Not yet planned or implemented.
**Branch:** `feat/sync-review-notification` (off `dev`).
**Author context:** The sync-review queue (M020, producer shipped 2026-07-11) has no notification
path. Admins learn an item exists only by opening `/sync-review` and looking.

---

## 1. Problem

`NotificationEvent` (`models.py:127`) carries four events — `LOW_STOCK`, `OVERRIDE_PENDING`,
`PULL_FULFILLED`, `PULL_SHORT`. None covers sync review, and `sync_review.py` never calls
`app.services.notify`. So an offline mutation that lost a write-conflict, or one held back by the
7-day stale cap, sits in the queue silently until an admin happens to visit the page. There is no
badge, no toast, and no push. The queue page uses a plain `useQuery` with no `refetchInterval`
(`sync-review.tsx:60`), so even an admin already on the page won't see a new arrival until the
query refetches.

## 2. Scope

**In:**

1. A fifth `NotificationEvent`, `SYNC_REVIEW_PENDING`, delivered over the existing FR-018 fan-out
   (Telegram / LINE / Viber).
2. A producer fired from the ingest route, off the request hot path.
3. Per-recipient burst suppression, so one reconnect cannot fan out into a run of near-identical
   messages.

**Out (explicitly):**

- **In-app surfacing** — a sidebar badge, a toast, or polling on the queue page. Separate concern,
  separate spec. This design covers push only.
- **A new push channel.** Rides the three that exist.
- **Notifying on resolve/discard.** Triage is an admin acting on their own queue; telling them what
  they just did has no recipient.
- **`ServiceTicketPart` idempotency** (CLAUDE.md backlog). Unrelated, and not blocking.

## 3. Decisions

### 3.1 Burst policy: instant first message, 5-minute per-recipient cooldown

The ingest endpoint is not hit one item at a time. On reconnect, `divertStaleMutations()`
(`query-client.ts:110`) sweeps the paused-mutation cache and posts every item past the 7-day cap —
`void postSyncReviewItem(item)` inside the loop, unawaited, so the POSTs land concurrently. Items
then continue to trickle in as `resumePausedMutations()` replays and individual mutations 409.

**Chosen:** notify immediately on the first item, then suppress further sends to that admin for
5 minutes. The first message is never delayed; the cooldown only mutes follow-ups.

**Rejected — one message per item.** Matches the existing producers, but a device offline past the
stale cap could push a dozen near-identical messages in seconds, and admins mute channels that do
that.

**Rejected — periodic digest.** Quietest, but there is no scheduler in the project today.

**Rejected — client-supplied `sync_batch_id` + atomic batch claim.** Would group a burst exactly
rather than by a time proxy: one UUID per reconnect sweep, claimed server-side with
`INSERT … ON CONFLICT DO NOTHING` so parallel POSTs cannot double-notify. Dropped on volume
grounds. A `CONFLICT` item requires a genuine conflict (insufficient stock, `crud.py:1172`; a unit
already sold) — most replays simply succeed. A `STALE` item requires a device forgotten for over a
week. The realistic arrival is one or two items, where a cooldown never engages at all. The batch
scheme costs a column, a table, a migration, and batch-id lifecycle threaded through two separate
replay paths (`main.tsx:56` and the login replay at `useAuth.ts:36`) to improve a rare tail case.

### 3.2 Cooldown scope: per recipient

Suppression keys on `target_user_id`, not globally on the event. An admin who enrolls or opts in
mid-burst still receives the next message, and one admin's delivery never silences another's.

### 3.3 A failed send starts the cooldown

`notify()` writes a `notificationlog` row for failures too, including
`"<channel> recipient id not set (not enrolled)"` (`notify.py:343`). The cooldown query therefore
counts rows of **any** status.

Counting only `SENT` would mean an admin who never enrolled generates a fresh `FAILED` row on every
single ingest. Counting all statuses caps that at one row per recipient per 5 minutes. The cost: if
a send genuinely fails (Telegram down), that admin waits out the cooldown before the next attempt.
Accepted — the window is 5 minutes and the queue is not an emergency surface.

### 3.4 Message carries the whole PENDING queue, not just this sync

The count is queue depth — what the admin will actually see and act on — not the arrivals from the
sync that triggered the send. A message may therefore read "7 need review" when only one is new.

### 3.5 Recipients: `BKK_ADMIN` only

`SYNC_REVIEW_PENDING` joins `ADMIN_ONLY_EVENTS` (`models.py:144`). The queue's list and resolve
endpoints are `get_admin`-gated, so a staff recipient could be notified about something they cannot
open. This matches the recipient query used by the other three admin producers.

Note the existing subtlety documented at `models.py:232` — `eligible_events` keys off
`role == BKK_ADMIN`, deliberately *not* `deps.is_admin`, so a superuser left at the default staff
role does not receive admin-only events. `SYNC_REVIEW_PENDING` inherits that behaviour unchanged.

## 4. Design

### 4.1 Backend

**`models.py`**

- `NotificationEvent` gains `SYNC_REVIEW_PENDING`.
- `ADMIN_ONLY_EVENTS` gains the same. The comment above it currently reads "the three below" and
  becomes four.

**`crud.py`**

- `create_sync_review_item` returns `tuple[SyncReviewItem, bool]` instead of `SyncReviewItem`,
  surfacing the `replayed` flag that `get_or_replay` already computes and that the function
  currently discards (`crud.py:2280`). The ingest route is the only caller.
- New `count_pending_sync_review_items(*, session) -> SyncReviewPendingCounts` — a small SQLModel
  with named `total`, `stale`, and `conflict` fields, filled from one query grouped by `reason`.
  Named fields rather than a bare tuple: three same-typed ints are trivially transposable at the
  call site, and the render template reads all three.

**`services/notify.py`**

- `_render_text` gains a `SYNC_REVIEW_PENDING` branch. Required, not optional: the function raises
  `NotImplementedError` for unrecognised events by design (`notify.py:476`).
- `notify_sync_review_pending(*, session)` — resolves `BKK_ADMIN` recipients, drops those inside the
  cooldown, counts the queue, delegates to `notify()`. Returns `[]` without sending if every
  recipient is suppressed.
- `notify_sync_review_pending_bg()` — `BackgroundTasks` entrypoint opening its own session and
  swallowing every exception, mirroring `notify_override_pending_bg` (`notify.py:611`).

**`api/routes/sync_review.py`**

- `ingest_sync_review_item` gains `background_tasks: BackgroundTasks` and queues the notify **only
  when `replayed` is False**. Without that guard, a device retrying the same `idempotency_key`
  re-notifies for an item already in the queue.

**Cooldown query** — one grouped statement, no per-recipient round trip:

```sql
SELECT target_user_id, max(created_at)
FROM notificationlog
WHERE event_type = 'SYNC_REVIEW_PENDING'
GROUP BY target_user_id
```

Admins whose latest row is newer than `SYNC_REVIEW_COOLDOWN` (5 minutes, a module constant) are
dropped before `notify()` is called. An admin with no row at all is absent from the result and
therefore always passes — which is what makes a newly-enrolled admin reachable mid-burst.

### 4.2 Message

Rendered in the background task's own session, so counts are accurate at send time rather than at
ingest time:

```
⚠️ 3 offline actions need review
2 conflicts, 1 stale
```

Counts only. `SyncReviewItem.payload` is the raw held mutation and carries prices, so no payload
field reaches the message text — consistent with the rule stated at `notify.py:474`. Ids stay in
the append-only log for audit.

### 4.3 Migration

`m034`, following `m033` (`e5f6a7b8c9d0`):

```sql
ALTER TYPE notificationevent ADD VALUE IF NOT EXISTS 'SYNC_REVIEW_PENDING'
```

Asymmetric downgrade, following `m030`'s precedent: Postgres cannot drop a value from an enum
without recreating the type and rewriting every dependent column, so the downgrade is a no-op that
documents why. The value is harmless once unreferenced. PG 12+ permits `ADD VALUE` inside a
transaction block provided the value is not *used* in the same transaction, which this migration
does not do.

### 4.4 Frontend

SDK regeneration only — `bun run generate-client`, never inside the frontend container.

The preferences grid is data-driven: `groupByEvent` builds rows from whatever the API returns and
labels them with `humanize()` (`notifications.tsx:55,137`). Once `eligible_events()` includes the
new event, the checkbox row appears on its own. No component changes.

## 5. Error handling

- The notify is best-effort throughout. `notify()` never raises to its caller, and the `_bg`
  wrapper swallows and logs anything that escapes.
- A notify failure can never affect the already-committed ingest — it runs after the response, in
  its own session.
- Ingest remains idempotent and rate-limited; the notify path adds no new failure mode to it.
- Every send outcome, success or failure, lands as one append-only `notificationlog` row for the
  weekly review that FR-018 already assumes.

## 6. Testing

pytest (`backend/tests/`), against the existing mocked `_post` seam:

1. Ingesting a new item queues a notify to every `BKK_ADMIN`.
2. Re-POSTing the same `idempotency_key` does **not** notify.
3. A second item inside the cooldown is suppressed; one after it is not.
4. Suppression is per recipient — an admin with no prior log row is notified even while another is
   suppressed.
5. A `FAILED` prior row suppresses (§3.3).
6. Staff-role users are never recipients.
7. `_render_text` renders total and per-reason counts, and leaks no `payload` key.
8. `alembic upgrade head` applies cleanly on a DB at `m033`, and the enum accepts the new value.

**No E2E.** The Playwright suite already covers the ingest path (`sync-review.spec.ts`,
`sync-producer.spec.ts`). The notification is a backend fan-out over a mocked HTTP seam, which
pytest covers directly and Playwright cannot observe.

## 7. Risk

Low. No stock movement, no FIFO consumption, no money, no ledger write. The one schema change is
an additive enum value. The one behavioural change to existing code is
`create_sync_review_item`'s return type, whose single caller changes in the same commit.
