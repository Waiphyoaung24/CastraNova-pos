# Design: Atomic service-ticket record endpoint (offline-safe)

**Date:** 2026-07-11
**FRs:** FR-008 (on-site maintenance recorded at the warehouse), §8.3 (offline: "maintenance entries are saved on the device first").
**Risk:** HIGH — touches FIFO stock consumption. Requires design doc → failing test first → `ecc:database-reviewer` + `ecc:security-reviewer` on review, and the FIFO concurrency test before merge (CLAUDE.md §5).

## Problem

A service ticket is submitted from `/tickets` as **three dependent server calls** — `open` → `addPart`(×N) → `close` (`tickets.tsx:112`). The middle call, `add_service_ticket_part`, is **not idempotent** (`crud.py:2399` appends a row per call). So:

1. The flow **cannot be safely offline-replayed** — the offline queue (`query-client.ts:134`) is built for one idempotent POST per queued action (sales/receipts/pull-fulfill). Registering the 3-call orchestration would let an automatic replay/retry re-add parts → duplicate `ServiceTicketPart` rows → over-consumed stock + double-charged customer. This is the known CLAUDE.md backlog footgun.
2. The PRD (§8.3 line 334) explicitly promises maintenance entries work offline; today they just fail offline.
3. The three-call split also permits an **orphaned open ticket** on partial failure — a state the PRD does not model (FR-008: "opened and closed at the warehouse"; no open-ticket queue exists, unlike Project Pulls).

## Approach (decided with owner)

Replace the three granular endpoints with **one atomic, idempotent `record` endpoint**, mirroring `create_sale` (`crud.py:2062`). One `idempotency_key` covers the whole ticket, so any replay returns the single already-recorded ticket. The UX is unchanged — `/tickets` already collects the whole form in memory and submits on one "Close ticket" click.

### Backend

**Models (`models.py`):**
- Add `ServiceTicketRecordRequest`: `customer_id, issue, notes, resolution, idempotency_key, parts: list[ServiceTicketPartCreate]` (reuse existing `ServiceTicketPartCreate` for the nested lines).
- Remove `ServiceTicketCreate` and `ServiceTicketClose` (only the granular routes used them). Keep `ServiceTicketPublic`, `ServiceTicketPartPublic`, `ServiceTicketPartCreate`.
- **No column change → no Alembic migration.** `ServiceTicket.idempotency_key` + its UNIQUE constraint already exist; `ServiceTicketPart` needs no key (parts are never added by a separate dedup-less call).

**crud (`crud.py`):** add `record_service_ticket(*, session, customer_id, issue, notes, resolution, parts, idempotency_key, actor_user_id)` — one transaction, mirroring `create_sale`:
1. Idempotency pre-check by key → return existing ticket (+ `_assert_replay_actor`), no re-consume.
2. Validate customer exists; validate every part up front (fail fast, no orphan): SKU resolves to a QUANTITY product; reject duplicate SKUs ("merge into one", as `create_sale` does — the UI already merges by SKU); reject an override id cited on two lines.
3. Lock cited overrides FOR UPDATE in id order (lock order: overrides → batches — same as `create_sale`/`close`, no cycle).
4. Create the `ServiceTicket` (closed immediately: `closed_at` set), flush.
5. For each part in deterministic product-id order: `consume_quantity_fifo` → `PartMovement(MAINTENANCE_OUT, from=YGN_WH, to=CUSTOMER, service_ticket_id, actor_user_id, idempotency_key=uuid5(idempotency_key, f"maint:{idx}:{product_id}"))` + link cost_lines; create `ServiceTicketPart(unit_price_thb = repair_price or override price via `_apply_override_price(target_kind=SERVICE_TICKET_PART)`)`.
6. `commit()` with the same `IntegrityError` handling as `create_sale`: override-collision → 409; else lost idempotency race → return winner (+ actor bind); reset `session.info["low_stock_crossed"]` on rollback.
- Remove `open_service_ticket`, `add_service_ticket_part`, `close_service_ticket`. Keep `get_service_ticket`, `list_service_ticket_parts`.

**Route (`service_tickets.py`):** replace the three POSTs with `POST /service-tickets/record` → `record_service_ticket`, response `ServiceTicketPublic`, `get_current_user` dep, keep the existing low-stock `BackgroundTasks` dispatch (`pop_low_stock_crossed`). Keep `GET /{ticket_id}`.

### Frontend
- SDK regen (`bun run generate-client`).
- `tickets.tsx`: replace `submitTicket`'s 3-call orchestration with one `ServiceTicketsService.recordServiceTicket({ requestBody })`; build the body from existing `buildTicketSubmission` state; wrap with `queued(body, idempotencyKeyRef.current)`; keep key-rotate-on-success.
- `query-client.ts`: register `setMutationDefaults(["tickets"], …)` mirroring `["sales"]`. The 409-divert + STALE producer (`sync-producer.ts`) is key-generic → no producer change.

## Testing (TDD, failing test first)

- **crud**: happy path (ticket closed, parts FIFO-consumed, movements + cost_lines written, repair price applied); **idempotent replay** (same key → same ticket, stock consumed once, no duplicate parts) — pins the fixed backlog bug; insufficient stock → 409, nothing committed; override price applied; duplicate-SKU → 422.
- **FIFO concurrency (mandatory)**: two concurrent `record` calls on the same limited stock consume correctly, no over-consumption (extend the existing `test_fifo_concurrency.py` harness).
- **route**: `POST /record` closes + consumes; auth required; low-stock alert dispatched on crossing.
- Rewrite `test_service_tickets.py` to the record endpoint; update the ~5 setup-helper files that build tickets via the granular endpoints (`test_replay_user_binding.py`, `test_movement_fks.py`, `test_reports.py`, `test_low_stock.py`, `test_customer_dashboard.py`).
- **E2E**: offline → close a ticket → reconnect → replays exactly once, parts consumed once (mirror the sale-offline spec).

## Out of scope / non-goals
- No persistent open-ticket state, queue, or management UI (PRD omits it deliberately).
- No `ServiceTicketPart.idempotency_key` / migration (the whole-ticket key subsumes it).
- Per-list-view exports, drill-downs, etc. (unrelated backlog).

## Verification
`bash scripts/test.sh`-equivalent (isolated worktree stack) green incl. idempotency + FIFO concurrency; `bun run test` offline E2E; ruff + mypy strict + biome clean; SDK regenerated & committed; manual: record a multi-part ticket online (one closed ticket, correct stock draw), then offline→close→reconnect (single replay, no dup parts).
