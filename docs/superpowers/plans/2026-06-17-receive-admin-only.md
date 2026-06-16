# Receive Admin-Only Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make stock receiving admin-only at all three layers (nav, route guard, backend) and move the Receive link from the staff-visible Inventory group into the admin Operations group.

**Architecture:** Mirror the existing admin-only "Adjust" surface exactly. Backend swaps `CurrentUser` → `AdminUser` on both receive endpoints; the route swaps `requireAuth()` → `requireAdmin()`; the nav entry moves from `baseItems` to `adminItems`. The label-PDF reprint endpoint is left untouched (shared-team, used by the staff Stock page). Four existing staff-can-receive tests are inverted to lock in 403/redirect behavior.

**Tech Stack:** FastAPI + SQLModel (backend), pytest (backend tests), React + TanStack Router (frontend), Playwright (E2E).

**Spec:** `docs/superpowers/specs/2026-06-17-receive-admin-only-design.md`

---

## Order note

Do the **backend** task first (Task 1) so the inverted backend tests and the E2E API test agree on 403 before the frontend changes land. Then route guard (Task 2), then nav (Task 3), then E2E inversion (Task 4).

---

### Task 1: Backend — receive endpoints require admin

**Files:**
- Modify: `backend/app/api/routes/receipts.py:7` (import), `:19-34` (`receive_serialized`), `:37-56` (`receive_quantity`)
- Test: `backend/tests/api/routes/test_receipts_quantity.py:222-233` (invert), `backend/tests/api/routes/test_receipts_serialized.py:157-168` (invert)

- [ ] **Step 1: Invert the staff-can-receive tests to expect 403**

In `backend/tests/api/routes/test_receipts_quantity.py`, replace the body of `test_staff_can_receive_quantity` (rename for clarity):

```python
def test_staff_cannot_receive_quantity(
    client: TestClient,
    staff_token_headers: dict[str, str],
    seed_quantity_product: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    """Receiving is admin-only (reverses FR-005/006 D3); staff are forbidden."""
    product_id, supplier_id, _sku = seed_quantity_product
    resp = client.post(
        f"{PREFIX}/receipts/quantity",
        headers=staff_token_headers,
        json=_body(product_id, supplier_id),
    )
    assert resp.status_code == 403, resp.text
```

In `backend/tests/api/routes/test_receipts_serialized.py`, replace the body of `test_staff_can_receive_serialized` (rename to `test_staff_cannot_receive_serialized`). Read lines 157-182 first to copy the exact `_body`/request shape that file uses, then assert 403:

```python
def test_staff_cannot_receive_serialized(
    client: TestClient,
    staff_token_headers: dict[str, str],
    seed_serialized_product: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    """Receiving is admin-only (reverses FR-005/006 D3); staff are forbidden."""
    product_id, supplier_id, _sku = seed_serialized_product
    resp = client.post(
        f"{PREFIX}/receipts/serialized",
        headers=staff_token_headers,
        json=_body(product_id, supplier_id),
    )
    assert resp.status_code == 403, resp.text
```

Note: confirm the serialized test's fixture name and `_body` signature by reading the file before editing — match what is already there rather than assuming.

- [ ] **Step 2: Run the inverted tests to verify they FAIL**

Run: `cd backend && python -m pytest tests/api/routes/test_receipts_quantity.py::test_staff_cannot_receive_quantity tests/api/routes/test_receipts_serialized.py::test_staff_cannot_receive_serialized -v`
Expected: FAIL — staff currently get 200, not 403.

- [ ] **Step 3: Swap the backend dependency to AdminUser**

In `backend/app/api/routes/receipts.py`, change the import on line 7 from:

```python
from app.api.deps import CurrentUser, SessionDep, get_current_user
```

to:

```python
from app.api.deps import AdminUser, SessionDep, get_current_user
```

(`get_current_user` stays — it still guards `read_unit_label`.)

In `receive_serialized`, replace the `current_user: CurrentUser` parameter and its use:

```python
@router.post("/serialized", response_model=ReceiveSerializedResponse)
def receive_serialized(
    *,
    session: SessionDep,
    admin: AdminUser,
    payload: ReceiveSerializedRequest,
) -> ReceiveSerializedResponse:
    units = crud.receive_serialized(
        session=session,
        product_id=payload.product_id,
        supplier_id=payload.supplier_id,
        pieces=payload.pieces,
        idempotency_key=payload.idempotency_key,
        received_by_user_id=admin.id,
    )
    return ReceiveSerializedResponse(units=units)
```

In `receive_quantity`, do the same:

