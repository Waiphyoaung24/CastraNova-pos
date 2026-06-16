# FR-015 Comprehensive Consumption History — Design

**Date:** 2026-06-17
**Status:** Approved (design); pending implementation plan
**Requirement:** PRD FR-015 (Search & Lookup); system-design spec §5 Flow F, §4.4, §6.5
**Risk class:** High (touches FIFO/append-only ledger + cost reads; both-roles surface) — mandatory TDD + `database-reviewer` + `security-reviewer` at review.

## 1. Problem

The Search page (`/search`) ships a partial FR-015:

- **SKU tab** shows received `part_batch` rows + quantity-on-hand, but **not the consumption side** the PRD requires: which sales/projects/tickets/adjustments drew stock down, and **which batch(es) each draw came from**.
- **Serial tab** shows the full `unit_movement` lifecycle but renders raw UUIDs for location / actor / linked sale-ticket-pull, so the "originating Project Pull" and who/where context is opaque.

This was deliberately deferred (parked in `docs/superpowers/plans/2026-06-05-castranova-part4-dashboards.md`) because the consumption history carries cost (`cost_line`), and Search is a both-roles surface where COGS must stay admin-only. This design closes the gap with role-tiered redaction.

## 2. Goals / Non-goals

**Goals**
- SKU consumption history (QUANTITY products): consuming `part_movement` events with counterparty attribution (customer/project), actor, date, and — for admins — full FIFO per-batch cost breakdown.
- Serial view enrichment: resolve location/actor IDs to names and label each movement's originating sale / service ticket / project pull.
- Strict role tiering: admins see cost; staff see attribution without any THB.

**Non-goals**
- No schema change / no Alembic migration (read-only over existing ledgers).
- No SKU consumption history for SERIALIZED products (their consumption is per-unit in `unit_movement` → the Serial tab; serialized events have no `cost_line`).
- No stock mutation, no new write paths.
- No date-range filtering in v1 (bounded most-recent list; revisit if needed).

## 3. Data model (existing — no changes)

The consumption audit chain already exists:

```
part_movement (consuming: SOLD | MAINTENANCE_OUT | PROJECT_OUT | ADJUSTED_OUT)
   ├─ exactly one parent FK: sale_id | service_ticket_id | project_pull_id | stock_adjustment_id
   ├─ actor_user_id, occurred_at, quantity (>0), notes
   └─ cost_line[]  (one per batch drawn; FIFO)
        └─ part_batch_id, quantity, unit_cost_thb, total_cost_thb
```

Key references (verified):
- `consume_quantity_fifo` — `crud.py:749` (writes `CostLine[]`; caller sets `part_movement_id`).
- Consuming call sites: sale `crud.py:1817`, service ticket `crud.py:2061`, project pull `crud.py:2326`, negative adjustment `crud.py:1460`.
- `PartMovement` `models.py:706`; `CostLine` `models.py:776`; `(product_id, occurred_at DESC)` index `models.py:744`.
- Counterparty parents: `Sale` (`customer_id`, `sold_at`) `models.py:1111`; `ServiceTicket` (`customer_id`, `opened_at`/`closed_at`) `models.py:1223`; `ProjectPull` (`project_id`, `customer_id`, `created_by`/`fulfilled_by`) `models.py:1319`; `StockAdjustment` (`reason`) `models.py:913`.
- `MovementType` `models.py:56`: consuming = SOLD, MAINTENANCE_OUT, PROJECT_OUT, ADJUSTED_OUT; adding = RECEIVED.
- Redaction precedent: `is_admin` / `get_admin` / `AdminUser` `deps.py:67`; `_to_public` role branch `sales.py:24`; `SaleStaffPublic`/`SaleLineStaffPublic` omit cost `models.py:1182`.

## 4. API

Two endpoints unchanged in path; handlers gain `current_user: CurrentUser` and branch on `is_admin`.

- `GET /search/sku/{sku}` → `SkuSearchResult` (staff) **or** `SkuSearchAdminResult` (admin).
- `GET /search/serial/{barcode}` → `SerialSearchResult` (enriched; both roles, no cost).

Both already gated `Depends(get_current_user)` at the router (`search.py:10`).

## 5. Response schemas (new Pydantic, in `models.py`)

Separate staff/admin classes (omission, not Optional-None) per the locked redaction pattern.

**SKU consumption (QUANTITY only):**

```
SkuConsumptionDrawAdminPublic   # admin only
  batch_no: str
  quantity: int
  unit_cost_thb: Decimal
  total_cost_thb: Decimal

SkuConsumptionEventPublic        # staff base — NO cost
  event_type: MovementType       # SOLD | MAINTENANCE_OUT | PROJECT_OUT | ADJUSTED_OUT
  occurred_at: datetime
  quantity: int
  reference_kind: str            # SALE | SERVICE_TICKET | PROJECT_PULL | STOCK_ADJUSTMENT
  reference_id: uuid.UUID
  customer_name: str | None
  project_name: str | None
  project_code: str | None
  actor_name: str | None
  notes: str | None

SkuConsumptionEventAdminPublic(SkuConsumptionEventPublic)   # adds cost
  total_cost_thb: Decimal
  draws: list[SkuConsumptionDrawAdminPublic]
```

