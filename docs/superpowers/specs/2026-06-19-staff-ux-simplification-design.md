# Staff UX Simplification — Design

**Date:** 2026-06-19
**Status:** Approved (design locked)
**Scope:** Frontend only. Display/UX changes to the staff-facing screens. No backend, database, API, or access-control changes.

## Problem

Staff (`YGN_STAFF`) are new to POS systems. The staff-facing screens expose internal vocabulary (FIFO, tracking mode, SERIALIZED/QUANTITY, batches, pull, fulfill, channel) and dense multi-column tables with nested drill-downs. This is cognitively heavy for non-technical employees.

The sidebar **already** restricts admin sections from staff (`AppSidebar.tsx`: `baseItems` shown to all, `adminItems` gated on `isAdmin`, `superuserItems` on `isSuperuser`). Access control is **not** in scope — verified working.

## Approach

**Reduce + reveal**, plus a plain-language pass on every staff screen:

- **Reduce** — the default view shows only the essentials, in plain language.
- **Reveal** — dense detail (full event/FIFO history, delivery/batch tables, extra columns) is moved behind a "Show details / Show history" toggle. Nothing is deleted; it's one tap away.
- **Plain words** — internal jargon is replaced with shop-floor language at the display layer only.

No wizards. No change to interaction models beyond the above.

### Non-goals

- No backend / DB / API renames — the database, models, and SDK keep their real names (`SERIALIZED`, `FIFO`, `tracking_mode`, `pull`, etc.).
- No change to stock logic, FIFO consumption, idempotency, or any inventory behavior. This is display-only.
- No access-control changes (already correct).
- No changes to admin-only screens.

## Section 1 — Plain-language glossary

Display labels only. Source enum/field values are unchanged.

| Staff sees now | → Plain word | Screens |
|---|---|---|
| `FIFO` / FIFO batches | Hidden by default; behind "Show details" reads "Oldest stock first" | Search, Stock |
| Tracking mode `SERIALIZED` | **Serial-tracked** (each piece has its own barcode) | Search, Stock, Low stock |
| Tracking mode `QUANTITY` | **Counted** (tracked by quantity) | Search, Stock, Low stock |
| Batch / Batch no | **Delivery** | Search, Stock |
| CastraNova barcode | **Shop barcode** | Search, Stock, Sale |
| Supplier serial | **Maker's serial no.** | Search, Stock |
| State (of a unit) | **Status** — In stock / Sold / In repair | Search, Stock |
| On hand | **In stock** | everywhere |
| Pull / Project pull | **Stock request** | Pulls, nav |
| Fulfill | **Give out parts** | Pulls |
| Line / line item | **Item** | Pulls, Tickets |
| Reorder threshold / Min level | **Reorder at** | Low stock |
| Resolution | **What was done** | Tickets |
| Channel (LINE/Viber) | **Send to** | Notifications |

### Implementation: shared label module

Today these labels are rendered inline per-screen (no central helper). Introduce one small module — `frontend/src/lib/labels.ts` — exporting pure functions that map source values to display strings, e.g.:

- `trackingModeLabel(mode)` → "Serial-tracked" | "Counted"
- `unitStatusLabel(state)` → "In stock" | "Sold" | "In repair" | …
- constants for shared field labels ("Shop barcode", "Maker's serial no.", "In stock", "Delivery", "Stock request", "Give out parts", "Reorder at", …)

Every screen imports from this module so wording stays consistent. Pure functions → unit-testable without React.

## Section 2 — Reduce + reveal (structural screens)

### 2a. Search (`routes/_layout/search.tsx`)

- Relabel tabs: "By unit" → **Find one item**, "By product" → **Find a product**.
- After a scan, render a clean **result card** in plain language:
  - Unit: product name, **Status** (In stock/Sold/In repair), Location, **Shop barcode**, **Maker's serial no.**
  - Product: product name, **Type** (Serial-tracked / Counted), **In stock: N**.
- Move the dense event table, FIFO draws, deliveries (batches) and consumption history behind a collapsed **"Show history" / "Show details"** toggle. Keep the existing tables as the revealed content.
- Simplify scan help text; keep accessibility (live regions) intact.

### 2b. Pulls (`routes/_layout/pulls.tsx`, `components/pos/PullQueue.tsx`, `PullCreatePanel`, `PullFulfillPanel`)

