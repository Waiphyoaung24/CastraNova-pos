# Design: List pagination + picker completeness

**Date:** 2026-07-12
**Status:** approved (brainstorming), pending implementation plan
**Risk:** HIGH — touches role-tiered financial fields (per `CLAUDE.md` §5). Review stage
must add `ecc:database-reviewer` + `ecc:security-reviewer`.
**Migration:** none required. Every change is read-side (response models + queries). No
table schema changes.
**Base branch:** `dev_wth`, **after** `feat/product-options-pagination` merges (see §0).

---

## 0. Prior art — what is ALREADY built (do not rebuild)

A concurrent branch, **`feat/product-options-pagination`** (4 commits, merging into
`dev_wth` imminently), already delivers two mechanisms this spec originally proposed:

| Commit | Delivers | Effect on this spec |
|---|---|---|
| `c83d200` | **`GET /products/options`** — replaces `GET /products/skus` with an unpaginated `{id, sku, model_name, tracking_mode, retail_price_thb, repair_price_thb}` projection | **This IS the products picker endpoint.** Do not create `/products/picker`. |
| `de3652d` | **`useProductOptions`** hook, migrated across `sale.tsx`, `receive.tsx`, `tickets.tsx`, `pulls.tsx`, `PullCreatePanel.tsx`, `pricing-overrides.tsx` | **The products picker call sites are DONE.** |
| `3e8eac2` + `f3c8403` | **`GET /audit` → `AuditPublic {data, count}`** + real Previous/Next in `audit.tsx` | Audit ledger is DONE. `audit.tsx` stays out of scope. |

**Consequences for this spec:**

- The **naming convention is `/options`, not `/picker`.** New picker endpoints follow it:
  `/customers/options`, `/suppliers/options`, `/projects/options`.
- The **hook convention is `use<Entity>Options`** (`frontend/src/hooks/useProductOptions.ts`).
- `AuditPublic {data, count}` is the **precedent for the envelope** — match its shape and its
  `crud.count_*` mirroring discipline (see §4).
- The **products picker is done except for the active-only filter** (§3), which must be added
  to the *existing* `/products/options`, not to a new endpoint.
- Remaining picker work is therefore **customers, suppliers, projects only**.

---

## 1. Problem

A backend + frontend audit (recorded in `notes.md`, 2026-07-12) found a single defect
class across seven entities.

Nine backend list endpoints share the signature `skip: Query(ge=0, le=10_000) = 0`,
`limit: Query(ge=1, le=500) = 100`. **Only `GET /users/` returns a total `count`**
(`UsersPublic`, `models.py:188`). Every other list returns a bare array. The frontend omits
the pagination args at nearly every call site, so it silently receives the first 100 rows
and **cannot even detect that more exist**.

Consequences, worst first:

- **Checkout is blocked.** The customer pickers (`sale.tsx:136`, `tickets.tsx:131`,
  `projects.tsx:68`) are bare `readCustomers()` calls. Customer #101+ is unselectable, and
  FR-007 requires a customer on every sale — so that sale *cannot be recorded at all*.
- **Product pickers truncate** at 100 (`receive.tsx:147`/`:482`, `pulls.tsx:86`), against a
  PRD that targets "hundreds of SKUs" (PRD:319).
- **Supplier and project pickers truncate** (`receive.tsx:152`/`:487`, `stock.tsx:63`,
  `pulls.tsx:80`).
- **Management tables truncate** (`products.tsx:83`, `customers.tsx:224`,
  `suppliers.tsx:56`, `projects.tsx:64`, `pricing-overrides.tsx:68`, `pulls.tsx:69`).
- **`admin.tsx` paginates a lie.** It fetches a hard-coded `{skip:0, limit:100}` and renders
  through `DataTable`, which uses TanStack's *client-side* `getPaginationRowModel()`
  (`DataTable.tsx:45`). It shows real-looking page buttons and "Showing 1 to 25 of 100
  entries", but the pager only walks rows already in memory and **never re-queries**. User
  #101 is unreachable no matter what you click.

**Out of scope:** the **audit ledger** (`audit.tsx`). Another developer is building its
pagination concurrently. **This work does not touch `audit.tsx` at all** — including its
user-filter dropdown — to avoid a merge collision.

