# Notes

## Open: Sale screen rejects a serialized product's SKU only at checkout

**Status:** deferred, 2026-07-10. Not yet designed. No code written.

### Symptom

On `/sale`, typing a SERIALIZED product's SKU (e.g. `iPhone-X`) adds a line to the
cart with no complaint. Checkout then fails:

```
POST /api/v1/sales  ->  400
{"detail": "PART line requires a QUANTITY-tracked product"}
```

The correct input is the unit's barcode (e.g. `CN-92E7DBDAD313458B`), which
resolves as a UNIT line and succeeds.

### Cause

`resolveScanResult` (`frontend/src/hooks/useScanLookup.ts:26`) classifies a scan by
lookup order: serial hit -> UNIT; serial 404 + sku hit -> PART; both 404 -> NOT_FOUND.
A serialized product's SKU misses the serial lookup and hits the sku lookup, so it is
classified PART. `create_sale` rejects it at `backend/app/crud.py:2134`.

The failure surfaces at checkout, not at scan time, and the message names an internal
concept ("PART line") that a warehouse user has no reason to understand. `/sale` is a
`requireAuth` staff screen, so staff are the ones who hit this.

### Relevant facts established while investigating

- `SkuSearchResult.tracking_mode` (`backend/app/models.py:1745`) is **already returned**
  to the client. The frontend has what it needs to reject at scan time and ignores it.
- The SKU search does **not** return unit barcodes. Any "pick a unit" UI needs a new
  backend surface.
- `ServiceTicket` has **no** `unit_id` — it binds to `customer_id`. Service history is
  not tied to a serial.
- `SaleLine.unit_id` (`backend/app/models.py:936`) is the only record linking a customer
  to a specific physical piece.
- `GET /search/serial/{barcode}` returns a unit's full chronological lifecycle and backs
  the `/search` staff screen.
- `Unit.purchase_cost_thb` is per-piece, so which unit is picked determines COGS.
- `holding_period_report` (`backend/app/crud.py:1185`) ages each unit by its own
  `received_at`.

### The unresolved question

Are serialized units interchangeable for **identity**, or only for accounting?

If the system auto-picks a unit and the staffer physically grabs a different one,
aggregate stock stays correct but identity inverts: the piece the customer holds reads
`IN_STOCK`, and a piece still on the shelf reads `SOLD`. That breaks the serial-lifecycle
lookup, which is a staff hot path.

Owner's initial read was that scanning is a data-entry convenience rather than an
integrity control. That was given before the identity-drift consequence was surfaced, so
it should be re-confirmed rather than assumed.

### Options on the table

1. **Block SKU entry for serialized products.** At scan time, detect
   `tracking_mode === "SERIALIZED"` on the sku-search response and surface
   "iPhone-X is serialized — scan the unit barcode." Frontend-only. No backend change.
   Preserves identity. Cheapest.
2. **System names the unit.** Type the SKU, system selects the oldest in-stock unit and
   tells the user which barcode to fetch. Faster. Identity correctness depends on staff
   compliance and is unverified.
3. **Unit picker.** Type the SKU, choose from a list of in-stock units. Human still
   selects a specific serial. Requires a new endpoint listing units by SKU.

### If picked up

Touches consumption, so per `CLAUDE.md` this is high-risk: design doc -> failing test
first -> `ecc:database-reviewer` + `ecc:security-reviewer` on review. Option 1 arguably
does not touch consumption at all (pure frontend guard), which may lower the bar.

---

## Minor: Country field length mismatch (suppliers)

> **FIXED 2026-07-11** on branch `fix/supplier-country-maxlength` (off `dev`). Set the
> Country `<Input maxLength>` to 64 in `suppliers.tsx` to match `SupplierBase.country`
> (backend cap 64). It was the only Country input; name/contact stay 255 (correct on
> both sides).

`frontend/src/routes/_layout/suppliers.tsx:114` sets `maxLength={255}` on the Country
input, but `SupplierBase.country` (`backend/app/models.py:242`) caps at 64. A 65–255
character country string passes client validation and returns 422. Cosmetic — nobody
types a 70-character country name — but the two numbers should agree. Name and contact
are correctly 255 on both sides.

---

## Minor: Zero-cost receipt blocked by UI only

> **RESOLVED — working as intended, 2026-07-11.** No code change. PRD v3.0 frames
> receiving cost as "cost from the supplier invoice" (FR-006) / per-piece "purchase
> cost" (FR-005) and never mentions free-of-charge, promotional, warranty-swap, or
> sample goods. There is no product requirement for zero-cost receipts, so the
> backend's `>= 0` is merely permissive, not a documented feature. The `> 0` UI guard
> (and its deliberate tests) is a reasonable fat-finger control. Revisit only if
> free goods turn out to be a real operational case.

`isPositiveCost` (`frontend/src/lib/receive-form.ts:94`) requires cost `> 0`, while the
API accepts `>= 0` (`backend/app/models.py:820`). A free-of-charge receipt is legal to the
backend but the submit button will not enable. Do not conclude the API rejects it.

---

## Bug: invalid/expired token doesn't redirect to login

> **FIXED 2026-07-11** on branch `fix/auth-401-redirect` (option 2). `get_current_user`
> now returns **401** (with `WWW-Authenticate: Bearer`) for invalid/expired/wrong-type
> tokens AND for the stale-token case (valid signature, subject no longer a user).
> 403 stays for role denials; route-level `/users/{id}` 404s unchanged; "Inactive user"
> left as 400 (distinct case, out of scope). No frontend change needed — `handleApiError`
> already redirects on 401. New tests in `backend/tests/api/test_auth_token_status.py`;
> updated `test_refresh_bearer_rejected.py` (403→401). Verified red→green, 50 auth/users
> tests pass, ruff+mypy clean. Run against the new `app_test` DB (see below).

**Found:** 2026-07-11 (surfaced when a stale JWT pointed at a since-deleted user).

`frontend/src/lib/query-client.ts:16` ends the session (clears token, redirects to
`/login`) **only on HTTP 401**. But `backend/app/api/deps.py:get_current_user` never
returns 401 for a bearer-token problem — it raises:
- **403** "Could not validate credentials" for an invalid / expired / wrong-type token
  (`deps.py:37-48`);
- **404** "User not found" when the token's `sub` matches no user (`deps.py:51-52`);
- **400** "Inactive user" for a deactivated user (`deps.py:53-54`).

So a present-but-unusable token (most importantly a normally **expired** one → 403)
leaves the user on a broken screen with no redirect. The 401 logout path effectively
only triggers when the `Authorization` header is entirely missing (OAuth2PasswordBearer
auto_error).

**Fix options (decide — touches auth):**
1. Frontend: also treat 403 "Could not validate credentials" and 404 on `/users/me` as
   session-end. Narrow, but 403 is overloaded (also legitimate role denials — the code
   comment at `query-client.ts:13-15` deliberately does NOT logout on 403, because staff
   hitting an admin endpoint is expected). Distinguishing needs matching on detail text
   or a dedicated code.
