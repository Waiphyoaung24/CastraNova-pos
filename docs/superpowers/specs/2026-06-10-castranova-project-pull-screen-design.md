# CastraNova-POS — Project-Pull Screen (`/pulls`) — Design

- **Date:** 2026-06-10
- **Status:** Approved design — ready for implementation planning
- **Scope:** A frontend-only `/pulls` screen (staff + admin) covering all of FR-009 (Flow D): a pull **queue**, staff/admin **fulfill** (scan-assisted), and admin-only **create** + **cancel**. Online-only, no cost shown. The 4th and final Part 5.3 inventory screen. **No backend changes.**
- **Backend already built:** Plan **Task 2.6** — `POST /project-pulls` (admin), `GET /project-pulls?state=` (staff+admin), `GET /{id}`, `POST /{id}/fulfill` (staff+admin), `POST /{id}/cancel` (admin); covered by pytest. SDK has `ProjectPullsService` + `ProjectsService`.
- **Authoritative sources:** `docs/superpowers/specs/2026-05-23-castranova-pos-system-design.md` (Flow D §lines 260–276; state machine §4.5; API table §8 lines 550–553; FR-009); `docs/superpowers/specs/2026-06-07-castranova-5.3-frontend-screens-design.md` (role matrix §3, Architecture A §D5, online-only Ticket/Pull §"out of scope"); the Sale/Ticket screens as pattern (`frontend/src/routes/_layout/{sale,tickets}.tsx`).

---

## 1. Problem / goal

Bangkok admins initiate project consumption by creating Project Pulls; YGN warehouse staff fulfill them at the barcode terminal (system design §lines 21, 260–276). The backend implements the full lifecycle and state machine; there is no UI yet. This is the last of the four Part 5.3 inventory screens (Receive, Sale, Service-Ticket, Project-Pull); shipping it unblocks the browser E2E (Task 5.2).

**Success criteria:** A logged-in user can open `/pulls`, see the pull queue filtered by state, and (staff or admin) **fulfill** a pull by scanning its lines — producing the correct `FULFILLED`/`SHORT` settlement with the backend FIFO/ledger writes. An **admin** can additionally **create** a pull (project + scanned request lines) and **cancel** a PENDING/SHORT pull. No cost/COGS is ever displayed.

## 2. Constraints discovered in the code (these drive the design)

1. **Fulfill is a single submission, not per-scan.** `ProjectPullFulfill = { lines: [{ line_id: UUID, fulfilled_qty: int(ge=0) }] }`. The server FIFO-consumes and sets each `line_state` + the pull `state` in one transaction. → the fulfill view holds a local draft map `line_id → fulfilled_qty`, scan-filled, then submitted once.
2. **No remove/edit-line endpoints after create**; create takes the whole pull at once: `ProjectPullCreate = { project_id, admin_notes?, lines: [ProjectPullLineCreate] (1..200) }`, where `ProjectPullLineCreate = { line_kind: "UNIT"|"PART", product_id, unit_serial?(UNIT), requested_qty?(PART, gt=0) }`. → create accumulates a local editable cart and POSTs once (like the ticket/sale carts).
3. **Public schemas carry no cost** (`ProjectPullPublic`, `ProjectPullLinePublic`): line exposes `line_kind, product_id, unit_serial, requested_qty, fulfilled_qty, line_state`; pull exposes `state, project_id, customer_id, admin_notes, created_by_user_id, created_at, fulfilled_at?, fulfilled_by_user_id?, cancelled_at?, cancelled_by_user_id?, lines`. "No cost shown" holds by construction; **staff and admin see identical data** (no schema variants, no redaction) — the only role difference is *capabilities* (create/cancel), not data.
4. **Role gating already enforced server-side:** create + cancel depend on `get_admin`; fulfill + read depend on `get_current_user` (staff + admin). Per 5.3 D5, the frontend route is `requireAuth` and the create/cancel **UI** is gated by `useRole().isAdmin` (cosmetic — backend is the real gate).
5. **Enums:** `ProjectPullState`/`LineState` = `PENDING | FULFILLED | SHORT | CANCELLED`; `SaleLineKind` = `UNIT | PART`. `ProjectPublic` exposes `code, name, customer_id, id` (for the queue label + create picker); `CustomerPublic` supplies the customer name.
6. **No idempotency_key on `project_pull`** (system design §461) — irrelevant here because the screen is online-only (no offline replay).

