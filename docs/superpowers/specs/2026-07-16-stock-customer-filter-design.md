# FR-012 — Stock dashboard customer filter (UI only)

**Date:** 2026-07-16 · **Status:** approved (owner, 2026-07-16)

## Problem

FR-012 asks for stock-on-hand viewable "for which customer". The backend has
supported this end to end since the FR-012 backend pass — `GET
/dashboards/stock-on-hand?customer=<uuid>` filters rows to products that
customer has ever bought or had serviced (`crud._filter_rows_by_customer`) —
but the `/stock` page never grew the control. Accidental UI gap, tracked in
the Engineering Ledger.

## Design

One file: `frontend/src/routes/_layout/stock.tsx`, mirroring the existing
supplier filter exactly.

- `customerId` state alongside `supplierId`.
- Query: `queryKey: ["stock-on-hand", supplierId, customerId]` and
  `customer: customerId || undefined` in the `getStockOnHand` call (SDK
  already exposes the param — no regeneration needed).
- Second `EntityCombobox` beside the supplier one, fed by
  `useCustomerOptions` (existing hook), `placeholder="All customers"`,
  searchable, clearable, `ariaLabel="Customer filter"`.
- **Admin-only**, wrapped in the same `isAdmin` guard as the supplier filter
  (owner decision: consistency; FR-012 is an admin/reporting concern).
  `useCustomerOptions` is fetched with `{ enabled: isAdmin }` to match.

## Semantics note

Selecting a customer answers "which products has this customer ever bought or
had serviced, and what's on hand now?" — it does not mean stock located at or
reserved for the customer.

## Out of scope

- The PRD's "and at what cost" clause — contradicts staff cost-redaction
  rules; tracked separately as a PRD wording amendment.
- Non-admin visibility (revisit if counter staff ask for it).

## Verification

- Playwright spec: admin sees the filter, staff does not; picking a customer
  issues `?customer=<id>` and the list narrows.
- Backend behavior already covered by existing `test_customer_dashboard.py`.