2. Backend: return **401** for token-validation failures (invalid/expired/wrong-type)
   and keep 403 strictly for role denials. Cleaner separation; frontend logic then
   correct as-is. Preferred, but changes API status codes (check tests/SDK consumers).
3. Both: 401 for auth failures (backend) AND redirect-to-login when `/users/me`
   specifically 404s (stale user).

Recommend option 2 as the root-cause fix. Not started.

---

## Bug: list endpoints silently truncate at 100 (products, customers, suppliers, projects, audit, overrides, pulls)

**Status:** found 2026-07-12 (surfaced while building the audit SKU autocomplete, as a
products-only bug). **Scope widened 2026-07-12** by a full backend + frontend audit: the same
defect affects **seven entities**, not just products.

> **DONE 2026-07-12** on `dev_wth` after merging `feat/product-options-pagination` and
> completing the remaining picker/table migrations below.
>
> **Products picker/lookup truncation — fixed.** New `GET /products/options`
> (`crud.list_product_options` / `products.py:read_options`) replaces the old
> `GET /products/skus`: an unpaginated `{id, sku, model_name, tracking_mode,
> retail_price_thb, repair_price_thb}` projection, ordered by SKU, for every product —
> the exact "lightweight `id`+label(+price) projection per entity" shape this section's
> "Fix direction" called for. A shared `frontend/src/hooks/useProductOptions.ts` hook
> replaces the truncated `readProducts()` call in all 6 picker/lookup screens: `sale.tsx`
> (price map), `receive.tsx` (both tabs' product selects), `tickets.tsx` (part lookup),
> `pulls.tsx` + `PullCreatePanel.tsx` (item picker), `pricing-overrides.tsx` (SKU labels),
> and the audit ledger's SKU combobox (which already used the interim `/products/skus`
> shape — now consolidated onto `/options` instead of two near-duplicate endpoints).
> `products.tsx`'s own catalog **table** is explicitly **not** touched by this fix — see
> "Still open."
>
> **Audit ledger truncation — fixed**, since it was rated **highest-volume** here (every
> stock movement lands there). `GET /audit` now returns `AuditPublic {data, count}`
> instead of a bare array (`crud.count_audit` mirrors `list_audit`'s exact filter
> construction, verified clause-by-clause in review, so the count can never disagree with
> the page it describes). `audit.tsx` sends real `skip`/`limit`, shows the true total on
> the "Movements" stat card, and has working Previous/Next controls (via the
> previously-unused `components/ui/pagination.tsx`) that reset to page 1 on any filter
> change. The cosmetic, never-backed "latest 100 shown" hint is gone.
>
> **Completed in the follow-up:** customer, supplier, and project option endpoints and
> bounded comboboxes; server-side pagination for products, customers, suppliers, projects,
> pricing overrides, project pulls, and users; filtered counts; and historical SKU/model
> labels on override and pull-line responses. The audit page remains owned by its concurrent
> branch and was not modified by the follow-up.

### Root cause (one pattern, many surfaces)

Nine backend list endpoints share an identical signature — `skip: Query(ge=0, le=10_000) = 0`,
`limit: Query(ge=1, le=500) = 100`: **audit, customers, products, projects, suppliers,
pricing-overrides, project-pulls, sync-review, users**.

**Only `GET /users/` returns a total `count`** (`UsersPublic.count`). Every other one returns a
bare array. So a client that omits `limit` gets the first 100 rows and has **no way to detect
that more exist** — the truncation is both silent *and* undetectable.

The frontend omits it nearly everywhere. Not hypothetical: the PRD targets **"hundreds of
SKUs"** (`docs/client/2026-06-02-castranova-pos-v3.0-prd.md:319`), and customers accumulate
faster than SKUs in a B2B trading business.

### Confirmed truncation — every call site below passes NO pagination args

| Entity | Call sites | Severity |
|---|---|---|
| **Customers** (`readCustomers`) | 4/4 bare: `customers.tsx:224` (table), `projects.tsx:68`, `sale.tsx:136`, `tickets.tsx:131` | **Highest** — the last three are the **checkout customer pickers**. Customer #101+ is unselectable, so a sale/ticket for that customer *cannot be recorded at all*. FR-007 requires a customer on every sale, so this blocks work outright. |
| **Products** (`readProducts`) | 7/7 bare: pickers `receive.tsx:147`/`:482`, `pulls.tsx:86`; catalog table `products.tsx:83`; lookup maps `sale.tsx:130`, `tickets.tsx:126`, `pricing-overrides.tsx:72` | **High** — the original finding. All seven share queryKey `["products"]`, so they share one truncated cache entry. |
| **Suppliers** (`readSuppliers`) | 4/4 bare: `suppliers.tsx:56` (table), `receive.tsx:152`/`:487` (pickers), `stock.tsx:63` (admin filter) | High |
| **Projects** (`readProjects`) | 2/2 bare: `projects.tsx:64` (table), `pulls.tsx:80` (picker) | Medium |
| **Audit ledger** (`listAudit`) | `audit.tsx:113` — `buildAuditQuery` (`lib/audit.ts`) never sets `skip`/`limit` | **Highest volume** — every stock movement lands here, so it overflows 100 fastest. The UI's `PAGE_LIMIT = 100` "latest 100" hint is **never sent to the API** — cosmetic only. Older history is unreachable. |
| **Pricing overrides** (`listPricingOverrides`) | `pricing-overrides.tsx:68` — sends `state` only | Medium |
| **Project pulls** (`readProjectPulls`) | `pulls.tsx:69` — sends `state` only | Medium |

Truncation is worst in **pickers/dropdowns**, where it is a *functional* bug (the record is
unreachable, so the work cannot be done) rather than a display shortfall.

### Worse than truncation: `admin.tsx` has pagination that lies

`admin.tsx:23` calls `readUsers({ skip: 0, limit: 100 })` — args *are* passed, but they are
**hard-coded, not page state**. It renders through `components/Common/DataTable.tsx`, which
uses TanStack's **client-side** `getPaginationRowModel()` (`DataTable.tsx:45`).

Result: real-looking first/prev/next/last buttons and a *"Showing 1 to 25 of 100 entries"*
counter that only walk the 100 rows **already in memory**. The pager **never re-queries**
`skip`/`limit`, so user #101 is unreachable no matter which button is clicked. Confidently
wrong is worse than visibly truncated.

Silver lining: `/users/` is the one endpoint that already returns a real `count`, so it is
also the easiest to fix properly.

### Backend-only ceiling (not fixable client-side)

`GET /search/sku/{sku}` (`crud.search_sku`) caps consumption history at a hard-coded
`_CONSUMPTION_LIMIT = 200` (`crud.py:1454,1640`), newest-first, with **no `skip` param at
all** — there is no way to page past 200 by construction. A busy SKU's older consumption
history is permanently unreachable through the API.