---

## 2. The governing rule

> **Pickers fetch complete. Lists paginate on the server.**

Every list surface falls into exactly one bucket; no surface does both.

| | **Pickers** | **Lists** |
|---|---|---|
| Endpoint | 4 new `/{entity}/picker` routes | 6 existing list routes, envelope changed |
| Shape | flat array, unpaginated, lean projection | `{data, count}` |
| Offline | **must** work offline (IndexedDB-persisted) | online-only |
| Query key | `["customers","picker"]` | `["customers", {skip, limit}]` |
| Rendering | `<EntityCombobox>` (search + 50-row cap) | existing table + `<PaginationControls>` |

Distinct query keys keep the two from colliding in the TanStack cache — which is *why*
they must be separate endpoints rather than one endpoint with a flag.

### Why pickers cannot use server-side search

The textbook fix for a large picker is a server-side typeahead (`GET /customers?q=`). **It
is ruled out here.** `main.tsx:72` wraps the app in `PersistQueryClientProvider`, persisting
the query cache to IndexedDB (`query-client.ts:128`); sales and tickets are offline-queued
mutations; FR-007 mandates a customer on every sale. **A staffer must be able to pick a
customer with no network.** A server typeahead cannot. The list must therefore be on the
device — fetch-complete is not merely acceptable for pickers, it is *architecturally
required*. The same reasoning applies to `sale.tsx`'s price map, which prices scanned items
offline.

---

## 3. Mechanism 1 — Picker endpoints (fetch complete)

Unpaginated, ordered, projection-only — the pattern `GET /products/options` already
establishes. **Naming follows `/options`, matching the shipped convention.**

| Route | Row model | Filter | Order | Status |
|---|---|---|---|---|
| `GET /products/options` | `{id, sku, model_name, tracking_mode, retail_price_thb, repair_price_thb}` | **add `is_active = True`** | `sku` | **EXISTS** — add filter only |
| `GET /customers/options` | `{id, name}` | — (no active flag exists) | `name` | new |
| `GET /suppliers/options` | `{id, name}` | — (no active flag exists) | `name` | new |
| `GET /projects/options` | `{id, code, name}` | `status = ACTIVE` | `code` | new |

**Each options route inherits the exact auth dependencies of its parent list route.** No new
access surface is created.

Frontend hooks mirror `useProductOptions`: `useCustomerOptions`, `useSupplierOptions`,
`useProjectOptions` (`frontend/src/hooks/`).

### Field sets are driven by actual consumption (traced, not guessed)

- `tracking_mode` is required: `receive.tsx` filters SerializedTab → `SERIALIZED` and
  QuantityTab → `QUANTITY`; `tickets.tsx` restricts `partLookup` to `QUANTITY`; `pulls.tsx`
  branches on it in `handleAddItem`.
- **Two different prices** are required: `sale.tsx` needs `retail_price_thb`;
  `tickets.tsx` needs `repair_price_thb` (repair parts price at repair, not retail).
- The projection sheds `specs` (JSONB), `brand`, `category`, `default_min_stock_level`,
  `is_active`.

### Active-only filtering

Verified against `models.py`: **`Product.is_active` exists and is indexed** (`models.py:372`).
**`Project` has `ProjectStatus = ACTIVE|CLOSED`** (`models.py:105`). **`Customer` and
`Supplier` have no active flag at all**, so the filter is a no-op for them.

`is_active` is currently **never read anywhere in the frontend**, so discontinued products
appear in every dropdown today. Filtering them out at the picker both shrinks the payload
and fixes that live bug. A `CLOSED` project should likewise not accept new pulls.

**This is a deliberate behavior change:** discontinued products and closed projects vanish
from pickers. Tables continue to show everything, so admins can still see and reactivate
inactive records.

### Role-tiering (the single most important review item)

`ProductPickerRow` carries `retail_price_thb` and `repair_price_thb`. These are **selling**
prices, which staff already see and transact at (`sale.tsx` prices at retail, `tickets.tsx`
at repair). The row carries **no `purchase_cost_thb`, no COGS, no margin**.