## 3. Decisions

**A. One `/pulls` route, three composed views, online-only.** The route (`requireAuth`) holds view state (`mode: "queue" | "create"`, `selectedPullId`) and orchestrates queries + the three mutations. **When a pull is selected for fulfill, the route seeds the fulfill draft to `{ <every line.id>: 0 }`** (see §3.C — required so unscanned lines settle as SHORT, not full). Three focused presentational components (Queue / FulfillPanel / CreatePanel) keep each unit small and independently testable (Architecture A, 5.3 D5). **Rejected:** a separate `requireAdmin` `/pulls/new` route — TanStack flat-route escaping adds complexity for no real security gain (backend `get_admin` already enforces create).

**B. Online-only** (user-confirmed; matches 5.3's YAGNI scope and the 5.2 E2E which only needs *online* fulfill-with-short). Plain `useQuery`/`useMutation`; no `setMutationDefaults`/IndexedDB for pulls. **Rejected:** the system design's offline-capable fulfill + offline-cached queue — deferred as out of scope for this screen.

**C. Fulfill via scan-assisted draft, defaulting to 0/unscanned — and send an explicit qty for every line.** Each line starts unsettled (0) so SHORT is a deliberate outcome of not-all-scanned, matching the warehouse scan flow (system design D.2). **This is not just a UX preference — it is required for correctness:** `crud.fulfill_project_pull` defaults a line **omitted** from the payload to its **full** requested amount (UNIT→1, PART→`requested_qty`), not to 0. So the fulfill draft is **seeded with every line at 0** when a pull is opened, and `buildFulfillPayload` emits an explicit `{ line_id, fulfilled_qty }` for **every** line; an unscanned line is therefore sent as `0` → SHORT, never silently full-fulfilled. A live projected-state badge previews FULFILLED vs SHORT. **Rejected:** sending only the touched lines — omission means full-fulfill server-side, the opposite of the intended behavior.

## 4. Components & data flow

### 4.1 Route — `frontend/src/routes/_layout/pulls.tsx`
`createFileRoute("/_layout/pulls")`, `beforeLoad: requireAuth`, head title `"Pulls - CastraNova POS"`. State: `mode`, `selectedPullId`, plus the fulfill draft / create cart lifted into the panels (see below). Queries:
- `["project-pulls", stateFilter]` → `ProjectPullsService.readProjectPulls({ state })`, `refetchInterval: 30_000`, `refetchOnWindowFocus: true` (system design D.1 freshness).
- `["projects"]`, `["customers"]`, `["products"]` → respective services, `staleTime: 5*60*1000` (shared with other screens). Used to build: `projectLookup` (id → {name, code}), `customerLookup` (id → name) for queue/labels, and `productLookup` (sku → {productId, modelName}) for the create cart + fulfill scan matching.

Three online-only `useMutation`s, each invalidating `["project-pulls"]` on success + a toast:
- **fulfill:** `fulfillProjectPull({ pullId, requestBody })` → on success return to queue.
- **create:** `createProjectPull({ requestBody })` → on success return to queue.
- **cancel:** `cancelProjectPull({ pullId })` → stays in queue.

### 4.2 Pure logic — `frontend/src/lib/pull-fulfill.ts`
React-free, unit-tested.
- `type FulfillDraft = Record<string, number>` (line_id → fulfilled_qty). Invariant: **the draft always contains an entry for every line on the pull** (seeded to 0 by the route on selection).
- `seedFulfillDraft(lines): FulfillDraft` — `{ <line.id>: 0 }` for every line. Used by the route when a pull is opened.
- `lineCap(line: ProjectPullLinePublic): number` — `1` for UNIT, `requested_qty ?? 0` for PART.
- `applyScanToFulfill(draft, lines, scan: ScanLookupResult): FulfillDraft` — `UNIT` scan → find the line whose `unit_serial === scan.data.castranova_barcode`; set its qty to `1`. `PART` scan → find the PART line whose `product_id === scan.data.product_id`; increment its qty, clamped to `lineCap`. No matching line, or `NOT_FOUND` → return `draft` unchanged (route shows the notice). Returns a new object on change.
- `setLineFulfilledQty(draft, line, qty): FulfillDraft` — clamp to `[0, lineCap(line)]`, floor.
- `buildFulfillPayload(draft): ProjectPullFulfill` — `{ lines: Object.entries(draft).map(([line_id, fulfilled_qty]) => ({ line_id, fulfilled_qty })) }`. Because the draft holds **every** line, every line is sent explicitly — un-scanned lines as `0` (→ SHORT). This is mandatory: an omitted line is full-filled server-side (see §3.C).
- `projectedPullState(lines, draft): "FULFILLED" | "SHORT"` — `FULFILLED` iff every line's drafted qty `>= lineCap(line)`, else `SHORT`.

### 4.3 Pure logic — `frontend/src/lib/pull-create.ts`
React-free, unit-tested. `type CreateLine = { key, lineKind: "UNIT"|"PART", productId, sku, modelName, unitSerial?, requestedQty }`.
- `addScanToCreateCart(lines, scan, productLookup): CreateLine[]` — `UNIT` scan → append a UNIT line keyed by `castranova_barcode` (`requestedQty = 1`, `unitSerial = barcode`), dedup by key (re-scan = no-op); `PART` scan whose sku is in `productLookup` → merge by sku (increment `requestedQty`) or append; `NOT_FOUND` / sku absent → unchanged (same reference).
- `setCreateQty(lines, key, qty)` — PART only, floor at 1; UNIT left at 1.
- `removeCreateLine(lines, key)`.
- `buildCreatePayload(lines, projectId, adminNotes): ProjectPullCreate` — UNIT → `{ line_kind:"UNIT", product_id, unit_serial }`; PART → `{ line_kind:"PART", product_id, requested_qty }`; blank notes → null.

### 4.4 Presentational components (`frontend/src/components/pos/`)
- **`PullQueue.tsx`** — props: `pulls`, `projectLookup`, `customerLookup`, `stateFilter`, `isAdmin`, `onStateFilterChange`, `onSelect`, `onCancel`, `onNew`. A state-filter `Select` (default `PENDING`; options PENDING/FULFILLED/SHORT/CANCELLED/ALL), a list/table of rows (project `name` (`code`) · customer name · created date · state badge · line count), an **admin** "New pull" button, and an **admin** "Cancel" action shown only on rows with `state ∈ {PENDING, SHORT}`.
- **`PullFulfillPanel.tsx`** — props: `pull`, `productLookup`, `draft`, `onScan`, `onQtyChange`, `onSubmit`, `onBack`, scan-status flags, `isPending`. Header (project/customer), `ScanInput` + `CameraScanFallback` + two `aria-live` regions (assertive: scan error / not-found / "isn't on this pull"; polite: "Searching…") mirroring Sale/Ticket. Line list: UNIT rows show `unit_serial` + a settled indicator (qty 0/1, editable via a confirm control); PART rows show `requested_qty` + a number input (0..requested). A projected-state badge (`projectedPullState`). "Fulfill pull" button; `canFulfill = pull.state === "PENDING" && !isPending`.
- **`PullCreatePanel.tsx`** — props: `projects`, `lines`, `projectId`, `adminNotes`, `productLookup`, scan wiring, `onScan/onQtyChange/onRemove/onSubmit/onBack`, `isPending`. Project `Select` (existing projects, label `name (code)`), optional admin-notes `Input`, `ScanInput` + `CameraScanFallback` + live regions, the create cart (UNIT: serial; PART: qty stepper + remove), "Create pull" button; `canCreate = projectId !== "" && lines.length > 0 && !isPending`.

### 4.5 Navigation — `frontend/src/components/Sidebar/AppSidebar.tsx`
Add `{ icon: ClipboardList, title: "Pulls", path: "/pulls" }` to `baseItems` (shared staff+admin list). `ClipboardList` from `lucide-react`.

### 4.6 Auto-generated
`routeTree.gen.ts` regenerates from the new route (via the `@tanstack/router-plugin`, never hand-edited). SDK already has `ProjectPullsService`/`ProjectsService` — **no `bun run generate-client`** (no backend change).

## 5. Scan handling summary

| Context | Scan kind | Action |
|---|---|---|
| Fulfill | UNIT | match line by `unit_serial`; set fulfilled_qty=1 |
| Fulfill | PART | match PART line by `product_id`; increment to cap |
| Fulfill | no line match / NOT_FOUND | live notice "Scanned item isn't on this pull." / "No item found." |
| Create | UNIT | append UNIT line (serial = barcode), dedup |
| Create | PART | merge PART line by sku, increment requested_qty |
| Create | NOT_FOUND / sku not in catalog | unchanged + notice |

## 6. Error handling

| Case | Behavior |
|---|---|
| fulfill 409 (state-machine / first-write-wins unit race) | error toast with backend detail ("already pulled/sold"); draft preserved |
| create 422 (no project / empty / bad line) | prevented by `canCreate` guard; any server error → toast |
| cancel error / not cancellable | Cancel only shown for PENDING/SHORT; server error → toast |
| scan not on pull / not in catalog | assertive live-region notice; no state change |
| any network error | error toast; no optimistic clearing |

## 7. Testing (TDD per the skill loop)

- **Pure unit tests** — `frontend/tests/pull-fulfill.spec.ts` and `frontend/tests/pull-create.spec.ts` (via `@playwright/test` as a pure-logic runner, mirroring `tests/ticket-parts.spec.ts`). Cover: UNIT/PART scan matching + clamps; no-match/NOT_FOUND no-ops (same reference where applicable); `projectedPullState` FULFILLED vs SHORT; `buildFulfillPayload`/`buildCreatePayload` shapes; create-cart merge/dedup/qty/remove. The three components are thin renderers over these + props, covered transitively.
- **Browser E2E** — the "pull fulfill (with short)" path is plan **Task 5.2**; this screen **unblocks** it but 5.2 is built separately.
- **Gates:** `tsc -p tsconfig.build.json --noEmit` clean; `biome check` clean; existing Playwright suite stays green.

**Resolved backend-behavior fact (confirmed in `crud.fulfill_project_pull`):** an omitted line is **full-filled** (`qty_by_line.get(line.id, requested_qty)` for PART, `…, 1)` for UNIT), NOT defaulted to 0. Therefore the fulfill draft is seeded with every line at 0 (`seedFulfillDraft`) and `buildFulfillPayload` emits an explicit entry for every line — the unit test must assert that an all-zero draft for a 2-line pull produces a 2-element payload of zeros (which the backend settles as SHORT), and that the payload count equals the line count. A failing-fast guard against the inverted contract.

## 8. Out of scope

- Offline fulfill / offline-cached queue (online-only by decision; system design's offline-capable fulfill deferred).
- Inline project or customer creation (projects/customers are picked from existing rows).
- Any cost/budget display (cost-only flow; schemas carry no cost).
- A notifications UI (backend sends SHORT/low-stock alerts via FR-018 on fulfill).
- Editing a pull after creation; per-line cancel; bulk actions.
- Any backend change (route/crud/model/migration/SDK regen).
