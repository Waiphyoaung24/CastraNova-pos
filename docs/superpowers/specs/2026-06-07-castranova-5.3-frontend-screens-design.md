# CastraNova-POS — Part 5.3: Frontend Screens, Role-Shells & Redaction — Design

- **Date:** 2026-06-07
- **Status:** Approved design — ready for implementation planning
- **Scope:** Full Part 5.3 (frontend SDK + screens + admin/staff role-shells + offline indicator/queue-counter), plus the targeted backend redaction slice required to satisfy the Definition of Done.
- **Plan reference:** `docs/plans/2026-06-04-castranova-pos-implementation.md` (Part 5; 5.3 now precedes 5.2).
- **Why now:** 5.2 (browser E2E) is `BLOCKED-BY 5.3`. Its headline acceptance — *offline queue survives reload; no dup on replay* — is a frontend PWA behaviour that can only be exercised through real inventory screens. This spec builds those screens so 5.2 can resume.

---

## 1. Goal & success criteria

Build the operational frontend for CastraNova-POS so that:

1. Staff and admins have real screens for the four inventory flows (Receive, Sale, Service-Ticket, Project-Pull).
2. **Staff cannot reach admin routes or see financial fields — verified by raw HTTP inspection, not DOM** (Definition of Done).
3. Offline sale/receive survive a browser reload and replay exactly once (idempotency), with a visible queue counter.
4. The existing E2E suite stays green and the five 5.2 Playwright paths become writable.

**Done when:**
- pytest proves staff `create_sale`/receipt JSON omits cost/COGS and `/receipts/*` 403s for staff.
- The four screens are reachable per the role matrix and function against the live backend.
- `bun run generate-client` regenerates cleanly; biome + tsc clean; `uv run ruff check . && uv run mypy app` clean.
- 5.2's five Playwright paths pass (handed off to 5.2 once screens exist).

**Out of scope (YAGNI):** offline replay for Ticket/Pull (only Sale + Receive are wired offline, matching the existing `query-client.ts`); reports/pricing-override/sync-review screens beyond what already exists; the two-step "staff stages, admin prices" receive flow (rejected — Receive is admin-only).

---

## 2. Decisions (locked during brainstorming)

| # | Decision | Rationale |
|---|---|---|
| D1 | **Full 5.3** scope: 4 screens + role-shells + offline counter | User selection |
| D2 | **Staff = ops screens, cost/COGS hidden**; admin = everything | Matches DoD "no financial fields for staff" |
| D3 | **Backend redaction included in 5.3** (not UI-only) | DoD requires redaction at the HTTP layer, not DOM |
| D4 | ~~**Receive = admin-only**~~ **SUPERSEDED 2026-06-09** | Receiving inherently enters `purchase_cost_thb`; staff must never see cost. **Superseded — staff receive per FR-005/006 (§8 receipts = staff); the redaction concern is sales COGS/margin, NOT the supplier purchase cost staff enter at receive. See `docs/superpowers/specs/2026-06-09-castranova-staff-receiving-design.md`.** |
| D5 | **Architecture A** — thin role-guarded routes over shared primitives | Matches existing patterns; best isolation/testability |
| D6 | **Responsive Sale** — two-pane desktop → single-column + sticky checkout on tablet | Staff use a mix of desktop + tablet |
| D7 | **Visual direction** — industrial-utilitarian, data-dense; Fira Code (codes/prices) + Fira Sans; cool-blue primary + orange CTA, dark-first | ui-ux-pro-max "Data-Dense Dashboard"; frontend-design anchor |

---

## 3. Role → route/access matrix

Roles: backend `UserRole = 'BKK_ADMIN' | 'YGN_STAFF'`, plus `is_superuser`. **Admin** = `is_superuser || role === 'BKK_ADMIN'`. **Staff** = `role === 'YGN_STAFF'`.