### Verified NOT bugs — do not "fix" these

**Deliberately unpaginated** endpoints return *everything*, so they cannot truncate (payload
size is the only consideration): `GET /products/options` (`crud.list_product_options` —
supersedes the now-removed `GET /products/skus`; same proven pattern, with an explicit size
rationale in its docstring), `GET /low-stock`, `GET /products/purchase-costs`,
`GET /dashboards/stock-on-hand`, plus the naturally-bounded sub-resource lists (price history,
notification prefs, per-product batches/units, service-ticket parts, project-pull lines).

`useProductOptions` already makes the Audit **SKU** combobox (`audit.tsx`) safe — but note the
Audit **User** filter is still a bare `readUsers()`, part of the "still open" customers-adjacent
follow-up above.

**Sales, service tickets, and stock adjustments have no list endpoints at all**, so they have
no exposure — don't go looking.

### Fix direction (decided and implemented)

Mirror the `/products/options` precedent: **lightweight unpaginated projections** per entity
for picker consumption, not heavy objects (`ProductPublic` carries JSONB `specs`, brand,
category, timestamps). This removes the cliff entirely and reuses a pattern already shipped
and justified in-codebase.

Explicitly rejected: **raising `limit` to 500** only moves the cliff from 100 → 500 while
leaving the defect class intact.

Tables now use the same `{data, count}` envelope with page-aware queries and filtered counts.

---

### ⚠️ BEHAVIOR CHANGE TO CONFIRM — pickers become "active-only" (2026-07-12)

**Owner asked to implement this, but flagged it here for later confirmation.**

Spec: `docs/superpowers/specs/2026-07-12-list-pagination-and-pickers-design.md` §3.

**What changes.** The picker/dropdown `/options` endpoints will filter out inactive records:

| Entity | Filter applied | Effect |
|---|---|---|
| **Products** | `GET /products/options?active_only=true` (`is_active`, `models.py:372`, indexed) | A **discontinued product disappears from the sale / receive / tickets / pulls dropdowns.** |
| **Projects** | `status = ACTIVE` (`ProjectStatus`, `models.py:105`) | A **CLOSED project can no longer be selected when creating a project pull.** |
| Customers, Suppliers | *none — these tables have no active flag at all* | No change possible. |

**Deliberately NOT filtered: the audit SKU combobox.** It shares `/products/options`, and
`list_product_options`' own docstring notes it must include inactive products — "whose
historical movements still appear in the append-only ledgers." Filtering them out would make
a discontinued product's SKU unfilterable in the ledger. Hence the filter is an **opt-in
query param** (`active_only`, default `false`), which the *pickers* pass and the *audit
filter* does not — rather than an unconditional `WHERE` on the endpoint.

**Why.** `is_active` is currently **read nowhere in the frontend** — so today, discontinued
products still appear in every dropdown, and a closed project can still take new pulls. That
is a live bug; the filter fixes it, and also shrinks the picker payload.

**What does NOT change.** The **tables** (`products.tsx`, `projects.tsx`) still list
*everything*, so an admin can still see, edit, and re-activate an inactive record. Only the
*pickers* are filtered.

**Confirm this is what you want**, specifically:
1. Staff should **not** be able to sell / receive / repair against a **discontinued** product.
2. Admin should **not** be able to open a project pull against a **CLOSED** project.

If either should stay permitted, drop that filter — it is a one-line `where` clause per
endpoint, and the picker still works without it (just larger, and showing dead records).

---

## List & picker UI polish (2026-07-12)

> **DONE 2026-07-12** on branch `feat/list-ui-polish`. Frontend only — no backend, schema,
> or migration change. Shipped: a shared `ListShell` (60vh scroll box + sticky header +
> dim-and-loading-bar overlay), a `scrollbar-thin` utility applied to every list and picker
> scroll box, a 250 ms debounce (`useDebouncedValue`) on the pickers and the stock search,
> one shared pager (`PaginationControls`, now with first/last) on **every** list, and
> `placeholderData: keepPreviousData` everywhere a page or filter change re-queries.

**The "loading flash" turned out to be three separate bugs, not one.** Worth recording,
because the worst of them was invisible in the original report:

1. **A misleading empty state, not a spinner.** `products.tsx`, `customers.tsx`,
   `suppliers.tsx` and `stock.tsx` had **no loading branch at all**. On a page turn `data`
   went `undefined` → `?? []` → the screen rendered **"No products yet." / "No customers
   yet."** for a frame. A page turn was briefly telling the user their records did not
   exist. That is worse than a spinner, and it is what "flashing" actually was on those
   screens.
2. **The table unmounting to a "Loading…" line** — `audit.tsx`, plus every filter-driven
   report.
3. **Re-suspending to a skeleton** — `admin.tsx` was the lone `useSuspenseQuery`; its
   query key changed per page with no `placeholderData`, so Suspense re-fired and flashed
   `PendingUsers`. It is now a plain `useQuery` like the other seven lists, and
   `PendingUsers.tsx` was deleted as orphaned. (`PendingItems.tsx` was **already** dead
   code before this change — still is; left alone.)

**`projects.tsx` needed nothing** — the projects *table* was already server-paginated
(`usePagination` + `readProjects({skip, limit})` + `PaginationControls`) and was in fact
the only screen that already had `keepPreviousData`. The concern that it had been missed
because "the projects *picker* doesn't need pagination" was unfounded: picker and table
are separate surfaces and only the picker was ever unpaginated by design.

**The real picker jank was not `EntityCombobox`.** `audit.tsx` carried its own hand-rolled
`SkuCombobox` copy with cmdk's filtering left **on**, an uncontrolled input, and **no
render cap** — it mounted a `CommandItem` for *every* product and re-scored them all on
each keystroke. It is now the shared `EntityCombobox` (50-item cap + "Show more" +
debounce), which deleted ~60 lines. It still calls `useProductOptions()` with **no**
`activeOnly`, so the ledger can still filter by a discontinued SKU.

**Deliberate exception:** `pulls.tsx` polls every 30 s, so its loading flag is
`isPlaceholderData` only, never `isFetching` — otherwise a background poll would pulse the
loading bar twice a minute.

**Not fixed here (pre-existing):** `receive.tsx`, `sale.tsx`, `tickets.tsx`,
`PullCreatePanel.tsx` and `usePagination.ts` are **not biome-clean on `dev_wth`** (format +
import-order drift). Untouched deliberately, to keep this diff surgical — pre-commit will
reformat them on whichever branch next edits them.

### Still open — follow-ups this pass surfaced

- **Audit's User filter still truncates at 100.** `audit.tsx` resolves actor names with a
  bare `UsersService.readUsers()` (no `skip`/`limit`), so it is the one picker the
  pagination migration never converted — user #101+ is missing from the filter dropdown
  *and* their rows render as "Unknown user". Fixing it properly needs a lightweight
  `GET /users/options` endpoint (a backend change), mirroring
  `/customers|suppliers|projects|products/options`. **Not done — needs a backend endpoint.**
