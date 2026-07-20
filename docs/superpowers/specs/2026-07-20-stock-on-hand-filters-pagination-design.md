# Stock-on-Hand Filters and Pagination Design

## Goal

Make `/stock` scalable and internally coherent: all product dimensions shown in
the top-level table are filterable, all filters run server-side, supplier
filtering returns only matching products with supplier-scoped quantities, and
the list is paginated.

## Scope

- Remove the customer filter and its API support. The earlier FR-012 customer
  history behaviour is deliberately withdrawn from this screen.
- Keep Supplier as an admin-only filter. It narrows rows to products with
  positive in-stock inventory from that supplier. The `In stock` value remains
  scoped to that supplier, and the header names the selected supplier.
- Add server-side `q`, `brand`, and `category` filters. `q` matches product SKU
  or model name; brand and category are exact values, following the existing
  products endpoint convention.
- Add page-based pagination (25 rows per page) with a filtered `count`.
- Add supplier names to batch and unit drill-down rows for administrators only.
  Staff receive `supplier: null`, preserving the existing financial/provenance
  role boundary while retaining their drill-down.
- Remove Tracking from the desktop table and mobile card. The six desktop
  columns are expander, SKU, Model, Brand, Category, In stock, plus the label
  action. Supplier stays in the drill-down because one product can have stock
  from more than one supplier.

## Backend design

`crud.stock_on_hand` accepts `q`, `brand`, `category`, `supplier_id`, `skip`,
and `limit`, and returns `StockOnHandResponse(rows, count)`.

The supplier filter has two distinct jobs:

1. Its existing correlated aggregate subqueries scope the displayed quantity to
   the selected supplier.
2. A tracking-mode-aware correlated `EXISTS` predicate narrows the product set:
   `PartBatch` needs `remaining_qty > 0`; `Unit` needs `current_state =
   IN_STOCK`. This prevents unrelated products from appearing as zero rows.

The `EXISTS` predicate is used rather than filtering on the aggregate alias, so
PostgreSQL can identify matching products before applying `LIMIT`; the list
does not lose the performance benefit intended by pagination. The same product
filter clauses are applied to the rows query and the count query. Rows remain
ordered by SKU.

`GET /dashboards/stock-on-hand` exposes query parameters `q`, `brand`,
`category`, `supplier`, `skip`, and `limit`. `skip` is bounded to 0–10,000 and
`limit` to 1–500. Supplying `supplier` requires an admin role at the route,
matching the admin-only options UI; ordinary unfiltered stock access remains
available to staff.

The batch and unit endpoints receive `CurrentUser`. Their CRUD helpers select
the supplier name alongside each active batch or unit, but set `supplier` to
`None` for a non-admin response. No costs or COGS fields are added.

The schema/API contract changes, so the generated frontend SDK is regenerated
from the host after backend tests pass. No migration is expected: required
foreign-key/index support already exists for the quantity and unit paths.

## Frontend design

The toolbar contains debounced text inputs for search, Brand, and Category,
plus the existing admin-only supplier combobox. Every filter is included in the
TanStack Query key and sent to the endpoint. Changing any filter resets to page
one. The supplier combobox resolves the selected name from its already-loaded
option list to render `In stock (Supplier name)`.

The page adopts the established `usePagination` and `PaginationControls`
pattern with a page size of 25 and `keepPreviousData`. It clears the expanded
row when the page changes, avoiding an expansion tied to a row no longer shown.
The former client-side `deriveCategories` and `filterStockRows` logic is
deleted, along with `src/lib/stock-on-hand.ts` and its pure-logic test. The
customer filter E2E is deleted because that feature no longer exists.

Drill-down tables add a Supplier column. Because the API intentionally returns
`null` to staff, the UI renders an em dash for a missing value rather than
attempting to infer identity from serial data.

## Validation

Backend API tests cover exact `q`, brand, and category filtering; supplier row
narrowing and supplier-scoped quantities for both tracking modes; supplier
admin enforcement; count and page bounds; and supplier names visible to admins
but redacted for staff in both drill-down types. Existing customer-filter tests
are removed or replaced.

Frontend browser coverage replaces the customer-filter scenario with an
admin supplier-filter scenario that confirms an unmatched stocked product is
absent (not displayed as zero), the supplier-scoped heading is visible, and
pagination navigates between pages. Biome, TypeScript checks, the affected
pytest module, and the focused Playwright test are run before handoff.

## Out of scope

- Filtering unfiltered stock down to only positive-quantity products.
- Virtualized rendering beyond page-based pagination.
- Cost visibility in stock drill-downs.
- Restoring customer-history filtering elsewhere in the application.
