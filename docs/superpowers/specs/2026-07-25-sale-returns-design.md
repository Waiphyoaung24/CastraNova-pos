# Sale Returns — Design

**Date:** 2026-07-25
**Status:** Approved design, pending implementation plan
**Scope:** Customer returns of sale lines (UNIT and PART), restocked as sellable, admin-only.

## Problem

CastraNova-POS has no way to record a customer returning a purchased item. A return must:

1. Put stock back — restore FIFO batch quantities (parts) or unit state (serialized) — without violating the append-only ledgers.
2. Reverse the sale's margin contribution on the channel-margin report, exactly (no cost drift).
3. Leave a complete audit trail: what was returned, when, by whom, against which sale, at what cost.

## Decisions (user-approved)

| Question | Decision |
|---|---|
| Scope | Sale returns only. Ticket-part returns and return-to-supplier are future work. |
| Report month | The **return month** changes (event keyed on `returned_at`). Past months stay immutable. |
| Restock fate | Restock as sellable at original FIFO cost. (Defective/write-off returns: future work — today, return then use the existing write-off adjustment.) |
| Granularity | Per line and per quantity; multiple partial returns per sale allowed, capped at quantity sold. |
| Refund amount | Fixed at the original `SaleLine.unit_price_thb`. No discretion, no restocking fee. |
| Permissions | Admin only (`get_admin`), like stock adjustments. |
| Report presentation | Separate **SALE RETURNS** row in the channel view (negative revenue/COGS). Product/customer breakdowns net returns into the matching row. |
| UI | Integrated into the existing stock-adjustment page tabs (no new tab). One item type per operation. |
| Reason | Required free-text `reason` on every return, like `StockAdjustment.reason`. |
| Offline | Online-only; no offline queue (admin desk action, unlike counter sales). |

Approach chosen: **first-class `SaleReturn` entity with appended reversal movements** (over extending `StockAdjustment` or negative credit-note sales), because it preserves the original FIFO cost basis via the sale's `CostLine`s and follows the codebase's append-only + CostLine pattern.

## Data model (migration m034)

New enum value: `MovementType.RETURNED` (used by both `UnitMovement` and `PartMovement`).

New state-machine edge in `backend/app/core/state_machine.py`: `SOLD -> IN_STOCK` (used only by the return path).

New tables in `backend/app/models.py` (with `*Create`/`*Public` schema variants per convention):

