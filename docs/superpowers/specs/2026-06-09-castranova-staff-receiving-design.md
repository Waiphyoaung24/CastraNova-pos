# CastraNova-POS — Restore Staff Receiving (revert Part 5.3 D4) — Design

- **Date:** 2026-06-09
- **Status:** Approved design — ready for implementation planning
- **Scope:** Make the Receive screen + `/receipts/*` API accessible to `YGN_STAFF` (not admin-only), correcting a role-model error introduced in Part 5.3. No new features; a targeted reversal + test/doc realignment.
- **Supersedes:** Part 5.3 design decision **D4** ("Receive = admin-only"). See `docs/superpowers/specs/2026-06-07-castranova-5.3-frontend-screens-design.md` §2 D4 / §4.3.
- **Authoritative source:** `docs/superpowers/specs/2026-05-23-castranova-pos-system-design.md` (§8 lines 545–546; Flow A, FR-005/FR-006).

---

## 1. Problem

Part 5.3 (Phase 1 backend + Phase 4 frontend) gated receiving to admin only:

- `backend/app/api/routes/receipts.py` — `dependencies=[Depends(get_admin)]` on `POST /receipts/serialized`, `POST /receipts/quantity`, and the unit-label PDF route.
- `frontend/src/routes/_layout/receive.tsx` — `beforeLoad: requireAdmin`.
- `frontend/src/components/Sidebar/AppSidebar.tsx` — Receive nav under admin-only items.

This **contradicts the foundational system design**, which makes receiving a YGN-warehouse **staff** operation:

- §8 API table (lines 545–546): `POST /receipts/serialized` → role **staff**; `POST /receipts/quantity` → role **staff** (FR-005, FR-006).
- Flow A (line 238): *"Staff opens 'Receive Parts'… enters… purchase cost."*

## 2. Root cause

Part 5.3 D4 conflated two distinct things:

1. **Staff entering the supplier purchase cost** at receive time — *intended* (staff physically handle the delivery and read the cost off the supplier invoice).
2. **Staff seeing the company's derived financials** — COGS/margin on sales, cost on stock/batch lookups, project budget/consumed_cost — which **is** redacted (S7 / §6.5: `TransactionSummaryStaffPublic` = "no cost/margin"; `ProjectStaffPublic` = "no budget/consumed_cost").

The redaction rule targets (2), never (1). Restoring staff receiving is fully consistent with cost-redaction.

## 3. Decision

Receiving is accessible to **staff and admin**. Staff enter the supplier `purchase_cost_thb` (per Flow A). Sales COGS/margin, stock/batch-drill cost, and project budgets stay redacted/admin-only — unchanged.

**Chosen approach (A):** drop the admin gate on the receipts routes; let the receive *response* echo back the cost the staff just entered (`UnitPublic.purchase_cost_thb`, `PartBatchPublic.purchase_cost_thb`). The echo is the user's own input, not a leak.

**Rejected (B):** add staff-redacted receipt-response schemas that strip cost from the echo — redundant (staff typed the value milliseconds earlier) and adds schema surface for no security gain.

## 4. Change set (one corrective PR off `dev`)

| Layer | File | Change |
|---|---|---|
| Backend | `app/api/routes/receipts.py` | Remove `dependencies=[Depends(get_admin)]` from `/receipts/serialized`, `/receipts/quantity`, and the label PDF route → authorize via `CurrentUser` (staff **and** admin). Keep `received_by_user_id = current_user.id`. Drop the now-unused `get_admin` import if nothing else in the file uses it. |
| Backend tests | `tests/api/routes/test_receipts_serialized.py`, `test_receipts_quantity.py` | Flip the three assertions: `test_staff_cannot_receive_serialized` / `_quantity` / `_fetch_unit_label` → **`test_staff_can_receive_*`** (expect success, not 403). Add/keep an unauthenticated → 401 check on at least one route. |
| Frontend | `src/routes/_layout/receive.tsx` | `beforeLoad: requireAdmin` → `requireAuth`. (Cost is shown on this screen to whoever receives — intended; no in-screen role-gating.) |
| Frontend | `src/components/Sidebar/AppSidebar.tsx` | Move **Receive** from `adminItems` to `baseItems` (staff + admin). **Admin** stays in `adminItems`. |
| E2E | `frontend/tests/receive.spec.ts` | Flip the two role tests: "staff is forbidden from the receipts API (403)" → **"staff can receive (serialized + quantity)"** (assert success); "staff route redirect" → **"staff reaches /receive"** (no redirect, heading visible). Admin paths unchanged. |
| Docs | this file + Part 5.3 design | Record the D4 reversal (this doc supersedes D4). Add a one-line pointer in the Part 5.3 design noting D4 is superseded. |

## 5. What is explicitly NOT changing (verified blast radius)

- **`get_admin` is untouched.** The other 10 routers using it (`audit, customers, low_stock, pricing_overrides, products, project_pulls, projects, reports, suppliers, sync_review`) keep their admin gates. Stock adjustments, pull create/cancel, admin reports, pricing decisions, etc. remain admin-only.
- **No SDK schema change.** Request/response models are identical; only an endpoint's auth dependency changes. (`bun run generate-client` is optional — it would only refresh OpenAPI security metadata, which the typed client does not encode.)
- **Redaction stays intact and independent.** `SaleStaffPublic` omits COGS (Phase 1); `SerialSearchResult` and `SkuBatchPublic` exclude cost; stock-on-hand excludes cost; project budget/consumed_cost stay admin-only. Staff see cost **only** where they enter it (receive form) and in its immediate echo.
- **The unit-label PDF is safe.** `render_unit_label` draws only the Code128 barcode + supplier serial — no cost/margin/price.
- **Downstream is role-agnostic.** FIFO consumption, the sale cost snapshot, margin reports, and stock-on-hand read the cost/batch data a receive produces; that data is identical regardless of the receiver's role (`received_by_user_id` is audit-only).

## 6. Testing strategy

- **Backend (pytest):** flipped tests prove staff **can** `POST /receipts/serialized` and `/quantity` and **can** fetch the unit label (success, not 403); an unauthenticated call still 401s. Existing admin receive tests stay green. Full `uv run pytest` green; `ruff` + `mypy app` clean.
- **Frontend E2E (Playwright, `--workers=1`):** flipped role tests — a `YGN_STAFF` browser reaches `/receive` (no redirect) and a staff token receives serialized + quantity over the SDK (success). Admin receive paths unchanged. Full suite green (requires the running dev backend to be current — rebuild with `docker compose up -d --build backend` if stale).
- **Manual:** log in as `staff@example.com` → Receive appears in the nav, `/receive` loads, a staff serialized + quantity receive succeeds; sales COGS/margin still absent for staff.

## 7. Definition of Done

- `/receipts/serialized`, `/receipts/quantity`, and the label route accept a `YGN_STAFF` token (success); unauthenticated → 401.
- Receive screen reachable by staff (nav + route); admin still reaches it.
- Backend `pytest` + frontend Playwright suites green; `ruff` + `mypy` + `biome` + `tsc` clean.
- Sales COGS/margin, stock/batch cost, and project budgets remain redacted from staff (no regression).
- Part 5.3 D4 recorded as superseded.