```python
@router.post("/quantity", response_model=PartBatchPublic)
def receive_quantity(
    *,
    session: SessionDep,
    admin: AdminUser,
    payload: ReceiveQuantityRequest,
) -> PartBatchPublic:
    batch = crud.receive_quantity(
        session=session,
        product_id=payload.product_id,
        supplier_id=payload.supplier_id,
        received_qty=payload.received_qty,
        purchase_cost_thb=payload.purchase_cost_thb,
        idempotency_key=payload.idempotency_key,
        received_by_user_id=admin.id,
        supplier_batch_ref=payload.supplier_batch_ref,
        expected_qty=payload.expected_qty,
        note=payload.note,
    )
    return PartBatchPublic.model_validate(batch)
```

Leave `read_unit_label` (the `/serialized/{unit_id}/label.pdf` endpoint) exactly as-is — it stays `Depends(get_current_user)`.

- [ ] **Step 4: Run the receipts test suites to verify all pass**

Run: `cd backend && python -m pytest tests/api/routes/test_receipts_quantity.py tests/api/routes/test_receipts_serialized.py -v`
Expected: PASS — staff get 403, superuser happy-paths still 200.

- [ ] **Step 5: mypy check**

Run: `cd backend && python -m mypy app/api/routes/receipts.py`
Expected: no errors (`get_current_user` still imported and used by `read_unit_label`; `CurrentUser` no longer referenced).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/receipts.py backend/tests/api/routes/test_receipts_quantity.py backend/tests/api/routes/test_receipts_serialized.py
git commit -m "feat(receive): require admin on receive endpoints; staff now 403"
```

---

### Task 2: Frontend route guard — /receive requires admin

**Files:**
- Modify: `frontend/src/routes/_layout/receive.tsx:51` (import), `:56` (`beforeLoad`)

- [ ] **Step 1: Swap the route guard import**

In `frontend/src/routes/_layout/receive.tsx`, change line 51 from:

```tsx
import { requireAuth } from "@/lib/route-guards"
```

to:

```tsx
import { requireAdmin } from "@/lib/route-guards"
```

- [ ] **Step 2: Swap the beforeLoad guard**

Change line 56 from:

```tsx
  beforeLoad: () => requireAuth(),
```

to:

```tsx
  beforeLoad: () => requireAdmin(),
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && bunx tsc --noEmit`
Expected: no errors (`requireAuth` no longer referenced in this file; `requireAdmin` is exported from `route-guards.ts`).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/_layout/receive.tsx
git commit -m "feat(receive): gate /receive route behind requireAdmin"
```

---

### Task 3: Frontend nav — move Receive into Operations

**Files:**
- Modify: `frontend/src/components/Sidebar/AppSidebar.tsx:53-66` (remove from Inventory), `:95-104` (add to Operations)

- [ ] **Step 1: Remove Receive from the Inventory (baseItems) group**

In `frontend/src/components/Sidebar/AppSidebar.tsx`, the Inventory block currently ends with the Receive entry. Replace the Inventory `items` so it contains only Stock and Low stock, and drop the receive-specific comment:

```tsx
  {
    icon: Boxes,
    title: "Inventory",
    items: [
      // Stock-on-hand + serial/SKU lookup: both roles, no cost fields (FR-012/015).
      { icon: Warehouse, title: "Stock", path: "/stock" },
      // Low-stock reorder list: both roles read, admin edits thresholds (FR-016).
      { icon: AlertTriangle, title: "Low stock", path: "/low-stock" },
    ],
  },
```

- [ ] **Step 2: Add Receive to the Operations (adminItems) group**

In the `Operations` block, add the Receive entry above `Adjust` and update the comment to reflect admin-only intake:

```tsx
  {
    icon: Settings2,
    title: "Operations",
    items: [
      // Receive: admin-only warehouse intake (FR-005/006; restricted from staff
      // 2026-06-17). Backend get_admin is the real gate.
      { icon: PackagePlus, title: "Receive", path: "/receive" },
      { icon: SlidersHorizontal, title: "Adjust", path: "/stock-adjustment" },
      // Pricing-override approval queue — admin decides PENDING deviations (FR-010).
      { icon: BadgePercent, title: "Overrides", path: "/pricing-overrides" },
      { icon: RefreshCw, title: "Sync review", path: "/sync-review" },
    ],
  },
```

(`PackagePlus` is already imported at the top of the file and is still used — no import change needed.)

- [ ] **Step 3: Typecheck and lint**

