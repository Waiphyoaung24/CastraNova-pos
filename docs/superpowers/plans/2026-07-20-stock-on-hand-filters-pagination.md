# Stock-on-Hand Filters and Pagination Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Make the Stock on hand dashboard query-filtered, paginated, supplier-correct, and role-safe.

**Architecture:** Extend the dashboard response and CRUD query with shared filters, correlated supplier-presence predicates, and offset pagination. The route validates this contract and protects supplier provenance. The React route becomes a server-driven filter/pagination client using existing pagination components.

**Tech Stack:** FastAPI, SQLModel/SQLAlchemy, PostgreSQL, pytest, React, TypeScript, TanStack Query, Playwright, generated OpenAPI SDK.

## Global Constraints

- Keep stock movements append-only; this change only reads inventory tables.
- All database access stays in backend/app/crud.py; routes validate/authenticate and delegate.
- Supplier filtering is admin-only; unfiltered stock remains staff-accessible.
- Supplier quantities stay supplier-scoped; unmatched products never appear as zero rows.
- Do not expose COGS/purchase costs; staff drill supplier values must be null.
- Regenerate, never hand-edit, frontend/src/client.
- No migration is expected unless query-plan inspection proves an index absent.

---

## File structure

- backend/app/models.py: response count and nullable drill supplier fields.
- backend/app/crud.py: shared filters, paginated query, role-shaped drill data.
- backend/app/api/routes/dashboards.py: bounded parameters and access enforcement.
- backend/tests/api/routes/test_dashboards.py: query, access, and redaction tests.
- frontend/src/routes/_layout/stock.tsx: server-driven filters, table, drill, pagination.
- frontend/src/lib/stock-on-hand.ts, frontend/tests/stock-on-hand.spec.ts, frontend/tests/stock-customer-filter.spec.ts: delete obsolete client filtering/customer coverage.
- frontend/tests/stock-supplier-filter.spec.ts: focused browser coverage.
- frontend/src/client/*: generated contract.

### Task 1: Define and test the paginated stock query

**Files:**
- Modify: backend/app/models.py:1858-1885
- Modify: backend/app/crud.py:4454-4599
- Test: backend/tests/api/routes/test_dashboards.py

**Interfaces:**
- Produces StockOnHandResponse(rows: list[StockOnHandRow], count: int).
- Produces BatchDrillRow and UnitDrillRow with supplier: str | None.
- Produces stock_on_hand(session, q=None, brand=None, category=None, supplier_id=None, skip=0, limit=100).

- [ ] **Step 1: Write failing API tests**

Add exact brand/category, case-insensitive SKU/model q, pagination, filtered count, and both tracking-mode supplier tests. Seed products stocked only by suppliers A and B; request A and assert only A remains with its A-scoped quantity. Replace customer-filter tests. Assert drill supplier equals the name for administrators and None for staff.

    response = client.get(endpoint, headers=staff_token_headers,
                          params={"q": sku[:8], "skip": 0, "limit": 1})
    assert response.status_code == 200, response.text
    assert response.json()["count"] == 1

- [ ] **Step 2: Run test to verify it fails**

Run: cd backend; ..\.venv\Scripts\python.exe -m pytest tests/api/routes/test_dashboards.py -q

Expected: FAIL because count, query/page parameters, narrowing, and drill suppliers are absent.

- [ ] **Step 3: Write minimal implementation**

Define StockOnHandResponse with rows and count. Define each drill row with supplier: str | None. In crud.py create one helper returning active-product, q, exact brand/category, and tracking-aware correlated exists clauses. Apply it identically to the count query and rows query. Preserve existing supplier-qualified aggregate subqueries, then order by SKU, offset(skip), and limit(limit). Remove _filter_rows_by_customer/customer_id. Select Supplier.name with active batches and units and only emit it when include_supplier is true.

- [ ] **Step 4: Run test to verify it passes**

Run: cd backend; ..\.venv\Scripts\python.exe -m pytest tests/api/routes/test_dashboards.py -q

Expected: PASS.

- [ ] **Step 5: Commit**

    git add backend/app/models.py backend/app/crud.py backend/tests/api/routes/test_dashboards.py
    git commit -m "feat(stock): paginate and filter stock on hand"

### Task 2: Expose the secure API contract and regenerate the SDK

**Files:**
- Modify: backend/app/api/routes/dashboards.py:12-51
- Modify: backend/tests/api/routes/test_dashboards.py
- Regenerate: frontend/src/client/*

**Interfaces:**
- Consumes Task 1 helpers.
- Produces GET /dashboards/stock-on-hand with q, brand, category, supplier, skip, and limit.

- [ ] **Step 1: Write failing route tests**

Assert staff gets 403 with a supplier ID, BKK admin succeeds, and skip=-1, skip=10001, limit=0, and limit=501 each get 422.

- [ ] **Step 2: Run test to verify it fails**

Run: cd backend; ..\.venv\Scripts\python.exe -m pytest tests/api/routes/test_dashboards.py -q

Expected: FAIL because supplier is not route-gated and limits are undeclared.

- [ ] **Step 3: Write minimal implementation**

Add q, brand, category, supplier, skip=Query(0, ge=0, le=10000), and limit=Query(100, ge=1, le=500) to the route. Reject a supplier for non-admin with detail Supplier filter is admin-only. Remove the customer argument/check. Forward supported filters and pass include_supplier=is_admin(current_user) to drills. Run scripts/generate-client.sh on the host; inspect generated types for count, q, brand, skip, and limit.

- [ ] **Step 4: Run test to verify it passes**

Run: cd backend; ..\.venv\Scripts\python.exe -m pytest tests/api/routes/test_dashboards.py -q
Run: cd frontend; bun run check

Expected: both exit 0.

- [ ] **Step 5: Commit**

    git add backend/app/api/routes/dashboards.py backend/tests/api/routes/test_dashboards.py frontend/src/client
    git commit -m "feat(stock): secure stock filter API"

### Task 3: Convert the Stock UI to server-side filtering and pagination

**Files:**
- Modify: frontend/src/routes/_layout/stock.tsx
- Delete: frontend/src/lib/stock-on-hand.ts
- Delete: frontend/tests/stock-on-hand.spec.ts
- Delete: frontend/tests/stock-customer-filter.spec.ts
- Create: frontend/tests/stock-supplier-filter.spec.ts

**Interfaces:**
- Consumes generated getStockOnHand({ q, brand, category, supplier, skip, limit }) and rows/count.
- Consumes usePagination({ pageSize: 25 }) and PaginationControls.

- [ ] **Step 1: Write the failing browser test**

Seed two suppliers and two products. As admin select supplier A, wait for the request, assert A is visible, B is absent, and the heading reads In stock (Supplier A). Seed 26 matching rows, navigate to page 2, and assert a final-page SKU is visible while a page-one SKU is absent.

- [ ] **Step 2: Run test to verify it fails**

Run: cd frontend; bunx playwright test tests/stock-supplier-filter.spec.ts --project=chromium

Expected: FAIL because filters are local and pagination is absent.

- [ ] **Step 3: Write minimal implementation**

Remove customer options, category Select/sentinel, client filtering imports, and tracking label import. Add debounced query, brand, and category inputs. Include settled filters plus skip and limit: pageSize in query key/request. Reset page on every filter change and clear expandedId on page change. Render stock rows, pass count to PaginationControls, remove Tracking from desktop/card props, and add Supplier cells to both drills, rendering an em dash for null.

- [ ] **Step 4: Run test to verify it passes**

Run: cd frontend; bun run check
Run: cd frontend; bunx playwright test tests/stock-supplier-filter.spec.ts --project=chromium

Expected: both exit 0 and no deleted module remains referenced.

- [ ] **Step 5: Commit**

    git add frontend/src/routes/_layout/stock.tsx frontend/tests/stock-supplier-filter.spec.ts
    git add -u frontend/src/lib/stock-on-hand.ts frontend/tests/stock-on-hand.spec.ts frontend/tests/stock-customer-filter.spec.ts
    git commit -m "feat(stock): filter and paginate stock dashboard"

### Task 4: Full scoped verification and review-note update

**Files:**
- Modify: docs/dev_notes/2026-07-18-full-code-review.md

**Interfaces:**
- Consumes all prior tasks.
- Produces accurate notes marking H-4 and the superseded customer/supplier finding resolved.

- [ ] **Step 1: Update the review note**

After successful verification, mark H-4 resolved and record deliberate customer removal, supplier route guarding/row narrowing, and server-side pagination.

- [ ] **Step 2: Run complete scoped verification**

Run: cd backend; ..\.venv\Scripts\python.exe -m pytest tests/api/routes/test_dashboards.py -q
Run: cd frontend; bun run check
Run: cd frontend; bunx playwright test tests/stock-supplier-filter.spec.ts --project=chromium

Expected: every command exits 0.

- [ ] **Step 3: Inspect final scope**

Run: git diff --check HEAD~3..HEAD
Run: git status --short

Expected: no whitespace errors and only pre-existing unrelated untracked files, if any.

- [ ] **Step 4: Commit**

    git add docs/dev_notes/2026-07-18-full-code-review.md
    git commit -m "docs: record stock dashboard hardening"