- **Catalog list pages need a search filter.** With 25 rows a page and no search, finding
  one customer/product/supplier means paging through the list by hand. Server-side
  pagination made this *more* acute, not less: the rows you want are now genuinely not on
  the client. Each list endpoint would need a `q`/`search` query param (name/SKU
  substring), plus a debounced input that resets to page 1 — the debounce hook and the
  page-reset pattern both already exist.
- **"Create new" should move behind a tab or a modal.** `products.tsx`, `customers.tsx`,
  `suppliers.tsx` and `projects.tsx` all stack a full create-form `Card` *above* the table,
  so the primary thing (the list) is pushed below the fold by a form that is used rarely.
  Move it into a dialog behind a "New …" button (the pattern `AddUser` on `admin.tsx`
  already uses) or a tab, and let the list own the page.
- **`EntityCombobox` doesn't look good on mobile (2026-07-13, owner-reported).**
  `PopoverContent` is pinned to `w-(--radix-popover-trigger-width)` (`EntityCombobox.tsx:112`)
  — a floating panel exactly as wide as its trigger, positioned relative to it. On a phone
  that's a cramped surface for a search input + up to 50 rows + "Show more", and a
  Radix `Popover` doesn't reflow around the on-screen keyboard the way a bottom sheet does
  — the panel can end up partially hidden behind the keyboard instead of resizing to sit
  above it. This affects every picker (`sale`/`tickets`/`projects` customer pickers,
  `receive` product/supplier pickers, `PullCreatePanel` project picker, the `stock` supplier
  filter, the `audit` SKU filter) and the same issue applies to the filter *row* triggers
  (`Select`) sitting next to them.
  **Suggested direction:** on mobile (`useIsMobile()`, already used everywhere else for the
  card-vs-table split), swap the `Popover` for a bottom sheet — either the `Sheet` primitive
  already in the app (`components/ui/sheet.tsx`, used by `AuditDetailSheet`) with
  `side="bottom"`, or add `vaul`'s `Drawer` (shadcn's usual mobile-combobox pattern; not yet
  a dependency here) for swipe-to-dismiss. Either way the search input + list keep their
  desktop behavior — only the container becomes a fixed, full-width, keyboard-aware sheet
  instead of a `Popover` anchored to the trigger. **Not built — recorded for later.**
- **Catalog lists — owner's combined spec (2026-07-13):** *"make catalog lists - hide
  register behind a pop up model or a form tab - add list filters."* This is the same pair
  of asks as the two bullets above, restated together as one unit of work for the catalog
  list pages (`products.tsx`, `customers.tsx`, `suppliers.tsx`, `projects.tsx`): (1) move
  the create ("register") form behind a popup dialog or a form tab instead of sitting above
  the table, and (2) add filters to the list itself (name/SKU search at minimum). Treat as
  one PR — a filter row and a "New …" trigger both land in the same header area above the
  table, so it is cheaper to lay out once than to patch the create-form move and then the
  filter row separately. **Not built.**

---

## List tables: split-header + flush-left pickers + sidebar scrollbar (2026-07-13)

> **DONE 2026-07-13** on branch `feat/list-table-split-header`, merged to `dev_wth`
> (`8352e3d`). Frontend only. Fixes the header-tint inconsistency this same UI-polish pass
> introduced above (`bg-background` had overridden shadcn's `bg-muted` tint on 13 of 14
> lists — only `audit.tsx` kept the tint, which is why it "looked different").

**Shared `ListTable` component** (`components/Common/ListTable.tsx`): a frozen, tinted
header band above a scrolling row area, so the scrollbar runs beside the rows only — audit's
original structure, generalized to all 15 list tables (admin, products, customers,
suppliers, projects, pricing-overrides, override-exceptions, holding-period,
channel-margin, low-stock, notifications, sync-review, stock, PullQueue, audit itself).
Uses `table-fixed` + a per-list `<colgroup>` so the header table and body table stay
aligned, native `overflow-auto` + `scrollbar-gutter: stable` (not Radix `ScrollArea` —
dropped as a dependency) so the reserved scrollbar gutter is identical on both tables, and
a `minWidth` prop for the tables that can't survive a narrow desktop viewport (`products`
at 9 columns, `stock` at 8, `override-exceptions` at 8) — those get a horizontal scrollbar
on the body with the header/footer mirroring `scrollLeft`. `channel-margin`'s totals row
became a third pinned table via a `footer` prop.

**Bug caught and fixed before shipping:** `ListTable`'s truncation rule
(`[&_td]:overflow-hidden`) is a descendant selector (CSS specificity 0,1,1), which beats a
plain `overflow-visible` utility placed directly on a `<TableCell>` (specificity 0,1,0). The
"escape hatch" for action-button cells (Edit, Approve/Reject pairs) was silently doing
nothing until switched to Tailwind's important-modifier syntax, `overflow-visible!`, across
all ~10 affected cells (`products`, `pricing-overrides`, `sync-review`, `stock`, etc.).
Worth remembering for any future addition to a `ListTable` row: a plain `overflow-visible`
on a cell will not override the table-level rule.

**Also shipped:** `EntityCombobox` — the checkmark moved to the trailing edge so labels sit
flush left (was indented behind a leading check slot); the sidebar (`AppSidebar.tsx`) got
the same `scrollbar-thin` treatment as every list/picker.

**Orphaned and removed:** `Table`'s `containerClassName` prop (`ui/table.tsx`),
`ui/scroll-area.tsx` and its `@radix-ui/react-scroll-area` dependency (`bun.lock` +
`package.json` updated via `bun install`) — audit's old bespoke two-table hack was the only
consumer.

**Not verified — no browser click-through was done.** `tsc`/biome/production build are
clean and the built CSS was confirmed to contain `.gutter-stable`/`.scrollbar-thin`, but
column alignment between a frozen header table and its independently-scrolling body table
is the one thing that's easy to get subtly wrong and hard to catch from reading code alone.
Check `products` and `stock` specifically (tightest column counts) at a normal desktop
width and near the 768px mobile cutoff where `minWidth` triggers horizontal scroll.

---

# PRD conformance audit — v3.0 vs implementation

**Audited:** 2026-07-10, against `docs/client/2026-06-02-castranova-pos-v3.0-prd.md`
(v3.0, 2 June 2026 — the client-facing, signed proposal). All 20 FRs plus the §8
non-functional claims. 16 inconsistencies found.

The pattern: the ledger and its guarantees were built rigorously. The client-facing
surface — exports, drill-downs, offline, printing — is where the PRD outran the code.

## Severity 1 — contradicts an explicit client promise

### FR-007: PRD forbids walk-in sales; the UI defaults to them

