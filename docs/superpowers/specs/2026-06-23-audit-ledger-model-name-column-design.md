# Audit ledger — Model name column

**Date:** 2026-06-23
**Scope:** Frontend-only. One column change in the admin audit ledger.

## Goal

Show the human-readable product **model name** in the audit ledger instead of the
raw SKU / unit reference.

## Background

`AuditEntryPublic.product_model_name` is already hydrated by the backend
(`crud._hydrate_audit`) for **both** PART and UNIT rows:

- PART rows resolve the product directly via `product_id`.
- UNIT rows resolve the product via the unit's `product_id`.

So the data is already present in the API response — no backend, migration, or
SDK regeneration is required.

## Change

File: `frontend/src/routes/_layout/audit.tsx`

- Rename the **Item** column header → **Model name** in:
  - the desktop `<Table>` header, and
  - the `Item` `<dt>` in the mobile card.
- Render `e.product_model_name` in that cell, falling back to the existing
  `itemRef(e)` when the model name is missing (deleted/unhydrated product), so a
  row is never blank.
- Keep `itemRef` and the `products` / `skuById` lookup — still used for the row
  `aria-label` and as the fallback. Nothing is orphaned.

## Decision

Per-unit identifier (`Unit ·xxxxxxxx`) is intentionally dropped from the table;
it remains available in the per-row detail drawer (`AuditDetailSheet`). Confirmed
acceptable for a ledger overview.

## Verification

- Run the app, open `/audit`.
- Confirm a SOLD (part) and a RECEIVED row both show the model name.
- Check the mobile card layout shows the model name under "Model name".
- Existing audit tests / E2E still pass.
