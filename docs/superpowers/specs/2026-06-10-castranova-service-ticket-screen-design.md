# CastraNova-POS — Service-Ticket Screen (`/tickets`) — Design

- **Date:** 2026-06-10
- **Status:** Approved design — ready for implementation planning
- **Scope:** A frontend-only screen at `/tickets` (staff + admin) for the maintenance flow: open a ticket → scan/add repair parts → close. Online-only, no cost shown. Continues Plan **Task 5.3** (per-flow inventory screens), following the Sale (Phase 3) and Receive (Phase 4) screens. **No backend changes.**
- **Backend already built:** Plan **Task 2.5** — `POST /service-tickets`, `GET /service-tickets/{id}`, `POST /service-tickets/{id}/parts`, `POST /service-tickets/{id}/close` (covered by pytest).
- **Authoritative sources:** `docs/superpowers/specs/2026-05-23-castranova-pos-system-design.md` (FR-008, Flow C); `docs/superpowers/specs/2026-06-07-castranova-5.3-frontend-screens-design.md` (screen patterns); plan `docs/plans/2026-06-04-castranova-pos-implementation.md` (Task 2.5, Task 5.3).

---

## 1. Problem / goal

CastraNova staff run maintenance jobs: open a service ticket for a customer, consume repair parts from YGN stock, then close the ticket (which FIFO-consumes the parts and writes the ledger). The backend implements this lifecycle; there is no UI for it yet. Build the screen, mirroring the existing scan-driven POS screens.

**Success criteria:** A logged-in staff or admin user can, from `/tickets`, pick a customer, describe the issue, scan repair parts into an editable list, and close the ticket — producing exactly one `service_ticket` with its `service_ticket_part` lines and the close-time FIFO ledger. No cost/COGS is ever displayed.

## 2. Constraints discovered in the code (these drive the design)

1. **No list endpoint.** Only open / read-one / add-part / close exist. A queue of open tickets is impossible without new backend work → **single-ticket workflow**, no list. (User-confirmed.)
2. **No remove-part or update-part endpoint**, and `crud.add_service_ticket_part` inserts a **new row per call** (no merge by SKU). Posting each scan immediately would make a mis-scan permanent → **parts accumulate in a local editable cart and flush at close.**
3. **`add_service_ticket_part` rejects non-QUANTITY products** (`400`). Scans resolve to `UNIT` (serialized) or `PART` (SKU/quantity) via `useScanLookup` → **only PART scans are valid; UNIT scans are rejected client-side.**
4. **`ServiceTicketPartPublic` exposes only `unit_price_thb`** (the repair price charged), no COGS. **"No cost shown" is satisfied by the schema**; both roles see identical data, so the screen needs no role-tiering. Display price comes from `ProductPublic.repair_price_thb` (a selling price — shown to both roles, exactly as Sale shows `retail_price_thb` to staff).
5. **`open` requires a client-generated `idempotency_key` (UUID)**; **`close` is idempotent** and returns `409` on insufficient stock, leaving the ticket open.

## 3. Decision

A **single-ticket, build-then-commit** screen, online-only, mirroring the Sale screen.

**Chosen approach (A) — build locally, commit once at close.** Customer/issue/notes and a parts cart are held in local state; parts are editable (qty change, remove) until commit. A single **"Close ticket"** action orchestrates the full server lifecycle in sequence:

```
const idempotencyKey = crypto.randomUUID()          // fresh per attempt
POST /service-tickets        { customer_id, issue, notes, idempotency_key }   → { id }
POST /service-tickets/{id}/parts  { sku, quantity }      // one call per distinct cart line
POST /service-tickets/{id}/close  { resolution }
```

This is the literal `open → add parts → close` lifecycle, atomic from the user's point of view. A **fresh `idempotency_key` per submit attempt** (matching Sale's `buildSaleRequest(..., crypto.randomUUID())`) guarantees a failed attempt never double-adds parts to the same ticket — a retry is always a brand-new ticket.

**Rejected (B) — persist on an explicit "Open" button, POST each scan immediately.** Rejected because (2) there is no remove/update-part endpoint, so a mis-scan would be permanently stuck, and repeat scans would create duplicate rows. Local-cart-then-flush gives full edit/remove with no extra backend surface.

**Rejected (C) — add a `GET /service-tickets` list + queue UI.** Out of scope (crosses back into backend); user chose the single-ticket workflow.

## 4. Components & data flow

### 4.1 Route — `frontend/src/routes/_layout/tickets.tsx`
`createFileRoute("/_layout/tickets")` with `beforeLoad: requireAuth` (staff + admin — same gate as Sale). `head` title `"Tickets - CastraNova POS"`. Component mirrors `sale.tsx` structure (two-pane desktop grid + sticky mobile footer).

State: `parts: TicketPartLine[]`, `customerId`, `issue`, `notes`, `resolution`, `ticketResult` (post-close summary), `scanRef`.