**SKU result:**

```
SkuBatchPublic           # unchanged (no cost)
SkuBatchAdminPublic(SkuBatchPublic)        # + purchase_cost_thb   (PRD batch attribution)

SkuSearchResult          # staff
  sku, product_id, tracking_mode, total_on_hand
  batches: list[SkuBatchPublic]
  consumption: list[SkuConsumptionEventPublic]      # [] for SERIALIZED

SkuSearchAdminResult     # admin
  sku, product_id, tracking_mode, total_on_hand
  batches: list[SkuBatchAdminPublic]
  consumption: list[SkuConsumptionEventAdminPublic]
```

**Serial enrichment** — extend `SerialMovementPublic` (`models.py:1704`), keeping existing raw IDs, adding:

```
  from_location_name: str | None
  to_location_name: str | None
  actor_name: str | None
  reference_kind: str | None     # SALE | SERVICE_TICKET | PROJECT_PULL | STOCK_ADJUSTMENT
  reference_label: str | None    # e.g. customer name, or "Project <code> — <name>" for a pull
```

No cost on the serial path (serialized search is cost-free for both roles, as today).

## 6. CRUD design (`crud.py`, next to `search_sku`)

- `search_sku(session, sku, *, is_admin)` extended: after building batches, if `tracking_mode == QUANTITY`, fetch consuming `PartMovement` for `product_id` ordered `occurred_at DESC, id DESC`, **LIMIT 200**. Build events; populate cost (`draws` from `cost_line → part_batch`, `total_cost_thb`) only when `is_admin`. Return the admin or staff result accordingly.
- `search_serial(session, barcode)` extended: resolve location/actor/parent labels.
- **Counterparty resolution** branches on the non-null parent FK; mirror `ProjectPullPublic`'s read-time name resolution (`models.py:1416`).
- **No N+1:** collect all `location_id`, `user_id`, and parent FK ids across the page; bulk-`SELECT … WHERE id IN (...)` per entity type; build id→label dicts. For admin draws, bulk-load `cost_line` for the page's `part_movement_id`s and their `part_batch.batch_no`.
- All DB access stays in `crud.py` (no raw SQL in routes).

## 7. Bounds & ordering

- SKU consumption: **LIMIT 200**, deterministic `occurred_at DESC, id DESC`. (Honors the bounded/ordered-catalog rule; >100-row LIMIT pitfall noted in project memory.) The UI states when the list is capped.
- Serial movements: per-unit lifecycle is naturally small; keep existing chronological `occurred_at ASC, id ASC` order.

## 8. Frontend (`frontend/src/routes/_layout/search.tsx`)

- **SKU tab:** add a "Consumption" section beneath "Batches". Table columns: When · Type (labeled from `event_type`: Sale / Service / Project / Adjustment) · Qty · Customer/Project · By · (admin) COGS. Admin rows expand to a per-batch FIFO draw breakdown (`batch_no`, qty, unit cost, line total). Cost columns/expanders render only when the field is present in the payload (defensive double-guard atop the server redaction). Empty state: "No consumption yet."
- **Serial tab:** History table gains Location (from→to names), By (actor), and Reference (resolved sale/ticket/pull label).
- Regenerate SDK: `bun run generate-client`.
- Role: rely on payload shape (presence of cost fields) for rendering; no new auth wiring.

## 9. Testing (TDD — write first)

Backend (pytest, `backend/tests`):
1. SKU consumption returns consuming events newest-first, bounded at 200.
2. Multi-batch FIFO consumption → multiple `draws` summing to the event quantity; `total_cost_thb` = Σ draws.
3. Counterparty resolution per parent: sale→customer; pull→customer+project(code/name); ticket→customer; adjustment→reason in notes, null customer.
4. **Redaction lock (raw-HTTP):** staff response for a SKU with consumption contains **zero** cost keys (`unit_cost_thb`, `total_cost_thb`, `purchase_cost_thb`, `draws`); admin response contains them. Extends the existing FR-015 redaction sweep.
5. SERIALIZED SKU → `consumption == []`.
6. Serial enrichment: location/actor names resolved; project-pull movement carries `reference_kind=PROJECT_PULL` + label.

Frontend: render admin (cost + draws) vs staff (no cost) from fixture payloads. E2E (Playwright) optional smoke.

## 10. Rollout

No migration; deploy is code + regenerated SDK. Backward-compatible (serial keeps raw IDs; SKU result gains a field). Review must run `requesting-code-review` + `database-reviewer` + `security-reviewer` before PR into `dev`.