Run: `cd frontend && bunx tsc --noEmit && bunx biome check src/components/Sidebar/AppSidebar.tsx`
Expected: no errors, no orphaned imports.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Sidebar/AppSidebar.tsx
git commit -m "feat(receive): move Receive nav from Inventory to admin Operations"
```

---

### Task 4: E2E — invert staff access expectations

**Files:**
- Modify: `frontend/tests/receive.spec.ts:204-236` (API test → 403), `:239-255` (browser test → redirect)

- [ ] **Step 1: Invert the staff API test to expect rejection**

In `frontend/tests/receive.spec.ts`, replace `test("staff can receive over the receipts API", ...)` (lines 204-236) with a test that asserts the staff token is rejected. The generated SDK throws `ApiError` on non-2xx; assert each call rejects. Read the file's existing imports first — if `ApiError` is not already imported from `@/client`, add it to the existing import.

```ts
  test("staff cannot receive over the receipts API", async () => {
    const { email, password } = await seedStaffUser()
    const staffToken = await tokenFor(email, password)

    const serProduct = await seedProduct("SERIALIZED")
    const qtyProduct = await seedProduct("QUANTITY")
    const supplier = await seedSupplier()

    await withToken(staffToken, async () => {
      await expect(
        ReceiptsService.receiveSerialized({
          requestBody: {
            product_id: serProduct.id,
            supplier_id: supplier.id,
            idempotency_key: crypto.randomUUID(),
            pieces: [
              { supplier_serial: `SN-${suffix()}`, purchase_cost_thb: "100.00" },
            ],
          },
        }),
      ).rejects.toMatchObject({ status: 403 })

      await expect(
        ReceiptsService.receiveQuantity({
          requestBody: {
            product_id: qtyProduct.id,
            supplier_id: supplier.id,
            received_qty: 5,
            purchase_cost_thb: "10.00",
            idempotency_key: crypto.randomUUID(),
          },
        }),
      ).rejects.toMatchObject({ status: 403 })
    })
  })
```

Note: confirm the thrown error shape exposes `status` (the hey-api `ApiError` does). If the suite's existing error assertions use a different property, match that convention instead.

- [ ] **Step 2: Invert the staff browser test to expect redirect**

Replace the `test.describe("Receive screen access control (staff browser)", ...)` block (lines 239-255) so staff are redirected to `/` by `requireAdmin()`:

```ts
test.describe("Receive screen access control (staff browser)", () => {
  // Fresh browser context, NOT the superuser storageState — log in as a staff
  // user in the UI so the requireAdmin guard redirects them away from Receive
  // (admin-only intake, restricted 2026-06-17).
  test.use({ storageState: { cookies: [], origins: [] } })

  test("staff are redirected away from /receive", async ({ page }) => {
    const { email, password } = await seedStaffUser()
    await logInUser(page, email, password)
    await page.goto("/receive")
    // requireAdmin redirects non-admins to "/".
    await expect.poll(() => new URL(page.url()).pathname).toBe("/")
    await expect(
      page.getByRole("heading", { name: "Receive stock" }),
    ).toBeHidden()
  })
})
```

- [ ] **Step 3: Run the receive E2E spec**

Run: `cd frontend && bun run test tests/receive.spec.ts`
Expected: PASS — admin happy-paths (serialized + quantity receive) still pass; staff API call rejects with 403; staff browser is redirected to `/`.

Note: the E2E suite uses a shared dev DB and serial workers (see memory `e2e-shared-dev-db-pitfalls`). If the run errors on seeding/superuser, reseed and retry rather than assuming a code failure.

- [ ] **Step 4: Commit**

```bash
git add frontend/tests/receive.spec.ts
git commit -m "test(receive): staff are forbidden (403) and redirected from /receive"
```

---

### Task 5: Full verification + review

- [ ] **Step 1: Backend suite**

Run: `cd backend && bash ../scripts/test.sh` (or `python -m pytest`)
Expected: green.

- [ ] **Step 2: Frontend lint/typecheck**

Run: `cd frontend && bunx tsc --noEmit && bunx biome check src tests`
Expected: green.

- [ ] **Step 3: Security review (auth-boundary change)**

Dispatch `ecc:security-reviewer` (model: opus) on the diff in `backend/app/api/routes/receipts.py` and `frontend/src/routes/_layout/receive.tsx`, focusing on: (a) no receive path still reachable by staff, (b) the label-PDF endpoint intentionally remaining shared-team is correct, (c) the route guard cannot be bypassed client-side (backend is the real gate).

- [ ] **Step 4: Address any findings, then open PR**

Per CLAUDE.md stage 6: branch → PR into `dev` (never `master`), one scoped feature.

---

## Self-Review

- **Spec coverage:** Nav move (Task 3), route guard (Task 2), backend dep (Task 1), label-PDF left untouched (Task 1 Step 3 explicit), 4 tests inverted (Tasks 1 & 4), no SDK regen (no schema change — confirmed, not in any task). All spec sections covered.
- **Placeholder scan:** No TBD/TODO; every code step shows full code; commands have expected output.
- **Type consistency:** `AdminUser`/`admin.id` consistent across both endpoints; `requireAdmin` matches `route-guards.ts` export; `PackagePlus` already imported; `ReceiptsService` method names (`receiveSerialized`, `receiveQuantity`) match existing usage in the spec file.
- **Caveat flagged inline:** serialized test fixture/`_body` shape and the E2E `ApiError.status` property must be confirmed against the actual files before editing (noted in Task 1 Step 1 and Task 4 Step 1).
