# Ledger Receipt Button — Design

**Date:** 2026-06-24
**Status:** Approved (brainstorming)
**Area:** Frontend (audit drawer) + Backend (sale receipt PDF)

## Problem

On the audit ledger (`/_layout/audit`), clicking a row opens a right-side drawer
(`AuditDetailSheet`) that shows only the *single* moved item — e.g. "Test ×10
UNITS", its source ("Sale → Walk In"), and who/when. A sale that bundles several
products (the client's example: a condensing unit sold together with 3 oil
separators) shows up as separate, unconnected ledger rows. There is no way to
see the whole sale from the ledger.

Client feedback: clicking a ledger entry should lead to the receipt for that
sale, so the user can see everything the customer bought together.

## Solution Overview

Add a **Receipt button** to the audit detail drawer. When the clicked entry came
from a sale, the button fetches the sale's receipt PDF (with auth) and opens it
in a new browser tab. The PDF is enriched so it actually shows the customer, the
selling staff, and human-readable line items — making it a usable receipt rather
than the raw-UUID/`UNIT`/`PART` placeholder it renders today.

This reuses the existing `GET /api/v1/sales/{sale_id}/receipt.pdf` endpoint and
the existing authed-PDF frontend helper. No new route, no new endpoint.

## Scope

- The Receipt button appears in `AuditDetailSheet` **only when `entry.sale_id`
  is present** (i.e. the movement was raised by a sale). Movements from service
  tickets, project pulls, stock adjustments, and receives have no sale and show
  no button.
- Out of scope: an in-app HTML receipt view, a dedicated `/sale/{id}` route, a
  JSON sale-detail endpoint, and receipts for non-sale movement sources.

## Backend Changes

The current receipt is not fit for purpose:

- `backend/app/services/receipt_pdf.py` — `render_sale_receipt` labels each line
  with `line.line_kind.value` (literally `"UNIT"` / `"PART"`), shows the raw sale
  UUID, and has no customer or staff.
- `backend/app/api/routes/sales.py` — `read_sale_receipt` passes only
  `(line_kind.value, quantity, unit_price_thb)` per line.

### Enriched receipt content

The endpoint resolves and the renderer displays:

1. **Header:** "CastraNova POS — Receipt", a shortened sale id, and the date
   (existing `sold_at`).
2. **Customer name** — resolve `sale.customer_id` → `Customer.name`; render
   "Walk In" when null.
3. **Sold by** — resolve `sale.created_by_user_id` → `User.full_name`, falling
   back to `User.email`.
4. **Line items** — for each `SaleLine`, a human-readable label:
   - PART line: product model name + SKU (resolve `product_id` → `Product`).
   - UNIT line: product model name + serial (resolve `unit_id` → `Unit` →
     `Product`; serial from the unit).
   - Plus `quantity × unit_price_thb` and a per-line total.
5. **Grand total** — existing `sale.total_thb`.

No cost/COGS data is added (receipt stays price + total only). Resolution of
customer, staff, products, and units follows existing `crud` lookup patterns;
batch the lookups rather than querying per line.

### API shape

Endpoint path, method, and auth (`get_current_user`, shared-team access) are
unchanged. Only the rendered PDF body changes, so the OpenAPI surface and the
generated SDK are unaffected — **no client regeneration required**.

## Frontend Changes

- `frontend/src/components/audit/AuditDetailSheet.tsx` — when
  `entry.sale_id` is set, render a Receipt button. On click it calls the
  existing `openAuthedPdf("/sales/{entry.sale_id}/receipt.pdf")` helper
  (`frontend/src/lib/print-pdf.ts`), which attaches the bearer token, opens the
  PDF in a new tab, and returns a result code.
- Mirror `frontend/src/components/PrintLabelButton.tsx` for UX: a disabled
  "Opening…" state while the PDF is in flight (prevents double-tab), and map the
  result codes to the same toasts (`no-token` → "Session expired…",
  `popup-blocked` → "Pop-up blocked…", `fetch-failed` → "Could not load
  receipt PDF.").
- Button placement: in the drawer's source/`SOURCE` area near the "Sale" badge,
  or as a primary action in the drawer footer — final placement decided during
  implementation to match the drawer's existing styling.

## Why a fetch instead of a plain link

`receipt.pdf` requires a JWT bearer token. A plain `window.open(url)` or anchor
would not carry the `Authorization` header and would 401. The `openAuthedPdf`
helper is the app's sanctioned pattern for authed binary PDFs (already used by
label printing) — fetch with token → blob → object URL → new tab.

## Testing

- **Backend (pytest):** a sale with a mix of UNIT and PART lines renders a PDF
  whose bytes contain the customer name, the selling staff name, and each
  product's model name (not `"UNIT"`/`"PART"`). A walk-in sale renders
  "Walk In". Unknown `sale_id` → 404 (existing behavior preserved).
- **Frontend (E2E, Playwright):** open the audit ledger, click a sale-sourced
  row, confirm the Receipt button is present and a non-sale row (e.g. a
  RECEIVED movement) shows no button. Clicking the button issues the authed
  PDF request. (Asserting on the opened tab's contents is out of scope for E2E;
  the PDF body is covered by the backend test.)

## Risk

Low. Touches the receipt renderer, one endpoint's line-assembly, and one drawer
component. The receipt PDF and sale-line handling are read-only here — no stock
movement, FIFO, or ledger-write code is touched, so this is not a high-risk
change under CLAUDE.md, though the backend review should still confirm the
batched lookups don't N+1.