- Rename throughout (display): **Stock requests**; "Fulfill" → **Give out parts**.
- Default view = clean request list: cards showing project name, "N items needed", status chip ("🟡 Waiting"), one primary **Give out parts →** button.
- Status filter (PENDING/ALL) defaults to pending and is hidden behind a **"Show all / completed"** link.
- "Give out parts" flow:
  - Header shows which request (project name) + **Back to requests**.
  - **Progress indicator**: "Given out: 2 of 3 items" with a bar.
  - Item checklist (✅ done / ⬜ remaining, with `given / needed` counts).
  - Scan field with **friendly errors** (e.g. "That part isn't on this request — scan a different one." instead of "Scanned item isn't on this pull.").
  - Submit button: **Done — parts given out**.
- Create request stays admin-mostly (project picker already admin-only); reword only ("New stock request", "Notes for the warehouse").

### 2c. Stock (`routes/_layout/stock.tsx`)

- Slim the main table: collapse SKU + Model + tracking-mode badge into one **Product** cell — model name as the heading, `SKU · Serial-tracked|Counted` as quiet secondary text (no loud badge). Columns become: expand · Product · **In stock** (right-aligned) · print-label.
- Keep search, category filter, supplier filter (admin), and print-label action.
- The existing expand drill-down stays (already reveal-on-demand); reword its contents: **Shop barcode**, **Maker's serial no.**, **Status**; batches → **Deliveries**.

## Section 3 — Wording pass only (already-simple screens)

- **Sale** (`sale.tsx`): "CastraNova barcode" → "Shop barcode" in scan help text.
- **Tickets** (`tickets.tsx`): "Resolution (optional)" → "What was done (optional)"; align part wording with the glossary.
- **Low stock** (`low-stock.tsx`): "reorder threshold" / "Min level" → **Reorder at**; tracking-mode badge uses plain labels.
- **Notifications** (`notifications.tsx`): "Channel" → **Send to**.
- **Dashboard** (`index.tsx`): staff-facing cards already plain — no change. Admin-only cards (channel margin / COGS / append-only ledger) are not seen by staff, so left untouched.

## Components / units

- `lib/labels.ts` — new. Pure display-label functions + shared label constants. One purpose: map source vocabulary to staff-friendly words. Unit-tested.
- `search.tsx` — result-card + collapsible history. The card render can be a small local component; the revealed tables reuse existing markup.
- `pulls.tsx` + pull panels — request-list cards, give-out progress + checklist, friendly scan-error copy.
- `stock.tsx` — Product cell consolidation + reworded drill-down.
- Wording-pass screens — string changes + glossary imports only.

## Data flow

Unchanged. All screens keep their current TanStack Query data sources, scan hooks (`useScanLookup`), and mutations. The redesign only changes how already-fetched data is labelled and which parts are visible by default vs behind a toggle.

## Error handling

- Scan errors: keep existing not-found / error live regions; reword copy to be friendlier (esp. Pulls). No change to error semantics.
- Reveal toggles are presentation only — no new failure modes.

## Testing

This is display-only and **not** a high-risk (FIFO/ledger/consumption) change, so the mandatory FIFO concurrency test does not apply. Still run stages 3–5 of the workflow.

- **Unit:** `lib/labels.ts` pure functions (each mapping + fallback for unknown values).
- **E2E (Playwright):** existing staff-screen specs must stay green; update any assertion that matches old wording (e.g. "On hand", "Fulfill", "Resolution"). Add coverage for: Search result card + Show history toggle; Pulls give-out progress + friendly scan error; Stock slim table + expand wording.
- Verify the reveal toggles expose the previously-visible data (no information lost), and that revealed content stays accessible.

## Risks

- **Test churn:** several E2E specs likely assert old label text; expect to update them as part of each screen's task.
- **Hidden-by-default data:** ensure nothing staff currently rely on is removed — only relocated behind a clearly-labelled toggle. Audit each screen's current visible data against the new default view during build.
- **Consistency:** all wording must come from `lib/labels.ts` to avoid drift between screens.

## Build order (one task per screen)

1. `lib/labels.ts` + unit tests (foundation; everything else imports it).
2. Search (2a).
3. Pulls (2b) — largest.
4. Stock (2c).
5. Wording-pass screens (Section 3) — can be grouped.
