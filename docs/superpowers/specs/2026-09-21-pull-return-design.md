# Project pull return — design (2026-09-21, rev 2 after review)

## Problem
A pull deducts stock at create (`PROJECT_OUT`). Nothing can bring it back:
- `PROJECT_OUT` is terminal for units (no state-machine edge back).
- Cancel is refused once stock has left (no reversal movement exists).
- "Found" creates a new batch at a typed cost and cannot resurrect a unit.

Two cases to cover:
- **A. Undo** — a PENDING pull that was never handed out.
- **B. Came back** — items handed to the project, later returned unused
  (also the surplus a SHORT hand-out left deducted).

## Decisions
| Question | Answer |
|---|---|
| Approach | Return from pull, no new tables |
| Who | Staff and admin |
| COGS month | Month it came back (closed months never change) |
| Reason | Not required — ledger has who + when |

## Behaviour
- **Return (FULFILLED / SHORT / CANCELLED pulls — any pull not PENDING):** pick lines + quantities. UNIT line
  qty must be 1. **Cap is per (pull, product)**, read from the ledgers:
  Σ `PROJECT_OUT` qty − Σ `RETURNED` qty where `project_pull_id = pull.id`
  (units: count of movements). Movements carry no line id, so a line is
  attributed to its movement by product — which requires:
- **`create_project_pull` rejects two PART lines for the same product** (422).
  UNIT lines for one product are normal (each carries its own serial).
  Dev has none (checked 2026-09-21); check prod before release. A legacy pull that
  has them still works: its whole product balance is returnable from the
  first matching line.
- **Cancel (PENDING pull that deducted):** returns every line at cap, then the
  existing CANCELLED flip, one transaction. Replaces today's 409. Cancel on
  SHORT is unchanged (given-out stock stays out; return it explicitly).
- **Units:** new edge `(PROJECT_OUT, RETURNED) -> IN_STOCK`. Rewrite the
  comment at `state_machine.py:22-23` ("single edge back" no longer true).
  Unit goes back to the `PROJECT_OUT` movement's `from_location_id`.
- **Parts:** reverse the `PROJECT_OUT` movement's cost lines, newest batch
  first, skipping what earlier returns restored.
- **Movements:** `RETURNED` with `project_pull_id` set (no `sale_id`).
  Movement list already labels this "RETURNED · Project pull" (attribution
  branches on `sale_id` then `project_pull_id`).

## Reuse (not new code)
- Pull the mover half of `_return_unit_line` / `_return_part_line` out into
  `_reverse_unit_out` / `_reverse_part_out` (two callers each: sale returns
  and pull returns). Each caller keeps only its own source lookup — SOLD by
  sale, or PROJECT_OUT by the deterministic key `uuid5(pull.id, "<kind>:<line>")`.
  The part mover copies `sale_id` / `project_pull_id` from its source. Keep the
  `populate_existing=True` re-lock — the cost-line join loads `PartBatch`
  rows unlocked, and SQLAlchemy 2.0 hands back stale identity-map objects
  from a plain `with_for_update()` (context7-confirmed).
- Validation mirrors `fulfill_project_pull`: duplicate / unknown `line_id`
  → 422; over-cap → 409.
- Frontend: per-line qty map with caps from `lib/pull-fulfill.ts`
  (`lineCap`, `FulfillDraft`), not `lib/sale-return.ts` (single-line).

## Idempotency (no header row)
- Request carries `idempotency_key`; movement keys are
  `uuid5(key, "unit:{line}" / "part:{line}")`.
- **Pre-check before any write:** select movements whose `idempotency_key`
  is in the derived set. If found → `_assert_replay_actor` against the
  winner's `actor_user_id` (409 on mismatch, as `_assert_replay_actor`
  does today), 409 if the winner's `project_pull_id` is a different pull, else
  return the current pull. **Plus** the same `IntegrityError` handler
  `create_sale_return` uses, wrapping the flush/commit, for the true race —
  without it a replay is a 500, not a 200.

## Locking
Pull `FOR UPDATE` first; load `ProjectPullLine` rows after the lock (as
`fulfill` does); all cited units in one id-ordered query before the loop
(as `_move_pull_stock` does, not one per line); batches by
`(received_at, id)` — the FIFO global order.

## Reports (Project COGS) — 10 sites, 20 occurrences
- **7 cost sums** (`_channel_rows` 4372/4383, `_product_rows` 4570/4587,
  `_customer_rows` 4694/4710, `_project_rows` 4761/4777,
  `get_customer_dashboard` 4917/4927, `_project_consumed_costs` 4988/5005,
  `_project_consumed_cost` 5022/5032): minimum edit is
  `event_type.in_((PROJECT_OUT, RETURNED))` + `sum(sign * cost)` with one
  module-level `sign = case((event_type == RETURNED, -1), else_=1)`. The
  inner join to `ProjectPull` already excludes sale returns. The **last
  three are lifetime (unwindowed)** — net there unwindowed too; the
  windowed four net on the return movement's `occurred_at`.
  (A shared `_project_cogs` helper would have 7 callers and is justified,
  but is a refactor beyond this task — not required.)
- **1 list** (`_project_consumed_items` 5062/5114): netting doesn't apply —
  include `RETURNED` rows and add `event_type` to
  `ProjectConsumptionRowPublic`.
- `_CONSUMING_EVENTS` / `search_sku` and `_move_pull_stock`: no change.
- Sale-return reporting is untouched (reads `SaleReturn` tables; no query
  sums `RETURNED` movements without `sale_id`).

## API / UI
- Body: `{idempotency_key, lines: [{line_id, quantity}]}` with
  `quantity: gt=0, le=1_000_000`, `lines: min 1, max 200`.
- `POST /project-pulls/{id}/returns` — `CurrentUser` (any logged-in user,
  same as `POST /sales/{id}/returns`). Response: the pull, with per-line
  `returnable_qty` on `ProjectPullLinePublic` (what the UI caps at). **Compute it with one grouped
  query per pull** — `_to_public` is already N+1 per line. No cost fields,
  so no staff redaction variant.
- Regenerate the SDK (`bun run generate-client`).
- Pull detail: "Return items" dialog (qty per line, capped). `PullQueue.tsx`
  `cancellable` drops `!pull.stock_deducted`.

## Out of scope / no migration
- `fulfill` after a partial return on a PENDING pull — not possible; PENDING
  pulls only allow cancel.
- Migration: none. `RETURNED` is on the native enum since m035; no CHECK or
  trigger ties `event_type` to `sale_id`; `returnable_qty` / `event_type` are
  response-only. Verify `alembic check` is clean.

## Tests (high-risk: FIFO + ledger)
- Unit return round-trip; illegal state 409; over-cap 409.
- Part partial returns restore exact batches/costs; over-cap 409.
- Replay with same key → 200, no double credit; replay by another user → 409;
  key reused on another pull → 409.
- Two PART lines for one product at create → 422.
- Cancel of deducted PENDING restores all stock.
- Concurrent return vs sale on same product: no lost update (mirror
  `tests/crud/test_return_concurrency.py`).
- Project COGS nets returns in the return month (windowed) and always
  (lifetime); project movement list shows the RETURNED row.
- Staff can return; E2E: return dialog on pull page; Cancel enabled on a
  deducted PENDING pull.