**`SaleReturn`**
- `id` UUID PK
- `sale_id` FK -> `sale`
- `created_by_user_id` FK -> `user`
- `idempotency_key` UNIQUE
- `reason` (required text)
- `returned_at` (indexed — the report's date key)
- `total_refund_thb`, `total_cogs_restored_thb`

**`SaleReturnLine`**
- `id` UUID PK
- `sale_return_id` FK -> `salereturn`
- `sale_line_id` FK -> `saleline`
- `quantity` (CHECK `> 0`; always 1 for UNIT lines)
- `unit_price_thb` (refund basis, snapshot copied from the sale line)
- `cogs_restored_thb` (exact cost restored, derived from the original CostLines)

Notes:
- These tables get **no** append-only trigger, but there is no update/delete endpoint — insert-only in practice. The movements the return appends (`PartMovement`, `UnitMovement`, `CostLine`) are covered by the existing `reject_ledger_mutation` triggers automatically.
- The over-return invariant (sum of returned qty per sale line <= qty sold) spans rows, so it is enforced in `crud.py` under `FOR UPDATE` locks, not by a CHECK.
- Migration m034: two tables, FKs, `returned_at` index. The `MovementType` change is Python-side (values stored as strings) — verify against existing enum handling during implementation.

## Recording a return (crud)

Endpoint: `POST /sales/{sale_id}/returns` — admin-only. Payload: `{ idempotency_key, reason, lines: [{sale_line_id, quantity}] }`. The API accepts multi-line returns even though the integrated UI posts one line per operation.

**Idempotency:** same key -> replay returns the existing `SaleReturn` (no double restock); same key with different payload -> 409. Per-movement idempotency keys derived via `uuid5`, matching `create_sale`.

**Validation under lock (409 on failure):**
- Every line belongs to the sale.
- Per line: `already_returned + requested <= quantity sold` (prior `SaleReturnLine`s locked and summed).
- UNIT lines: quantity must be 1 and the unit's `current_state` must be `SOLD`.

**PART lines — exact FIFO rollback:**
1. Find the sale line's original `PartMovement(SOLD)` and its `CostLine`s (which record exactly which batches supplied the stock and at what `unit_cost_thb`).
2. Restore in **reverse consumption order** (newest-consumed cost line first). Deterministic across multiple partial returns: the already-returned quantity for the line is mapped onto the cost lines in the same reverse order, so each new return continues where the last stopped.
3. Lock the affected `PartBatch` rows `FOR UPDATE` in id order (same discipline as `consume_quantity_fifo`), increment `remaining_qty` by the restored amount. Safe against the `remaining_qty <= received_qty` CHECK: a batch is only ever restored by amounts it supplied to this sale, and positive adjustments mint new batches rather than touching old ones.
4. Append `PartMovement(RETURNED, quantity, sale_id=...)` plus new `CostLine`s at the **original** `unit_cost_thb` — audit chain and COGS reversal both exact, no cost drift.

The batch here is a cost bucket, not a physical bin: nobody knows which physical piece came back, and it doesn't matter. FIFO consumption was itself an accounting convention; the return reverses that convention deterministically.

**UNIT lines:**
- Lock the unit, `assert_unit_transition(SOLD -> IN_STOCK)`, set `current_state = IN_STOCK`, restore `current_location_id` to the SOLD movement's `from_location_id`.
- Append `UnitMovement(RETURNED, sale_id=...)`. COGS restored = `unit.purchase_cost_thb`.

**Totals:** `total_refund_thb = SUM(qty * sale_line.unit_price_thb)`; `total_cogs_restored_thb = SUM(restored cost)`. Everything in one DB transaction — any line failing rolls back the whole return. Low-stock machinery untouched (returns only add stock).

**Supporting read endpoint** for the UI: sale lookup that resolves a unit barcode to its sale, lists recent sales containing a product, and includes per-line already-returned quantities.

## Margin report changes

All aggregations key on `SaleReturn.returned_at` within the existing `_month_window`:

- **Channel view (`_channel_rows`):** new `SALE_RETURN` row — `revenue = -SUM(total_refund_thb)`, `cogs = -SUM(total_cogs_restored_thb)`, margin derived as usual. Grand totals therefore net correctly.
- **Product and customer views:** returns net into the matching product/customer row for the return month (join `SaleReturnLine -> SaleLine` for product/qty; `SaleReturn -> Sale.customer_id` for customer). No per-product returns rows.
- **Prior months untouched:** a June sale returned in July changes only July's report. June prints identically forever.
- **PDF/XLSX exports** inherit the new row automatically.
- COGS for returns uses `SaleReturnLine.cogs_restored_thb` (exact, from CostLines) — consistent with the report's existing preference for exact CostLine-derived COGS over rounded snapshots.

## Frontend (integrated into stock-adjustment page)

`frontend/src/routes/_layout/stock-adjustment.tsx` (admin-guarded), no new tab:

- **Unit tab:** scanning a barcode that resolves to a `SOLD` unit offers **"Return to stock"** (instead of write-off, which remains for `IN_STOCK` units). Shows the originating sale and fixed refund; requires reason; one confirm.
- **Quantity tab:** a third action alongside Found/Lost: **"Return"**. After picking the product, a **sale picker** lists recent sales containing it with per-line returnable counts; admin selects the sale, enters quantity (capped at returnable), reason, confirms. Fully-returned sales shown disabled.
- Each operation posts a single-line `SaleReturn`. Refund is display-only (fixed at original price).
- Pure logic (returnable caps, payload building) lives in `frontend/src/lib/` with colocated vitest tests, mirroring `stock-adjustment.ts`.
- SDK regenerated after backend changes; on success invalidate `["stock-on-hand"]`, `["search-sku"]`, `["search-serial"]`.
- Online-only: not wired into the offline queue.

## Error handling

- **403** non-admin.
- **404** sale/line/unit not found; line not part of the sale.
- **409** over-return; unit not in `SOLD` state; idempotency-key reuse with different payload.
- **422** quantity <= 0; quantity != 1 on a UNIT line; missing reason.
- One transaction per return; no partial restocks.

## Testing (high-risk: stages 3–5 mandatory)

- **pytest:** multi-batch restore exactness (5 sold from 2 batches, return 4, verify `remaining_qty` and restored cost per batch); second partial return restores the correct remainder; over-return 409; idempotent replay -> single restock; unit `SOLD -> IN_STOCK` and re-sellable; already-returned unit 409; staff 403; report shows `SALE_RETURN` row in the return month only; exports include it.
- **Concurrency:** existing FIFO concurrency test (plan Task 2.3) must pass; new test that a concurrent return + sale on the same product neither deadlocks nor corrupts `remaining_qty`.
- **vitest:** returnable-cap and payload logic in `frontend/src/lib/`.
- **Playwright E2E:** unit scan -> return -> sellable again; quantity return via sale picker. Run with `E2E_SKIP_DB_RESET=1`.
- **Review stage:** `requesting-code-review` plus `ecc:database-reviewer` and `ecc:security-reviewer` (required for ledger/money changes).

## Out of scope (explicit)

- Ticket-part returns (tickets do consume parts via `MAINTENANCE_OUT`; same mechanism can extend later).
- Return-to-supplier.
- Defective returns / restocking fees / adjustable refunds.
- Refund payment processing (this records the inventory + margin reversal; cash handling is outside the system today).
- Deleting or editing a recorded return (record a compensating sale/adjustment if ever needed).
