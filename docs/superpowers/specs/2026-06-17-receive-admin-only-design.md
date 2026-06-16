# Design: Move "Receive" under Operations and make it admin-only

**Date:** 2026-06-17
**Status:** Approved (brainstorming)
**Author:** Wai Phyo Aung (with Claude)

## Summary

Move the **Receive** navigation item from the staff-visible *Inventory* group into
the admin **Operations** group, and enforce admin-only access across all three
layers (nav, route guard, backend) so the restriction is real rather than
cosmetic. No FIFO / receipt business logic changes — only the authorization
boundary moves.

## Motivation

Today "Receive" is intentionally staff + admin (warehouse intake, FR-005/006,
recorded decision D3). The product owner has decided receiving stock should be
an **admin-only** operation. A nav-only move would hide the link but leave staff
able to receive via URL or direct API call (security-by-obscurity), so the change
must go all the way down to the backend dependency.

## Current state (three layers)

| Layer | Location | Today |
|---|---|---|
| Nav | `frontend/src/components/Sidebar/AppSidebar.tsx:64` | `baseItems` → Inventory, visible to all roles |
| Route guard | `frontend/src/routes/_layout/receive.tsx:56` | `requireAuth()` — any authenticated user |
| Backend | `backend/app/api/routes/receipts.py:23,41` | `CurrentUser` — staff + admin |

The exact template for the target state already exists in-repo:
`stock-adjustment.tsx` (`requireAdmin()`) and `stock_adjustments.py` (`AdminUser`).

## Changes

### 1. Nav — `AppSidebar.tsx`
- Remove `{ icon: PackagePlus, title: "Receive", path: "/receive" }` from
  `baseItems` → Inventory (Inventory becomes Stock + Low stock).
- Add it to `adminItems` → Operations, next to *Adjust*.
- Rewrite the stale "staff + admin" comment to reflect admin-only intake.
- `PackagePlus` import is already present and stays used — no orphaned imports.

### 2. Route guard — `receive.tsx`
- `beforeLoad: () => requireAuth()` → `requireAdmin()`; update the import from
  `@/lib/route-guards`. Staff hitting `/receive` by URL are redirected to `/`.

### 3. Backend — `receipts.py`
- `receive_serialized` and `receive_quantity`: change `current_user: CurrentUser`
  → `admin: AdminUser`; `received_by_user_id=current_user.id` → `admin.id`;
  update the import to `AdminUser`. Staff now receive **403**.
- **Leave `read_unit_label` (`/serialized/{unit_id}/label.pdf`) untouched.** It is
  genuinely shared-team and the staff-visible **Stock** page reprints labels
  through it (`PrintLabelButton` on `stock.tsx`). Locking it would break staff
  label reprints.

## Tests to invert (regression safety net)

- `backend/tests/api/routes/test_receipts_quantity.py::test_staff_can_receive_quantity`
  → assert **403**.
- `backend/tests/api/routes/test_receipts_serialized.py::test_staff_can_receive_serialized`
  → assert **403**.
- `frontend/tests/receive.spec.ts`:
  - "staff can receive over the receipts API" → staff call now **rejects (403)**.
  - "staff can reach /receive" → staff now **redirected to `/`** (lands on `/`).

Admin/superuser happy-path tests (currently using `superuser_token_headers`)
remain green unchanged.

## Explicitly NOT touching

- FIFO / ledger / movement logic and `crud.receive_*` functions.
- The label-PDF reprint endpoint, the Stock page, and `PrintLabelButton`.
- OpenAPI request/response schemas — the dependency swap does not change the
  bearer-token security scheme, so **no SDK regeneration** is required.

## Tradeoff (accepted)

This reverses recorded decision D3 / FR-005/006 ("YGN warehouse *staff* do
intake"). Warehouse staff can no longer receive stock; only admins can. The
inverted tests lock the new behavior in.

## Verification

- `pytest tests/api/routes/test_receipts_*.py` — staff→403, admin→200.
- `bun run test` for `receive.spec.ts`.
- biome / ruff / mypy clean.
- Review stage includes `ecc:security-reviewer` (auth-boundary change).
