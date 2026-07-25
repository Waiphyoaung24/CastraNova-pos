# Receive date picker — design

**Date:** 2026-07-25
**Status:** Approved, ready for implementation plan
**Driver:** The holding-period report is wrong for late-entered deliveries.

---

## Problem

The Receive page (`frontend/src/routes/_layout/receive.tsx`) has no date field on either
tab. `received_at` is set entirely server-side from the column default (`now()`), so a
delivery that physically arrived on 10 Jul but was keyed in on 25 Jul is recorded as
arriving on 25 Jul.

`holding_period_report` computes `now() - received_at` for in-stock serialized units and
for the oldest active quantity batch per SKU (`crud.py:1597`, `crud.py:1632`). A late
entry therefore under-reports holding days by exactly the entry delay, which is the bug
being fixed.

`received_at` is also the FIFO sort key (`ORDER BY received_at, id` at `crud.py:1152`,
`crud.py:1921`, `crud.py:1995`, `crud.py:4689`). Holding period and FIFO read the same
column, so making holding period accurate necessarily makes FIFO order follow the picked
date. This is intended: stock that physically arrived first should both age first and be
consumed first.

---

## Decisions

| Question | Decision |
|---|---|
| Which tabs | Both — Serialized (`Unit.received_at`) and Quantity (`PartBatch.received_at`) |
| Date → timestamp | Picked date + the server's current clock time |
| Future dates | Blocked, in the UI (`max`) and on the server (422) |
| `batch_no` prefix | Follows the picked date |
| Movement `occurred_at` | Unchanged — stays real-time |
| Granularity | One date per receipt, not per piece |

### Why picked date + current clock time

The rejected alternative was collapsing to midnight UTC. Two receives of the same SKU on
one day would then both store `00:00:00Z`, and FIFO's tiebreaker is `id` — a **random
uuid4** (`models.py:647`), not a sequential one. Which batch's cost lands in a sale would
become non-deterministic. Composing with the current clock time keeps every receive
distinct, so same-day FIFO follows entry order, which is the best available proxy for true
arrival order.

It also means picking today — the default — stores exactly what the system stores now.

### Why the client sends a date, not a timestamp

The client sends `"2026-07-10"`; the server composes the timestamp. A wrong tablet clock
cannot forge a `received_at`, and the future-date rule reduces to a plain date comparison
(`received_date > date.today()`), so picking today still stores *now* without tripping the
check.

### Why `occurred_at` stays real-time

The movement ledger is append-only audit truth: "this row was written at 14:32 on 25 Jul."
Backdating it would corrupt the audit log's chronology and its `(actor_user_id,
occurred_at DESC)` ordering. `received_at` answers *when the goods arrived*;
`occurred_at` answers *when we recorded it*. A backdated receipt makes those legitimately
differ, and the gap is itself an audit signal.

---

## Data model

**No schema change. No Alembic migration.** `Unit.received_at` (`models.py:650`) and
`PartBatch.received_at` (`models.py:845`) already exist as NOT NULL timestamps with
`now()` server defaults. Only the source of the value changes.

Two request models gain one optional field each:

```python
class ReceiveSerializedRequest(SQLModel):
    ...
    received_date: date | None = None   # None → today

class ReceiveQuantityRequest(SQLModel):
    ...
    received_date: date | None = None
```

Optional with a `None` default preserves every existing caller: `seed_demo.py` (3 call
sites), the backend test suite, and any cached frontend bundle.

---

## Backend changes

**`crud.receive_serialized` / `crud.receive_quantity`** each take
`received_at: datetime | None = None` and pass it to the `Unit(...)` / `PartBatch(...)`
constructor, falling through to the existing column default when `None`.

**`receive_quantity`** additionally threads the date into batch numbering:
`next_batch_no(today=received_date or date.today())` (`crud.py:1089`), so a receipt
backdated to 10 Jul is labelled `20260710-{SKU}-001`. The advisory lock is keyed on
`hashtext(yyyymmdd), hashtext(sku)` (`crud.py:1003`), so it keeps serialising correctly
against a backdated day's sequence; `UNIQUE(product_id, batch_no)` remains the backstop.

**`api/routes/receipts.py`** composes and validates:

```python
received_at = (
    datetime.combine(payload.received_date, get_datetime_utc().timetz())
    if payload.received_date is not None
    else None
)
```

with a 422 when the date is in the future. The UI cap is convenience; the server is the
enforcement point.

**Timezone skew.** The client's `todayISO()` is the operator's *local* date; the server's
`date.today()` is UTC. Local operating timezones are Yangon (UTC+6:30) and Bangkok
(UTC+7), both ahead of UTC, so between local midnight and ~06:30 the local date is one day
ahead of the UTC date. A strict `> date.today()` check would reject the default date
during those hours. The check is therefore:

```python
if payload.received_date > date.today() + timedelta(days=1):
    raise HTTPException(status_code=422, detail="received_date cannot be in the future")