| Screen / route | Staff (YGN_STAFF) | Admin (BKK_ADMIN / superuser) |
|---|---|---|
| Receive (serial + qty) | ❌ hidden in nav + **403** | ✅ |
| Sale / POS | ✅ (cost/COGS redacted) | ✅ full |
| Service ticket (open/parts/close) | ✅ | ✅ |
| Pull — fulfill (+ read) | ✅ | ✅ |
| Pull — create / cancel | ❌ | ✅ |
| Admin (users), reports, pricing-overrides, sync-review | ❌ | ✅ |

Frontend `beforeLoad` guards mirror the existing `admin.tsx` pattern, but **the backend role guards are the real enforcement** — the UI guards only prevent staff from *seeing* routes.

---

## 4. Backend redaction slice

Audit result: the only staff-reachable endpoint that leaks cost is **Sale**. Tickets and pulls carry no cost fields; stock-on-hand and batch-drill deliberately exclude cost (see the `BatchDrillRow` comment); stock-adjustments and pull create/cancel are already admin-only.

### 4.1 Sale schema variants (`app/models.py`)

```text
SaleLineStaffPublic = SaleLinePublic minus `unit_cost_thb`
SaleStaffPublic     = SalePublic     minus `total_cogs_thb`; lines: list[SaleLineStaffPublic]
```
(Keep `unit_price_thb` / `total_thb` — selling price is staff-visible.)

### 4.2 Role dispatch (`app/api/routes/sales.py`)

Follow the established pattern in `customers.py` / `projects.py`: branch on `current_user.role == UserRole.BKK_ADMIN` (superuser treated as admin) to return the admin vs staff schema. Applies to `create_sale` and the `_to_public` helper used by the receipt JSON. Confirm the `receipt.pdf` route renders selling price only (no cost) — it is customer-facing; add a redaction assertion to the test regardless.

### 4.3 Receive → admin-only (`app/api/routes/receipts.py`)

> **Superseded 2026-06-09:** receiving is **staff + admin** (revert D4). Receipts routes authorize via `CurrentUser` (the label route via `get_current_user`), not `get_admin`. The redaction concern was sales COGS/margin, not the supplier purchase cost staff enter at receive. See `docs/superpowers/specs/2026-06-09-castranova-staff-receiving-design.md`.

~~Add `dependencies=[Depends(get_admin)]` to `/receipts/serialized`, `/receipts/quantity`, and the serialized label PDF route. (`get_admin` already exists and gates pull create/cancel + stock-adjustments.)~~

### 4.4 Cleanup

Update the stale comment at `project_pulls.py:81` ("staff role-tiering deferred to Part 4") — fulfill is intentionally staff-accessible per the matrix; the comment should say so.

### 4.5 SDK regen

After 4.1–4.3, run `bun run generate-client`. The union response surfaces `unit_cost_thb`/`total_cogs_thb` as optional in generated types; the frontend `useRole` rendering already treats cost as conditionally present.

---

## 5. Frontend architecture (Approach A)

One file-route per screen under `src/routes/_layout/`, each role-guarded in `beforeLoad`. Shared primitives written once and reused.

### 5.1 Shared primitives

- **`useRole()`** (`src/hooks/useRole.ts`) — wraps `useAuth()`; returns `{ isAdmin, isStaff, role }`. Drives sidebar filtering, route guards, and conditional cost rendering. Belt-and-suspenders with backend redaction.
- **`useScanLookup()`** (`src/hooks/useScanLookup.ts`) — composes the existing `useScanner` keyboard-wedge hook + `SearchService.searchSerial`/`searchSku`, with the existing `CameraScanFallback` for no-wedge devices. Returns `{ resolved unit/product | not-found, isSearching }`. Auto-focuses the scan field on mount; re-focuses after each commit.
- **`ScanCart`** (`src/components/pos/ScanCart.tsx`) — shared line-item builder for **Sale** and **Ticket**. Holds lines (kind, unit/product, qty, price), emits the SDK request payload. Cost columns rendered only when `useRole().isAdmin`.
- **Route guards** — two `beforeLoad` helpers: `requireAdmin` (Receive, Pull-create/cancel, admin screens) and `requireAuth` (Sale, Ticket, Pull-fulfill), mirroring `admin.tsx`.

