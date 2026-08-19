# Audit log: SKU + batch filters (FR-019)

**Date:** 2026-07-11
**Status:** Approved (pending spec review)

## Problem

FR-019 requires the audit log to be filterable "by user, date, event type, SKU, or
batch." The backend `GET /audit` endpoint (`audit.py:16-52`) supports user
(`actor_user_id`), date (`from_date`/`to_date`), event type, `product_id`, and
`unit_id` — but **no SKU filter** (only indirect via `product_id`) and **no batch
filter**. The frontend audit page (`audit.tsx`) exposes even less: only Event,
User, From, and To. This closes the SKU and batch gap, backend and frontend.

## Decisions (confirmed with user)

- **Scope:** backend + frontend UI for SKU and batch. The existing `product_id`/
  `unit_id` params stay backend-only (not wired into the UI) — the SKU filter
  covers the product case more usefully for the audit screen.
- **Batch identity:** `batch_no` (human string, e.g. `20260611-ABC123-001`),
  matching FR-019's "filter by batch" intent. Accepted caveat: `batch_no` is
  unique per product, not globally, so a duplicate across products would broaden
  the match. Near-impossible in practice (the SKU is embedded in `batch_no`).
- **SKU reach:** spans both ledgers — correct for SERIALIZED and QUANTITY products.
- **Batch input UX:** commits on Enter and blur (no query per keystroke).

## Non-goals

- No schema change → **no Alembic migration**.
- No new `AuditEntryPublic` field (batch_no is filtered on, not displayed in rows).
- Not wiring `product_id`/`unit_id` into the UI.

## Data model facts

- A SKU identifies exactly one `Product` (`Product.sku` is unique). A product is
  either SERIALIZED (movements in `unit_movement`) or QUANTITY (movements in
  `part_movement`) — never both. So a SKU's history lives in exactly one ledger.
- `UnitMovement` carries `unit_id` (no `product_id`); its product is reached via
  `Unit.product_id`.
- A batch is a `PartBatch` (`batch_no`, unique per `product_id`; globally-unique
  `id`). Batches are PART-only (serialized units aren't batched).
- A `PartBatch` links to movements two ways:
  - the RECEIVED movement that **created** it: `part_movement.part_batch_id`;
  - consumption movements that **drew from** it:
    `cost_line.part_batch_id → cost_line.part_movement_id`.

## Backend design

### `crud.list_audit` — two new params

Signature gains `sku: str | None = None`, `batch_no: str | None = None`.

1. **Resolve SKU → product id** (once, up front):
   ```python
   product_id_from_sku: uuid.UUID | None = None
   if sku is not None:
       product_id_from_sku = session.exec(
           select(Product.id).where(Product.sku == sku)
       ).first()
       if product_id_from_sku is None:
           return []  # unknown SKU matches nothing
   ```

2. **Ledger gating** (batch is PART-only, so it excludes the UNIT ledger):
   ```python
   audit_unit = product_id is None and batch_no is None
   audit_part = unit_id is None
   ```

3. **SKU on the UNIT ledger** (only when `sku` given) — reach the product's units
   via a sub-select:
   ```python
   u_stmt = u_stmt.where(
       col(UnitMovement.unit_id).in_(
           select(Unit.id).where(Unit.product_id == product_id_from_sku)
       )
   )
   ```

4. **SKU on the PART ledger** (only when `sku` given):
   ```python
   p_stmt = p_stmt.where(PartMovement.product_id == product_id_from_sku)
   ```

5. **batch_no on the PART ledger** (only when `batch_no` given) — direct link OR
   via cost lines:
   ```python
   batch_ids = select(PartBatch.id).where(PartBatch.batch_no == batch_no)
   p_stmt = p_stmt.where(
       or_(
           col(PartMovement.part_batch_id).in_(batch_ids),
           col(PartMovement.id).in_(
               select(CostLine.part_movement_id).where(
                   col(CostLine.part_batch_id).in_(batch_ids)
               )
           ),
       )
   )
   ```

Because a product is one tracking mode, exactly one of the SKU predicates yields
rows (the other ledger comes back empty), so applying both unconditionally when
`sku` is set is correct with no `tracking_mode` branch.

**Imports:** add `or_` to the `sqlalchemy` import in `crud.py`. `CostLine`,
`PartBatch`, `Product`, `Unit`, `UnitMovement`, `PartMovement` are already imported.

### `audit.py` route

Add two `Query` params and pass them through to `crud.list_audit`:

```python
sku: Annotated[
    str | None, Query(description="Restrict to a product's SKU (both ledgers)")
] = None,
batch_no: Annotated[
    str | None,
    Query(description="Restrict to PART entries that created or drew from a batch"),
] = None,
```

Update the docstring to mention the two new filters.

## Frontend design

### `lib/audit.ts`

- Extend `AuditFilter` with `sku: string` and `batchNo: string`.
- In `buildAuditQuery`, map non-blank values to `q.sku` and `q.batchNo`.

### `audit.tsx`

- **SKU `Select`** — options from the already-loaded `products` query (value =
  `product.sku`), plus an "All SKUs" option. Consistent with the existing User
  select. (A searchable combobox is a future enhancement if the SKU list grows
  large — out of scope here.)
- **Batch # text `Input`** — local input state committed to `filter` on Enter and
  on blur, so the query runs on submit rather than per keystroke.
- Both feed the existing `filter` state; `useQuery`'s `queryKey` already includes
  `filter`, so results refresh automatically.

### SDK regeneration

Run `bun run generate-client` after the backend change so `AuditListAuditData`
gains `sku` and `batchNo`. The `audit.tsx` / `lib/audit.ts` edits depend on the
regenerated types (never hand-edit `frontend/src/client/`).

## Testing

Backend (append to the audit test suite):

- SKU on a QUANTITY product → returns that product's PART rows only.
- SKU on a SERIALIZED product → returns that product's UNIT rows (proves the
  both-ledger reach).
- Unknown SKU → `[]`.
- `batch_no` → returns the RECEIVED row (direct link) **and** consumption rows that
  drew from the batch (via `cost_line`), excluding rows from other batches.
- `batch_no` → yields no UNIT rows (PART-only).

Frontend: covered by the existing Playwright audit flow plus a manual check that
the SKU select and batch input narrow the ledger.

## Risk

Low. Append-only ledgers are read-only here; no stock mutation, no money, no
schema change. The one nuance is the SKU/batch predicate correctness, covered by
the backend tests above.