```

The one-day tolerance is exactly the maximum skew for the intended operating timezones,
not a loose margin.

It does mean a `today+1` date is accepted from *any* client, not only an ahead-of-UTC one.
A client in UTC+12, or one with a misconfigured system clock, can therefore land a
`received_at` up to ~24h ahead of real `now()` — not the few hours the Yangon/Bangkok case
produces. The consequence is bounded and cosmetic: such stock reports 0 holding days and
sorts last in FIFO, so it is consumed last. It cannot escalate privilege, and both
endpoints are admin-only with the real entry time preserved on the movement ledger.
Tightening this would require the client to send its UTC offset, which is itself
client-controlled and so buys nothing.

Replay is unaffected — an idempotent replay returns the stored row without re-dating it,
because the existing replay branches return before any construction.

---

## Frontend changes

No new dependency: the codebase already uses native `<input type="date">`
(`audit.tsx:194`, `ProjectEditDialog.tsx:150`), and that idiom is matched.

- `QuantityDraft` gains `receivedDate: string`; `SerializedTab` gains a matching
  `useState`. Both initialise to today.
- New pure helper in `lib/receive-form.ts`:
  `todayISO(): string` → local date as `YYYY-MM-DD`.
- Both tabs render `<Input type="date" max={todayISO()}>` in the existing **Delivery**
  section beside Product/Supplier — a per-delivery fact, not a per-piece one. `max`
  disables future dates in the native picker.
- `buildReceiveQuantityRequest` / `buildReceiveSerializedRequest` pass `received_date`
  through.
- `canSubmitQuantity` / `canSubmitSerialized` gain a non-empty, not-in-future date check
  so a cleared field cannot submit.
- Regenerate the SDK with `bun run generate-client` **on the host, never in the frontend
  container** — the container regenerates from a stale image-baked `openapi.json` and
  silently drops new fields.

### Offline replay

The serialized tab queues mutations offline (`lib/query-client.ts`). Today a receive
entered Friday and replayed Monday records Monday. Capturing the date at entry time means
it records Friday — an incidental improvement, not a goal.

---

## Testing

FIFO-touching work is high-risk per `CLAUDE.md`, so stages 3–5 run in full, with
`ecc:database-reviewer` + `ecc:security-reviewer` in addition to the standard review.

**pytest**

- `received_date` omitted reproduces current behaviour exactly.
- A backdated quantity receive lands the correct `received_at` *and* the matching
  `batch_no` prefix.
- A backdated batch is consumed **before** an already-present newer batch, and books its
  own cost into the sale.
- `holding_period_report` reports the backdated age, for both a serialized unit and a
  quantity batch.
- A future date returns 422 on both endpoints; a date exactly one day ahead of UTC today
  is accepted (timezone-skew tolerance).
- Two same-day receives get distinct `received_at` and sequential `-001` / `-002`.
- An idempotent replay of a backdated receive returns the original row unchanged.

**vitest** — `todayISO()` shape; request builders carry the field; submit guards reject
empty and future dates.

**Playwright** — one backdate-and-verify pass per tab, with `E2E_SKIP_DB_RESET=1`.

---

## Known trade-off

This makes FIFO consumption order editable by an admin through the receive form. That is
inherent to fixing holding period — both read `received_at` — and is the correct
behaviour. But a typo'd year on a backdated entry silently reorders which stock a sale
draws its cost from. The future-date block catches the forward direction; nothing catches
`2025` typed for `2026`.

Deliberately **not** guarded, per YAGNI. If it becomes a real problem, the cheap fix is a
soft UI confirmation when the picked date is more than N days back.