> **FIXED 2026-07-11** on branch `feat/no-walkin-default` (commit `ec55e12`). Removed
> `WALK_IN_RE` / `findWalkIn` / the auto-select effect from `sale.tsx` and `tickets.tsx`;
> added an FR-007 E2E assertion (no auto-select, checkout blocked until a customer is
> chosen). Verified red→green, all sale+tickets specs green, tsc clean.

PRD §6.3: "**A customer is always required** (no walk-in or anonymous sales)."

`frontend/src/routes/_layout/sale.tsx:49-54` defines `WALK_IN_RE` / `findWalkIn`, and
`sale.tsx:152-157` auto-selects the match on load. Its own doc comment: "A walk-in
customer is the default counter sale when no specific customer is chosen." Same pattern
in `tickets.tsx:53-56,196-200`.

Backend still requires non-null `customer_id`, so the constraint holds literally. But if
any customer row is named "Walk-in" (the test fixtures seed exactly that), every sale
silently attributes to it unless the staffer intervenes — defeating the per-customer
margin attribution the system exists to produce.

~~**Decision needed.** Either remove the default or amend the PRD.~~ **Resolved** — the
default was removed (see the FIXED note above); the PRD's "no walk-in" promise now holds
in the UI as well as the backend.

### §8.3: "auto-logs-out after 12 hours of inactivity" — no idle timer exists

> **DONE 2026-07-11** on `dev_wth` (idle-auto-logout feature; spec + plan under
> `docs/superpowers/`). Implemented as a **sliding-window refresh**, not a DOM idle
> timer: `ACCESS_TOKEN_EXPIRE_MINUTES=15`, `REFRESH_TOKEN_EXPIRE_MINUTES=60*12` (the
> 12h refresh cookie is rotated + max-age-reset on every refresh = the sliding
> window). The frontend now actually uses the refresh flow: `auth-session.ts`
> (single-flight refresh, `ensureValidSession`, `endSession`) + a 401
> refresh-then-retry response interceptor + a boot-time session check.
> **Offline resolved as (ii):** replay is gated on `ensureValidSession()` — offline
> <12h refreshes silently and replays; offline >12h forces re-login but the queued
> sale stays paused and replays post-login (idempotent) → **zero data loss**. Also
> fixed a real prod bug found in E2E: `OpenAPI.WITH_CREDENTIALS` was `false`, so the
> refresh cookie was never sent cross-origin (refresh would have silently failed in
> dev + prod). `logout()` now clears the server cookie (true logout). E2E:
> auth-session 4/4, sale offline 5/5; backend refresh/TTL tests green.


> **RETRACTED 2026-07-12 — the paragraph below is stale; both controls now exist.** See
> the `DONE 2026-07-11` block above: the sliding-window 12h idle-logout shipped
> (`ACCESS_TOKEN_EXPIRE_MINUTES=15` + a 12h refresh cookie rotated/reset on every
> refresh) and the 7-day offline-queue cap shipped (`query-client.ts:106`,
> `staleItemFor`). PRD §8.3 (line 336) and the §9 deferral rationale (line 392,
> "12-hour auto-logout + 7-day queue cap") are therefore **now accurate** — the
> deferral of app-level encryption rests on controls that genuinely exist. No PRD change
> needed. Original finding kept below, struck through, for the record.

~~`backend/app/core/config.py:36` — `ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 8`. A fixed
**8-day** TTL, not 12 hours, and not inactivity-based. No idle timer anywhere in
`frontend/src`; the only automatic logout is on a 401 (`query-client.ts:16-19`). A
7-day refresh token exists (`login.py:83-119`) but `useAuth.ts` never calls it.~~

~~**Escalate this one.** PRD §9 defers "stronger app-level encryption of offline cached
data" on the stated grounds that v1 relies on "device-level encryption + 12-hour
auto-logout + 7-day queue cap." Two of those three compensating controls were never
built. A deferral was justified by controls that do not exist.~~

## Severity 2 — offline (§8.3) is the largest functional gap

| Claim | Reality |
|---|---|
| "Sales, scans, maintenance entries, and project-pull fulfillments are saved on the device first" | Only **sales** + **serialized receipts**. `tickets.tsx:223-224` and `pulls.tsx:132-137` have no `mutationKey`, so they cannot be replayed — they just fail offline. Registered keys: `query-client.ts:41-48` (`["sales"]`, `["receipts"]` only). |
| "The system spots the conflict on sync and surfaces it for review" | No client code detects a 409 or calls the ingest endpoint. `sync-review.tsx` only lists/resolves. The admin queue has **no producer**. |
| "The offline queue is capped at 7 days" | No cap. `SyncReviewReason.STALE` is produced only in tests (`test_sync_review.py:28`). |

Backend for all three is built and correct (`sync_review.py:20-37`). The client half was
knowingly deferred — `docs/superpowers/plans/2026-06-06-part4.3-sync-review.md:8`:
"auto-capture is deferred to Part 5." The client-facing PRD still advertises it as
delivered.