### 5.2 Offline indicator + queue counter

Extend the existing `src/components/OfflineIndicator.tsx`:
- Read the TanStack Query mutation cache via `useMutationState({ filters: { predicate: (m) => m.state.isPaused } })` and show a badge: *"N queued"*. (Pattern confirmed against current TanStack Query docs via context7.)
- Replay-on-reconnect is **already wired** for Sale + Receive (`setMutationDefaults(["sales"|"receipts"])` + `PersistQueryClientProvider` + `resumePausedMutations()` in `src/lib/query-client.ts`). No new offline wiring; Ticket/Pull stay online-only by design.
- Announce online/offline transitions and queue changes via `aria-live="polite"`.

### 5.3 Data fetching

Per existing convention: `useSuspenseQuery` + generated SDK service methods; mutations via `useMutation` with the SDK. No bare axios. Query keys: `["sales"]`, `["receipts"]`, `["service-tickets"]`, `["project-pulls"]`, etc.

---

## 6. Screen specs

All screens: dark-first industrial-utilitarian theme; Fira Code for codes/serials/SKUs/prices/qty (tabular numerics), Fira Sans for labels; an always-present monospace scan bar with a live status dot is the recurring anchor. All forms use react-hook-form + zod via the shadcn `Form` primitive.

### 6.1 Sale / POS — `/_layout/sale` (staff + admin) — responsive

- **Desktop (≥ md):** two-pane — left = scan bar + `ScanCart` lines; right = customer select + subtotal/total + **orange "Complete sale"** CTA. Admins additionally see a COGS/margin row; staff see the redacted treatment (row absent).
- **Tablet/phone (< md):** single column, checkout pinned in a sticky footer.
- **Flow:** scan → `useScanLookup` resolves UNIT (serial) or PART (SKU) → line added → adjust qty → select customer (default Walk-in) → Complete sale → `SalesService.createSale` with a client-generated `idempotency_key`.
- **Offline:** createSale is offline-capable (mutation default); when offline the sale is queued, the queue counter increments, and it replays on reconnect (exactly once — backend `UNIQUE(idempotency_key)`).

### 6.2 Receive — `/_layout/receive` (admin only)

- Tabs: **Serialized** (per-piece serial entry, scan-assisted) and **Quantity** (batch qty). Both capture supplier + `purchase_cost_thb`.
- `ReceiptsService.receiveSerialized` / `receiveQuantity` with `idempotency_key`. Serialized receive offers the label PDF link.
- Offline-capable for receipts (mutation default already wired).

### 6.3 Service ticket — `/_layout/tickets` (staff + admin)

- Open ticket (customer + issue) → add part lines (scan SKU; price = `repair_price_thb`, no cost shown to anyone) → **close** (FIFO-consumes on the backend). Re-close is idempotent.
- `ServiceTicketsService.openServiceTicket` / `addServiceTicketPart` / `closeServiceTicket`. Online-only.

### 6.4 Project pull — `/_layout/pulls` (fulfill: staff + admin; create/cancel: admin)

- List pulls by state. Fulfill view = a **checklist against requested lines** (not free cart-building): per line, confirm/scan units or enter fulfilled qty.
- On partial fulfilment the line and pull settle **SHORT** with a visible badge.
- `ProjectPullsService.fulfillProjectPull`; create/cancel buttons render only for admins. Online-only.

### 6.5 Navigation & role-shell

Extend `src/components/Sidebar/AppSidebar.tsx` to build nav from `useRole()`:
- **Staff items:** Dashboard, Sale, Tickets, Pulls.
- **Admin items:** the above + Receive, Admin (users), and existing admin areas.
Icons from lucide (no emoji). Active-route highlight.

---

## 7. Accessibility (frontend-a11y)