Data: `useQuery(["products"])` and `useQuery(["customers"])` (same keys/`staleTime` as Sale, so the cache is shared). From products build:
- `partLookup: Map<sku, {productId, modelName, repairPriceThb}>` filtered to `tracking_mode === "QUANTITY"`.

Scan wiring: `useScanLookup()` → on `result`, fold into the cart via `addScanToTicketParts`, then `reset()` (same effect pattern as Sale). UNIT / NOT_FOUND surface via the two static `aria-live` regions (assertive for errors, polite for "Searching…").

Submit: a plain online-only `useMutation` (NOT the persisted `["sales"]` queued key) whose `mutationFn` runs the three-step orchestration above. `onSuccess`: set `ticketResult`, clear form, success toast, refocus scan. `onError`: error toast (insufficient-stock 409 message surfaced).

`canClose = customerId !== "" && issue.trim() !== "" && !mutation.isPending` (parts optional — `close` tolerates zero parts).

### 4.2 Pure cart logic — `frontend/src/lib/ticket-parts.ts`
Pure, React-free (mirrors `sale-cart.ts`). `TicketPartLine = { key: sku, sku, productId, modelName, quantity, unitPriceThb }`.
- `addScanToTicketParts(lines, scan, partLookup): TicketPartLine[]` — `PART` → merge by SKU (increment qty) or append; `UNIT` / `NOT_FOUND` → return `lines` unchanged (the route shows the UNIT-rejection message; the cart simply ignores it).
- `setPartQuantity(lines, key, qty)` — floor at 1.
- `removePart(lines, key)`.
- `ticketPartsSubtotalThb(lines)` — display total (price, never cost).
- `buildTicketSubmission(lines, customerId, issue, notes, resolution, idempotencyKey)` — returns the shaped payloads for the open/parts/close calls (the orchestrator iterates them).

### 4.3 Renderer — `frontend/src/components/pos/TicketPartsList.tsx`
Thin presentational component over `TicketPartLine[]`: product name · qty stepper · unit repair price · remove button, plus the subtotal and the post-close summary. **No cost column, no `isAdmin` branch** (unlike Sale's `ScanCart`). Covered transitively by the `ticket-parts.ts` unit tests.

### 4.4 Navigation — `frontend/src/components/Sidebar/AppSidebar.tsx`
Add `{ icon: Wrench, title: "Tickets", path: "/tickets" }` to `mainItems` (the shared staff+admin list, alongside Sale and Receive). `Wrench` from `lucide-react`.

### 4.5 Auto-generated
`frontend/src/routeTree.gen.ts` regenerates from the new route file (never hand-edited). The SDK already contains `ServiceTicketsService` — **no `bun run generate-client` needed** (no backend change).

## 5. Error handling

| Case | Behavior |
|---|---|
| Scan resolves to UNIT (serialized) | Cart unchanged; assertive live region: *"Serialized units can't be added as repair parts."* |
| Scan NOT_FOUND | Assertive live region: *"No item found for that code."* |
| Scan lookup non-404 failure | *"Scan lookup failed. Try again."* (same as Sale) |
| `close` → 409 insufficient stock | Error toast with the backend detail; form preserved so the user can lower a quantity and resubmit (as a fresh ticket). |
| Any open/parts/close network error | Error toast; nothing cleared. |

## 6. Testing (TDD per the skill loop)

- **Pure unit tests — `frontend/tests/ticket-parts.spec.ts`** (run via `@playwright/test` as a pure-logic runner, mirroring `tests/sale-cart.spec.ts`): PART merge-by-SKU and append; UNIT and NOT_FOUND leave the cart unchanged; `setPartQuantity` floor-at-1; `removePart`; `ticketPartsSubtotalThb`; `buildTicketSubmission` payload shape (incl. a stable `idempotency_key` passed through, and one parts payload per distinct line). `TicketPartsList` is a thin renderer over these, so it is covered transitively.
- **Browser E2E** (ticket open → add → close in a real browser) is plan **Task 5.2, which is BLOCKED-BY 5.3** and explicitly deferred in the plan — **not built here.**
- **Gates:** `tsc` + `biome` clean; existing Playwright suite stays green.

## 7. Known limitation (accepted for MVP)

If `close` returns 409 after the ticket + parts were already persisted, that ticket is left **open and unreachable** (no list endpoint) — an invisible orphan. Eliminating it would require a delete/abandon endpoint (out of scope). The 409 surfaces as a toast; the user adjusts quantities and resubmits as a fresh ticket.

## 8. Out of scope

- Ticket list / queue / reopening a previously opened ticket (no backend list endpoint).
- Pricing overrides (FR-010) on ticket parts — parts use the default `repair_price_thb`; `pricing_override_request_id` is left `null`.
- Whole-unit machine-swap on a ticket — not exposed by `add_service_ticket_part` (SKU/quantity only).
- Offline queueing — tickets are online-only by decision.
- Any backend change (route, crud, model, migration, SDK regen).