> **MOSTLY DONE 2026-07-11** on `dev_wth` (branch `feat/sync-review-producer` + the
> offline work merged with idle-auto-logout). The client half now exists in
> `query-client.ts`:
>   - **Conflict producer built** — an offline-origin 409 on replay is diverted to the
>     admin review queue as `CONFLICT` via `ingestSyncReviewItem` (`query-client.ts:45-69`).
>     The admin queue now has a producer.
>   - **7-day cap built** — paused mutations older than the cap are dropped before replay
>     (`query-client.ts:104-112`, `staleItemFor`), so a forgotten device can't replay
>     stale actions.
>   - **Offline replay extended** — `pull-fulfill` now has a `mutationKey`
>     (`query-client.ts:142`), so project-pull fulfillments queue/replay offline (was
>     sales + receipts only).
> **DONE 2026-07-12: maintenance (tickets) offline.** Merged into `dev_wth` — commits
> `4f520f6` ("atomic idempotent record endpoint") + `6e16b80` ("single atomic record
> call + offline replay (FR-008, §8.3)"). `feat/tickets-atomic-record` tip now equals
> `dev_wth` HEAD (`f335ae0`); `git log dev_wth..feat/tickets-atomic-record` is empty.
> `tickets.tsx` now records via a single atomic call with an offline mutationKey, so the
> §8.3 "maintenance entries saved on the device first" claim is fully met. This was the
> last Severity-2 offline gap.

## Severity 3 — scope shortfalls

- **FR-017** "One-click PDF and Excel export from every list view and report."
  > **RESOLVED — not a gap, 2026-07-11 (owner read: reports-only).** All **report**
  > surfaces export both PDF + Excel: channel margin, holding period, override
  > exceptions (frontend `channel-margin.tsx` / `holding-period.tsx` /
  > `override-exceptions.tsx` each wire `downloadReport` → PDF + Excel buttons;
  > backend `reports.py:76,88 / :197,210 / :137,149`). The other surfaces the audit
  > counted (stock-on-hand, search results, customer detail, project detail, audit
  > log, low-stock, adjustments) are **list views, not reports** and have no export.
  > Owner confirms FR-017 is intended as the report surfaces, which are complete;
  > per-list-view export is **out of scope** unless requested later.
- **FR-013** "Drill-down by product, customer, or project."
  > **DONE 2026-07-11** on `dev_wth` (merge `bc42bfc`, branch
  > `feat/channel-margin-drilldown`; spec+plan under `docs/superpowers/`). The fixed
  > 3-row `channel_margin_report` is replaced by `crud.margin_report(group_by, channel)`
  > returning a `MarginBreakdownReport` re-sliceable by **channel / product / customer /
  > project**, optionally scoped to one channel, with a reconciliation invariant (all
  > groupings foot to the same month totals). Routes gained `group_by`/`channel` params;
  > PDF/XLSX exports generalized; legacy model deleted; SDK regenerated; frontend gained
  > Group-by + Channel controls. Built via the full skill loop (7 TDD tasks, per-task
  > review). Final high-risk review (security + database + code) caught & fixed a Critical
  > SALE-COGS rounding-reconciliation hole (product/customer used the rounded per-unit
  > `SaleLine.unit_cost_thb` instead of the authoritative FIFO `Sale.total_cogs_thb`);
  > fixed to source from `CostLine`/`Unit` exact grain + non-cent-divisible regression
  > test. Backend green on `app_test`, E2E 7/7, mypy+ruff clean.

  ~~Absent. `crud.channel_margin_report` (`crud.py:2930`) takes only `(year, month)` and
  returns a fixed 3-row summary (`models.py:1538`: "always 3 rows").~~
- **FR-018** 4 events promised.
  > **DONE 2026-07-11** on `dev_wth` (commit `55162b4`, branch
  > `feat/pull-fulfilled-notify`). `PULL_FULFILLED` now fires: sender
  > `notify_pull_fulfilled` + `_render_text` branch (`services/notify.py:225,269`), wired
  > from the pull-fulfillment route (`project_pulls.py:119` →
  > `notify_pull_fulfilled_bg`). All 4 events now send. (Note: `notify.py` moved to
  > `backend/app/services/notify.py` since the audit.)

  ~~**3 fire.** `PULL_FULFILLED` existed in the enum/migration but had no sender, call
  site, or template — it would raise `NotImplementedError`.~~
- **FR-005** "prints a label for the warehouse label printer."
  > **Re-examined 2026-07-11 — "wrong dimensions" retracted; still deferred.** The
  > audit's "4×6" was inherited from a **PRD self-contradiction**, not a real
  > requirement. FR-005 itself (PRD line 194) states **no** size. The size lives in
  > the hardware section (PRD line 356), which calls the TSC TDP-225 a **"2-inch
  > desktop"** printer that **"uses 4×6 inch label rolls"** — impossible: a 2-inch
  > print head (~54mm printable, ~60mm max media) cannot feed 4-inch-wide stock;
  > 4×6 is a 4-inch-printer format. So the code's **60×30 mm** (`barcode.py:18-22`)
  > is *plausibly correct* for the actual hardware, and changing it to 4×6 would
  > break it. Delivery is a QR PDF opened in a new tab (`PrintLabelButton.tsx:50-55`)
  > and printed via the browser dialog — **valid as long as the PDF page size equals
  > the loaded roll and printing is at 100%** (no ZPL/TSPL needed for that path).
  > **Blocked on one unknown:** the actual label-roll size purchased for the shop
  > (owner: no answer yet). If it differs from 60×30 mm, the only change is
  > `_LABEL_W/_LABEL_H` + layout — verifiable with a 100%-zoom PDF and a ruler, no
  > direct-to-printer test. **Also: fix PRD line 356** ("4×6 inch label rolls" → a
  > 2-inch-compatible size).
- **FR-019** "filter the audit log by user, date, event type, SKU, or batch."
  > **BATCH FILTER DONE 2026-07-11** on `dev_wth` (branch `feat/audit-sku-batch-filters`,
  > migration `m028` audit_filter_indexes). `audit.py` now accepts `batch_no` ("restrict
  > to PART entries that created or drew from a batch", `audit.py:40-63`) alongside the
  > existing user/date/event-type/`product_id`/`unit_id`. **SKU** is still only indirect
  > via `product_id` (no direct SKU param) — minor residual if a literal SKU filter is
  > wanted. **[Superseded — see 2026-07-12 note below.]**
  > **BATCH FILTER REMOVED 2026-07-12** on branch `fix/audit-model-filter` (migration
  > `m029_drop_batch_no_audit_indexes`). Deliberate decision, not a regression: FR-019
  > lists SKU *or* batch as alternative options, not a mandate for both, so the `batch_no`
  > filter (and its indexes/query param/UI input) was removed entirely — `sku` is kept as
  > the direct filter and is now the one wired to something visible in the table: the
  > audit ledger's "Model name" column was renamed to "Model" and now shows the SKU
  > stacked in muted small text under the model name on every row (desktop table cell and
  > mobile card), so filtering by SKU has a visible on-screen anchor.
- **FR-006** "Missing or extra items vs the supplier manifest are flagged for
  confirmation." No manifest entity (`crud.py:688-689` says so). Just `expected_qty` +
  a composed free-text note (`_discrepancy_note`, `crud.py:646-655`). No flag, no
  confirmation step, no alert.
  > **Detail added 2026-07-11 (still undecided — build vs amend PRD).**
  >
  > **`expected_qty` is write-only, single-use.** Full lifecycle: entered at
  > `receive.tsx:681` → mapped at `receive-form.ts:83-84` (blank → `null`) →
  > `ReceiveQuantityRequest.expected_qty` (`models.py:827`, a **request-only field**,
  > explicitly "transient", **not a column** on any table) → route `receipts.py:53` →
  > consumed at exactly one place, `crud.py:738-739` → `_discrepancy_note`. That helper
  > (`crud.py:646-655`) does *only*:
  > `if expected_qty is not None and expected_qty != received_qty:` append the sentence
  > `"Discrepancy: expected N, received M."` to the movement `notes`.
  >   - expected **== received** → `expected_qty` silently discarded (no record a check ran).
  >   - expected **is null** (blank field) → discarded.
  >   - expected **≠ received** → interpolated into free-text prose on the `RECEIVED`
  >     movement's `notes`; the number itself is never stored as a number.
  > Nothing reads it back: the `"Discrepancy: …"` string is *produced* at `crud.py:652`
  > and consumed by **nothing** — no filter, no report, no parser, no status. It's prose
  > a human must open a specific batch's movement to see. So today expected-qty is
  > **neither a control nor a signal** — a one-shot string formatter, firing only on
  > mismatch, leaving nothing queryable.
  >
  > **Two jobs a real "flag for confirmation" could do — the code does neither:**
  >   - **Job A — moment-of-receiving gate.** On counted ≠ expected, force the staffer to
  >     acknowledge before commit (fat-finger guard). Cheap, frontend-heavy. Currently the
  >     batch commits unconditionally, no prompt.
  >   - **Job B — durable, findable signal.** Let a manager / whoever pays suppliers pull
  >     "every receipt where counted < invoice" to chase credits/redeliveries. Needs
  >     **structured** storage (a boolean flag and/or the expected value in a column) — you
  >     can't reliably query prose. Currently impossible.
  >
  > **The decision hinges on one operational fact (owner unsure as of 2026-07-11):**
  > *what happens with supplier money after goods arrive?* If a counted-vs-invoice
  > shortage must be **findable later to affect payment** (withhold / chase credit) →
  > build Job B (the real flag + a discrepancy report). If staff just resolve it on the
  > spot and nobody looks back → Job A gate at most, or amend the PRD to match the
  > free-text-note reality. Owner is testing the live flow first — receive page at
  > `/receive` (staff auth; QUANTITY product; e.g. qty 50 vs expected 100 → commits with
  > no prompt, discrepancy buried in the batch's movement note, unfindable afterward).
  >
  > **If built, this is high-risk** per `CLAUDE.md` (touches receiving / stock movements):
  > design doc → failing test first → `ecc:database-reviewer` + `ecc:security-reviewer` on
  > review. Adding a stored flag/column also requires an Alembic migration (current head
  > `m027`).
- **FR-012** "filterable by category, supplier, customer." Backend supports all three
  (`crud.stock_on_hand`, `crud.py:3508`); the UI exposes only category and supplier
  (`stock.tsx:48-71`). **Customer** is the only *accidental* gap — the route already
  accepts `customer` (`dashboards.py:21,27`) and `_filter_rows_by_customer`
  (`crud.py:3626`) is built; only the UI control is missing. Semantics to preserve if
  built: it narrows *which products* show (those the customer has ever bought/serviced),
  **not** the quantity — quantity stays total shop stock (asymmetric with the supplier
  filter, which narrows both). `read_customers` is open to any authed user
  (`customers.py:22`), so unlike supplier this filter *could* be shown to staff.
  > **FLAGGED — PRD self-contradiction (the "at what cost" clause), 2026-07-11.**
  > FR-012 (PRD line 237) says the FIFO batch drill-down shows "how many units in each
  > batch, when they were received, **and at what cost**." That is **impossible to honor
  > as written** given the PRD's own role model:
  >   - §6.1 (PRD line 187): Yangon staff have **"no financial figures on dashboards."**
  >   - §5.2 (PRD line 283): financial columns are **"completely hidden from staff (not
  >     just visually masked)."**
  >   - The stock dashboard *is* the staff warehouse tool — it's the "See live stock at
  >     Yangon" success metric (PRD line 130). So its primary users are exactly the ones
  >     forbidden from seeing cost.
  >
  > The implementation resolved the conflict correctly by **dropping cost** from the
  > both-roles drill-down: `BatchDrillRow`/`UnitDrillRow` omit it with an explicit
  > comment (`models.py:1565,1574`), `stock_on_hand` docstring says "No cost/COGS fields"
  > (`crud.py:3519`), and the audit itself praises the no-leak result (notes.md line 339).
  > So the missing cost column is **not a bug** — it's the PRD contradicting itself, with
  > the code choosing role-safety over the literal wording.
  >
  > **Fix the PRD, not the code.** Amend FR-012 line 237 to drop "and at what cost" (or
  > qualify it "admin only"). If the client genuinely wants cost visible, the *only*
  > correct build is an **admin-gated** cost column (mirroring the supplier-filter admin
  > gate), never on the staff-visible view.
- **FR-010** "monthly override exception report lists every override **sorted by
  deviation size**." Sorted by `created_at` (`crud.py:1146`).
  > **FIXED 2026-07-11** on `dev_wth`. `override_exceptions_report` now orders
  > `deviation_pct DESC, created_at ASC, id` (`crud.py`) — deviation size first
  > (largest = most scrutiny), created_at ascending as the tiebreak, `id` last for
  > a total order (the `999.9999` zero-default cap collapses many rows to one
  > deviation, so a deterministic tiebreak matters for the stable PDF/Excel
  > exports). Read-only report → not high-risk. New crud test pins the order
  > (`test_pricing_override.py`); 13/13 module tests green, ruff+mypy clean.
  > Frontend renders rows in received order (no client re-sort), so it flows through.
- **§8.2** "Login attempts are rate-limited." Implemented (`5/15 minutes`,
  `login.py:52-53`, on by default `config.py:42`) — but `limiter.py:6-11` documents that
  behind Traefik `get_remote_address` returns the proxy IP, making the limit
  **effectively global, not per-client**. Its own comment: "Before production deploy
  (Part 5.4)." Not done.
  > **FLAGGED — app-side IP rate limiting is currently broken, 2026-07-11.**
  >
  > **Root cause.** `limiter.py:12` keys the limit with slowapi's `get_remote_address`,
  > which reads `request.client.host` — the **TCP peer**, i.e. whoever opened the socket.
  > Any reverse proxy in front of the app *is* that peer for every request, so all users
  > collapse into **one shared bucket**. The limit is therefore global, not per-client.
  > This is not theoretical for us: Traefik is already in `compose.yml`, so the moment the
  > app runs behind it (dev included), the socket peer is the Traefik container for 100% of
  > requests.
  >
  > **Two failure directions, both bad:**
  >   - **Self-inflicted DoS (the worse one).** 5 failed logins from *anyone* exhaust the
  >     shared `5/15 minutes` budget and lock out **every** user for 15 minutes. A rate
  >     limit meant to stop brute-force becomes a way to freeze login for the whole shop.
  >   - **Weak isolation.** Individual attackers are no longer independently limited.
  >
  > Same defect applies to every other limit — `REFRESH`, `LOGOUT`, `PRICING_OVERRIDE`,
  > `SYNC_INGEST` all share this one `limiter` instance and key function (`limiter.py:14-18`).
  >
  > **Deployment makes this deeper, not shallower.** Whatever fronts the app buries the
  > real client IP one more layer:
  >   - **Traefik** (have it now) — forwards the client IP in `X-Forwarded-For`.
  >   - **Dokploy** (a candidate PaaS for deploy) — uses **Traefik under the hood**, so
  >     same situation, nothing new to solve.
  >   - **Cloudflare** (if put in front) — adds another hop; real IP arrives in
  >     `CF-Connecting-IP` (and appended to `X-Forwarded-For`). Its trusted IP ranges would
  >     also need allow-listing.
  >
  > **Fix direction (per the code's own comment).** Read the client IP from a forwarded
  > header (`X-Forwarded-For` / `CF-Connecting-IP`) via a custom `key_func`, or
  > `ProxyHeadersMiddleware` / uvicorn `--forwarded-allow-ips` — **but only trust it from
  > the known proxy IP(s)**. Trusting `X-Forwarded-For` blindly lets a client spoof a fresh
  > IP per request and bypass the limit entirely; `limiter.py:11` already warns against this.
  > Consider also (or instead) doing brute-force rate limiting **at the edge** (Cloudflare /
  > Traefik middleware) so malicious traffic never reaches the app — defense in depth, and a
  > better place to absorb a login flood.
  >
  > **Config-dependent, so verify per environment.** The concrete trusted-proxy list depends
  > on the final deploy topology (Traefik only vs Dokploy vs +Cloudflare), which is not yet
  > decided. Whatever is chosen, confirm the real client IP actually reaches the key_func
  > (e.g. log it, or hit login 6× from one host and confirm only *that* host is limited)
  > before trusting the limit in production.

## Not gaps — judgment calls

- **FR-010** "the sale waits in *awaiting approval* status." There is no Sale status
  field; the implemented design refuses to create the sale until an approved override id
  is attached (`crud.py:1112-1123`). This is arguably **better** — no half-finished sale
  in limbo, no partial state to reconcile. Recommend amending the PRD, not the code.
  > **Re-confirmed 2026-07-12 (PRD unchanged).** The shipped flow: within-threshold
  > overrides are `AUTO_APPROVED` and apply immediately; above-threshold ones become a
  > `PENDING` *override request* (admin decides via `POST /pricing-overrides/{id}/decide`,
  > `pricing_overrides.py:64-75`), and the sale cannot be created until an
  > `APPROVED`/`AUTO_APPROVED` override id is attached (`_apply_override_price` → 400 while
  > unapproved). There is no Sale "awaiting approval" status. LINE/Viber is only the
  > *notification* channel (`notify_override_pending` → `BKK_ADMIN`). Recommendation
  > stands — amend the two PRD occurrences (FR-010 body + §10 Tricky Scenarios row) when
  > the client doc is next revised; **not done here.**
- **FR-001** (CSV/Excel seed import) and **FR-004** (LINE/Viber bot enrollment) have no
  code. Both PRD entries say "KWG handles" them, so they read as delivery services
  rather than product features. Confirm that is the shared understanding — there is no
  script to run either way. `User.line_user_id` / `viber_user_id` are plain nullable
  columns "populated at deployment enrollment" (`models.py:172-175`).
  > **DECISION TO MAKE (FR-001 seed import) — 2026-07-11.** If we do build a seed path,
  > pick between two shapes:
  >   - **A — template file → fill → import flow.** Ship a blank CSV/Excel template with
  >     the expected columns; the owner (or KWG) fills it and imports through a UI/CLI
  >     that validates and reports row-level errors. Repeatable, self-serve, forgiving of
  >     bad data. More to build (template, parser, validation, error surfacing).
  >   - **B — simple seed script, run after customer data.** A one-shot script that loads
  >     products/opening stock from a fixed file, run once at deployment **after** customer
  >     records exist (so sales/service history can bind). Cheapest; not repeatable and no
  >     friendly error handling.
  >
  > Ordering constraint either way: customer data must land before seed stock/sales so
  > `customer_id` foreign keys resolve. Decide only if FR-001 turns out to be a real build
  > rather than a KWG-delivered service.
  >
  > **FR-004 clarified — outbound is built; only enrollment + tokens are missing (2026-07-11).**
  > The confusion to avoid: `line_user_id` / `viber_user_id` are **not** API keys — they're
  > per-recipient destination addresses. The API keys are separate and already wired
  > (`LINE_CHANNEL_ACCESS_TOKEN` / `VIBER_AUTH_TOKEN`, `config.py:114-115`, sent in the
  > request **header**; the user_id goes in the **body**). Outbound push (FR-018) is fully
  > implemented (`notify.py:75-113`, real HTTP + retry + append-only log). For a push to
  > actually fire, `notify()` needs three things (`notify.py:152-186`), in order:
  >   1. **Token in `.env`** — `LINE_CHANNEL_ACCESS_TOKEN` / `VIBER_AUTH_TOKEN`.
  >   2. **A `NotificationPreference` opt-in** (`enabled=True` for that channel+event) —
  >      checked first; no pref row → user silently skipped. **Self-service** via
  >      `PATCH /notifications/preferences` (`notifications.py:25-39`), so this is a normal
  >      in-app action, not a deployment step.
  >   3. **`user_id` populated** on the User row — else the send no-ops with
  >      `"recipient id not set (not enrolled)"` (`notify.py:162-177`).
  >
  > So the **only out-of-band / deployment provisioning is (1) tokens in `.env` and (3) the
  > user_ids.** FR-004's actual gap is just (3): there is **no inbound webhook/bot** to
  > capture user_ids automatically when someone follows/subscribes (LINE/Viber issue the id
  > at that moment). Until such a webhook exists ("KWG handles at deployment"), user_ids must
  > be set manually/out-of-band. Also note recipient targeting: `notify_pull_short` /
  > `notify_override_pending` only reach `BKK_ADMIN`-role users; `notify_low_stock` reaches
  > anyone with the enabled pref.

## Verified as solidly implemented

FIFO cost layering with correct multi-batch splits; append-only enforcement via DB
triggers (m021); three-tier server-side role gating (44 admin dependencies across 15
route files); cost redaction by separate response schemas with **no leak** — staff
batch-drill rows carry no cost field at all (`models.py:1561`). FR-014, FR-015, FR-020
fully implemented, including project budget-vs-actual (`crud.py:3205-3228`). The
LINE/Viber integration is real HTTP (`notify.py:75-113`) with tenacity retry and
permanent-failure logging, not a stub.

## Suggested order of attack

~~1. **FR-007 walk-in default** — silently corrupts the margin attribution the system
   exists to produce.~~ **DONE 2026-07-11** — default removed (`feat/no-walkin-default`).
~~2. **§8.3 12-hour logout claim** — a security deferral rests on it.~~ **DONE
   2026-07-11** — idle-logout + 7-day cap shipped; the §9 deferral rationale is now
   valid (see the RETRACTED note in the §8.3 section).
3. Decide, per item, whether to **build it or amend the PRD**. ~~FR-013 drill-down~~ (DONE
   2026-07-11) and ~~FR-017 breadth~~ (RESOLVED — reports-only) are settled; the live
   decisions are **FR-006** (manifest discrepancy) and **FR-001/FR-004** (KWG-delivered or
   not). FR-010 / FR-012 / FR-005 wording are documentation drift — PRD amendments
   recommended but not yet applied.

**Current top priorities (as of 2026-07-12):**
1. **List truncation at 100** (see the bug section above) — customer pickers block checkout;
   the audit ledger hides all but the latest 100 movements.
2. **§8.2 rate limiting behind the proxy** — a live self-DoS: 5 failed logins from anyone
   locks out every user for 15 minutes.