- Every input has a connected `<label htmlFor>`; errors linked via `aria-describedby` + `role="alert"` (shadcn `Form` provides this — use it, don't hand-roll).
- Scan bar auto-focuses and re-focuses after each scan; scan results, cart changes, and offline/queue transitions announced via `aria-live` regions (`polite`; `assertive` only for scan-not-found errors).
- All interactive elements are real `<button>`/`<a>` (no `div onClick`); icon-only buttons have `aria-label`.
- Touch targets ≥ 44×44px; visible focus rings; color is never the only signal (SHORT/queued states carry text + icon).
- `prefers-reduced-motion` respected (reuse a `useReducedMotion` helper for any transitions).
- Contrast ≥ 4.5:1 in the chosen palette (verify the dark theme tokens).

---

## 8. Visual / theme

- Add Fira Code + Fira Sans (self-hosted or Google Fonts) and wire into the Tailwind v4 theme tokens; `--font-mono: "Fira Code"`, `--font-sans: "Fira Sans"`. Apply mono to a `.num`/tabular utility used on all codes/prices.
- Tune the existing shadcn theme tokens toward the data-dense dark palette (primary `#3B82F6`, CTA `#F97316`, success/warn/bad). This is a deliberate visual upgrade layered on existing shadcn primitives — **global theme tokens change**, but component APIs stay shadcn-standard. Keep light mode functional (the template supports `next-themes`).

---

## 9. Testing strategy

- **Backend (pytest, test-first):** staff token → `create_sale` and receipt JSON omit `unit_cost_thb`/`total_cogs_thb`; admin token → present. Staff token → `/receipts/serialized|quantity|label` → 403. Reuse the existing `staff_token_headers` / `superuser_token_headers` fixtures.
- **Frontend:** component tests for `useRole` gating and `ScanCart` payload assembly where they earn their keep.
- **E2E (handed to 5.2 once screens exist):** the five paths — receive (admin), sale online, **sale offline→reload→replay**, ticket close, pull fulfill (short) — plus a role test: staff redirected from `/receive`, cost absent in DOM *and* raw HTTP. The login rate-limit is already disabled for E2E via `RATE_LIMIT_ENABLED=false` (compose.override.yml).

---

## 10. Build order (one reviewable PR per phase)

| Phase | Deliverable | Review gates |
|---|---|---|
| 1 | Backend redaction slice (§4) + pytest + SDK regen | **`ecc:database-reviewer` + `ecc:security-reviewer`** (money/redaction = high-risk) + `requesting-code-review` |
| 2 | Design foundation (§5.1, §5.2, §8): fonts + theme tokens, `useRole`, route guards, `useScanLookup`, OfflineIndicator + queue counter | `requesting-code-review` |
| 3 | Sale/POS screen (§6.1) — unblocks 5.2 sale online + offline replay | `ecc:react-reviewer` + `requesting-code-review` |
| 4 | Receive screen (§6.2) — unblocks 5.2 receive | `ecc:react-reviewer` |
| 5 | Service-ticket screen (§6.3) — unblocks 5.2 ticket close | `ecc:react-reviewer` |
| 6 | Project-pull screen (§6.4) — unblocks 5.2 pull fulfill (short) | `ecc:react-reviewer` |
| 7 | Role-shell polish (§6.5) + final role/redaction E2E; mark 5.2 done in the plan | `requesting-code-review` + `ecc:security-reviewer` |

Each phase follows the CLAUDE.md §5 loop (TDD inside each build task). Phase 1 is independently shippable and closes the Sale half of the parked `deferred-security-hardening` staff-redaction item.

---

## 11. Risks & open questions

- **Theme change blast radius:** retuning global tokens + adding fonts affects every existing screen (login, admin, settings). Mitigation: verify the existing E2E suite stays green after Phase 2; keep light mode working.
- **SDK union typing:** confirm `@hey-api/openapi-ts` emits a usable union for the role-dispatched response; if awkward, fall back to making cost fields `Optional` on a single Public schema (still backend-redacted) rather than two schemas. Decide during Phase 1.
- **`receipt.pdf` cost check:** confirm the PDF template carries no cost (expected customer-facing); covered by a Phase 1 test.
- **Pull fulfill UNIT scanning UX:** the checklist-vs-scan interaction for serialized pull lines needs a concrete interaction spec at Phase 6 (resolve then, not now).