The PRD rule ("financial columns completely hidden from staff, not just visually masked",
§5.2) is about **cost**, not selling price. This design does not breach it. A test asserts
the cost key is **absent** from the payload — not merely null.

---

## 4. Mechanism 2 — Server-side pagination (lists)

Adopt the `{data, count}` envelope for all six remaining list responses: `ProductsPublic`,
`CustomersPublic`, `SuppliersPublic`, `ProjectsPublic`, `PricingOverridesPublic`,
`ProjectPullsPublic`.

Two precedents already exist — **follow `AuditPublic`** (from `feat/product-options-pagination`,
§0), which pairs a `crud.count_audit` that mirrors `list_audit`'s filter construction
clause-for-clause. `UsersPublic` (`models.py:188`) is the older, simpler precedent but its
count is unfiltered (safe only because it has no filters — see the invariant below).

This is a **breaking response change** (bare array → object). Every consumer is ours; the
SDK is regenerated (`bun run generate-client`).

### Invariant: `count` must honor the same filter as `data`

`read_users` computes `select(func.count()).select_from(User)` — **unfiltered**. That is safe
only because it has no filters. `pricing-overrides` and `project-pulls` filter by `state`.
Copying the unfiltered pattern would report *all* rows while the page shows *filtered* rows,
so the pager would offer pages that render empty.

> **Every `count` query must apply the same `WHERE` clause as its `data` query.**

This gets a dedicated test per filtered endpoint.

---

## 5. Denormalization — resolves a regression the active-only filter would introduce

`PricingOverridePublic` (`models.py:897`) and `ProjectPullLinePublic` (`models.py:1409`)
carry **only `product_id`** — no SKU or name. That is precisely why the frontend builds
`productLabels` (id→sku, `pricing-overrides.tsx:72`) and `productNames` (id→model_name,
`pulls.tsx`) from the products list.

With an active-only picker, those maps lose entries for deactivated products, so **historical
override rows and existing pull lines would render blank labels.**

**Fix — add to the response models (read-side only, no migration):**

- `PricingOverridePublic` **+ `product_sku`**
- `ProjectPullLinePublic` **+ `product_sku`, `model_name`**

This is strictly better than patching the lookup maps:

- **Historical rows become self-describing.** An override on a since-deactivated product
  still shows its SKU — correct by construction, not by whatever happens to be in a cache.
- **It deletes two products fetches outright.** `pricing-overrides.tsx:72` and `pulls.tsx`'s
  `productNames` map both disappear — two fewer truncation sites, two fewer cross-entity
  cache dependencies.
- `pulls.tsx` still uses the products picker, but only for the **create** panel, where
  active-only is exactly right.

---

## 6. Frontend components

### `<EntityCombobox>` (new, shared) — search + hard render cap

**The trap this exists to avoid:** `audit.tsx`'s `SkuFilter` renders `{skus.map(...)}` —
**every** item as a `CommandItem` — and relies on cmdk's built-in filtering. **cmdk keeps all
items mounted** and merely hides non-matching ones. DOM node count is therefore N *regardless
of what the user types*. Fine at hundreds of SKUs; at thousands of customers it mounts
thousands of nodes on open. There is **no virtualization anywhere in the frontend**.

**So autocomplete alone does not bound the DOM — it only fixes findability.** A render cap is
what bounds the DOM. The two solve different problems and must be combined.

Behavior:

- **Filter and slice in JS, then render.** `shouldFilter={false}` on `Command` — cmdk's own
  filter mounts everything, which silently reintroduces the bug.
- **`VISIBLE_LIMIT = 50`.** DOM is bounded at ~50 nodes regardless of dataset size. No
  virtualization dependency needed.
- **Load-more** bumps the slice by 50 — covers browsing when the user doesn't know the name.
- **Honest truncation notice**: "Showing 50 of 1,240". Never silently truncate again — that
  is the exact failure this whole project exists to fix.
- **Small lists degrade to nothing.** 12 suppliers → all 12 render, no footer, no button;
  identical to today's UX.

Rationale for combining: cap-without-search is unusable (25 clicks to reach customer #1,240);
search-without-cap janks the DOM. Each covers the other's failure.

Built on the existing `components/ui/command.tsx` + `popover.tsx`.

### `usePagination` + `<PaginationControls>` (new, shared)

- **`usePagination(pageSize = 25)`** → `{page, setPage, skip, limit}`.
- **`<PaginationControls total pageSize page onPageChange />`** — built on
  `components/ui/pagination.tsx`, which **already exists and is currently unused**.

These are **added underneath each existing table**. The bespoke table markup and mobile-card
layouts are **not** rewritten (`CLAUDE.md` §3 — surgical changes). Tables set
`placeholderData: keepPreviousData` so paging does not flash empty.

`admin.tsx` keeps `DataTable`, which gains optional `manualPagination` props (`pageCount`,
`pageIndex`, `onPaginationChange`) so its pager stops lying. `/users/` already returns a
`count`, so no backend change is needed there.

---

## 7. Call-site migration

Products pickers and the audit ledger are **already migrated** by
`feat/product-options-pagination` (§0) and are therefore struck from this table.

| Screen | Picker → complete | Table → server-paginated |
|---|---|---|
| `sale.tsx` | ~~products~~ *(done)* · **customers** | — |
| `tickets.tsx` | ~~products~~ *(done)* · **customers** | — |
| `receive.tsx` | ~~products~~ *(done)* · **suppliers** ×2 | — |
| `pulls.tsx` / `PullCreatePanel.tsx` | ~~products~~ *(done)* · **projects** | pull queue |
| `pricing-overrides.tsx` | ~~products~~ *(done — and the label map dies entirely, §5)* | overrides list |
| `stock.tsx` | **suppliers** | — |
| `projects.tsx` | **customers** | projects table |
| `products.tsx` | — | catalog table |
| `customers.tsx` | — | customers table |
| `suppliers.tsx` | — | suppliers table |
| `admin.tsx` | — | rewire the fake pager (count already exists) |
| **`audit.tsx`** | **untouched** — done by the other branch | **untouched** |

---

## 8. Error handling and edge cases

- **Page beyond the end** (rows deleted while paging): backend returns empty `data` with a
  truthful `count`; `usePagination` clamps `page` to `max(1, ceil(count / limit))`.
- **Offline picker**: served from the IndexedDB-persisted cache. A *cold* first load with no
  network has no list — that is existing behavior and is unchanged.
- **Customer picker ceiling**: bounded DOM via the 50-row cap, so the practical limit is
  payload/IndexedDB size, not rendering. Past a few thousand customers the next step is
  **virtualizing `<EntityCombobox>` — not server-side search**, which offline forbids.

---

## 9. Testing

**Backend (pytest, TDD — write the failing test first):**

- **Regression test, per picker route:** seed **150+** rows, assert the response contains
  *all* of them. This is the test that would have caught the original bug.
- Products picker excludes `is_active = False`; projects picker excludes `status = CLOSED`.
- **`count` honors filters:** seed mixed `state` values, request one state, assert `count`
  equals the *filtered* total, not the table total. Per filtered endpoint.
- Pagination: `skip`/`limit` return correct, disjoint slices; a page past the end returns
  empty `data` with a correct `count`.
- **Role-tiering:** a staff user hitting `/products/options` receives selling prices and the
  cost key is **absent** from the payload (not null — absent).
- Denormalized `product_sku` present on override rows and pull-line rows, **including for a
  deactivated product**.

**Frontend:**

- `bunx tsc --noEmit` + biome.
- E2E on **`app_test`** (per the saved worktree recipe — **never** the dev `app` DB):
  - a customer beyond the old 100-row cutoff is findable and selectable in the sale picker;
  - a table pager advances to page 2 and shows different rows.

---

## 10. Out of scope

- **The audit ledger** — concurrent work by another developer. `audit.tsx` is not touched.
  Once that lands, its `SkuFilter` should adopt `<EntityCombobox>` (it has the same
  unbounded-mount issue). Recorded in `notes.md`.
- **Virtualization** — unnecessary given the 50-row cap. Revisit only past a few thousand
  customers.
- **`GET /search/sku/{sku}`'s `_CONSUMPTION_LIMIT = 200`** hard cap (`crud.py:1454`) — a
  separate, backend-only ceiling with no `skip` param. Remains open in `notes.md`.
