# Restore Staff Receiving — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Receive screen + `/receipts/*` API accessible to `YGN_STAFF` (staff + admin), reverting the admin-only gating that Part 5.3 D4 introduced in error.

**Architecture:** Drop the `get_admin` dependency on the three receipts routes (back to `CurrentUser` = any authenticated active user), flip the frontend route guard + nav, and flip the role tests to assert staff *can* receive. Cost-redaction on sales/reports/dashboards/budgets is independent and untouched.

**Tech Stack:** FastAPI + SQLModel + pytest (backend); React + TanStack Router + Playwright (frontend).

**Design spec:** `docs/superpowers/specs/2026-06-09-castranova-staff-receiving-design.md` (read it first).

**Risk note:** This is a **role-tiering change → high-risk per CLAUDE.md §5**. The review gate (end of plan) MUST include `ecc:security-reviewer` in addition to `@superpowers:requesting-code-review` + `ecc:react-reviewer`. `ecc:database-reviewer` is not required (no schema/SQL change).

**Branch:** `fix/5.3-staff-receiving` (already created off `dev`).

---

## File Structure

- Modify: `backend/app/api/routes/receipts.py` — remove the admin gate from 3 routes.
- Modify: `backend/tests/api/routes/test_receipts_serialized.py` — flip 2 staff tests + add a 401 test.
- Modify: `backend/tests/api/routes/test_receipts_quantity.py` — flip 1 staff test + add a 401 test.
- Modify: `frontend/src/routes/_layout/receive.tsx` — `requireAdmin` → `requireAuth`.
- Modify: `frontend/src/components/Sidebar/AppSidebar.tsx` — move Receive to `baseItems`.
- Modify: `frontend/tests/receive.spec.ts` — flip 2 role tests (staff can receive; staff reaches `/receive`).
- Modify: `docs/superpowers/specs/2026-06-07-castranova-5.3-frontend-screens-design.md` — mark D4 superseded.

---

## Task 1: Backend — staff can receive (TDD)

**Files:**
- Modify: `backend/tests/api/routes/test_receipts_serialized.py:156-176`
- Modify: `backend/tests/api/routes/test_receipts_quantity.py:222-230`
- Modify: `backend/app/api/routes/receipts.py:6,18,36,58-60`

- [ ] **Step 1: Flip the serialized staff tests (write failing tests first)**

In `backend/tests/api/routes/test_receipts_serialized.py`, replace the two tests `test_staff_cannot_receive_serialized` and `test_staff_cannot_fetch_unit_label` (lines 156-176) with:

```python
def test_staff_can_receive_serialized(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
    seed_product_supplier: tuple[uuid.UUID, uuid.UUID],
) -> None:
    product_id, supplier_id = seed_product_supplier
    resp = client.post(
        f"{PREFIX}/receipts/serialized",
        headers=staff_token_headers,
        json=_body(product_id, supplier_id),
    )
    assert resp.status_code == 200, resp.text


def test_staff_can_fetch_unit_label(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
    seed_product_supplier: tuple[uuid.UUID, uuid.UUID],
) -> None:
    product_id, supplier_id = seed_product_supplier
    recv = client.post(
        f"{PREFIX}/receipts/serialized",
        headers=staff_token_headers,
        json=_body(product_id, supplier_id),
    )
    assert recv.status_code == 200, recv.text
    unit_id = recv.json()["units"][0]["id"]
    resp = client.get(
        f"{PREFIX}/receipts/serialized/{unit_id}/label.pdf",
        headers=staff_token_headers,
    )
    assert resp.status_code == 200
    assert resp.content[:4] == b"%PDF"


def test_unauthenticated_cannot_receive_serialized(client: TestClient) -> None:
    resp = client.post(f"{PREFIX}/receipts/serialized", json={})
    assert resp.status_code == 401
```

- [ ] **Step 2: Flip the quantity staff test**

In `backend/tests/api/routes/test_receipts_quantity.py`, replace `test_staff_cannot_receive_quantity` (lines 222-230) with:

```python
def test_staff_can_receive_quantity(
    client: TestClient,
    staff_token_headers: dict[str, str],
    db: Session,
    seed_quantity_product: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    product_id, supplier_id, _sku = seed_quantity_product
    resp = client.post(
        f"{PREFIX}/receipts/quantity",
        headers=staff_token_headers,
        json=_body(product_id, supplier_id),
    )
    assert resp.status_code == 200, resp.text


def test_unauthenticated_cannot_receive_quantity(client: TestClient) -> None:
    resp = client.post(f"{PREFIX}/receipts/quantity", json={})
    assert resp.status_code == 401
```

- [ ] **Step 3: Run the flipped tests — verify they FAIL**

Run: `cd backend && uv run pytest tests/api/routes/test_receipts_serialized.py tests/api/routes/test_receipts_quantity.py -k "staff_can or unauthenticated" -v`
Expected: the `staff_can_*` tests FAIL with `403` (the admin gate still fires). The `unauthenticated_*` tests should already PASS (401).

- [ ] **Step 4: Remove the admin gate from the receipts routes**

In `backend/app/api/routes/receipts.py`:

1. Delete `dependencies=[Depends(get_admin)]` from all three decorators:
   - `@router.post("/serialized", response_model=ReceiveSerializedResponse, dependencies=[Depends(get_admin)])` → `@router.post("/serialized", response_model=ReceiveSerializedResponse)`
   - `@router.post("/quantity", response_model=PartBatchPublic, dependencies=[Depends(get_admin)])` → `@router.post("/quantity", response_model=PartBatchPublic)`
   - the label route `@router.get(...)` block — remove the `dependencies=[Depends(get_admin)],` line.
2. Update the import on line 6: `from app.api.deps import CurrentUser, SessionDep, get_admin` → `from app.api.deps import CurrentUser, SessionDep`.
3. If `Depends` is now unused in the file, remove it from the `fastapi` import (`from fastapi import APIRouter, Depends, HTTPException, Response` → drop `Depends`). Verify with `grep -n "Depends" backend/app/api/routes/receipts.py` — if no matches remain, remove it.

Keep the route bodies untouched (they still set `received_by_user_id`/`created_by_user_id` from `current_user`).

- [ ] **Step 5: Run to verify the flipped tests PASS + no regression**

Run: `cd backend && uv run pytest tests/api/routes/test_receipts_serialized.py tests/api/routes/test_receipts_quantity.py -v`
Expected: all PASS (staff can receive + fetch label; admin still works; unauthenticated 401).

- [ ] **Step 6: Full backend suite + lint/type**

Run: `cd backend && uv run pytest -q && uv run ruff check . && uv run mypy app`
Expected: all green, ruff + mypy clean.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/routes/receipts.py backend/tests/api/routes/test_receipts_serialized.py backend/tests/api/routes/test_receipts_quantity.py
git commit -m "feat(receipts): allow staff to receive (revert admin-only gate, D4)"
```

---

## Task 2: Frontend — staff route guard + nav

**Files:**
- Modify: `frontend/src/routes/_layout/receive.tsx:48,52`
- Modify: `frontend/src/components/Sidebar/AppSidebar.tsx`

- [ ] **Step 1: Loosen the route guard**

In `frontend/src/routes/_layout/receive.tsx`:
- Change the import: `import { requireAdmin } from "@/lib/route-guards"` → `import { requireAuth } from "@/lib/route-guards"`.
- Change the guard: `beforeLoad: () => requireAdmin(),` → `beforeLoad: () => requireAuth(),`.

- [ ] **Step 2: Move Receive into the base (staff + admin) nav**

In `frontend/src/components/Sidebar/AppSidebar.tsx`, move the Receive entry from `adminItems` to `baseItems`. The result:

```tsx
const baseItems: Item[] = [
  { icon: Home, title: "Dashboard", path: "/" },
  { icon: ShoppingCart, title: "Sale", path: "/sale" },
  // Receive: staff + admin (YGN warehouse intake, FR-005/006). Staff enter the
  // supplier purchase cost off the delivery invoice; sales COGS/margin stay
  // redacted. Backend authorizes both roles.
  { icon: PackagePlus, title: "Receive", path: "/receive" },
]

const adminItems: Item[] = [
  { icon: Users, title: "Admin", path: "/admin" },
]
```

Leave the `isAdmin` gating of `adminItems` and the `useRole()` usage exactly as-is (Admin stays admin-only). Keep all four icon imports.

- [ ] **Step 3: Verify build + lint + types**

Run: `cd frontend && bunx tsc --noEmit && bunx biome check src && bun run build`
Expected: tsc exit 0, biome clean, build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/_layout/receive.tsx frontend/src/components/Sidebar/AppSidebar.tsx
git commit -m "feat(receive): staff can reach Receive (guard + nav)"
```

---

## Task 3: E2E — flip the role tests

**Files:**
- Modify: `frontend/tests/receive.spec.ts`

- [ ] **Step 1: Flip the receipts-API role test to assert staff CAN receive**

In `frontend/tests/receive.spec.ts`, find the test titled `"staff is forbidden from the receipts API (403)"` and replace it with a test that asserts staff succeed. Keep the existing helpers (`seedStaffUser`, `tokenFor`, `withToken`, `seedProduct`, `seedSupplier`):

```ts
  test("staff can receive over the receipts API", async () => {
    const { email, password } = await seedStaffUser()
    const staffToken = await tokenFor(email, password)

    const serProduct = await seedProduct("SERIALIZED")
    const qtyProduct = await seedProduct("QUANTITY")
    const supplier = await seedSupplier()

    await withToken(staffToken, async () => {
      const ser = await ReceiptsService.receiveSerialized({
        requestBody: {
          product_id: serProduct.id,
          supplier_id: supplier.id,
          idempotency_key: crypto.randomUUID(),
          pieces: [{ supplier_serial: `SN-${suffix()}`, purchase_cost_thb: "100.00" }],
        },
      })
      expect(ser.units.length).toBe(1)

      const batch = await ReceiptsService.receiveQuantity({
        requestBody: {
          product_id: qtyProduct.id,
          supplier_id: supplier.id,
          received_qty: 5,
          purchase_cost_thb: "10.00",
          idempotency_key: crypto.randomUUID(),
        },
      })
      expect(batch.received_qty).toBe(5)
    })
  })
```

(Remove the now-unused `statusOf` helper only if nothing else in the file uses it — `grep -n statusOf frontend/tests/receive.spec.ts` first.)

- [ ] **Step 2: Flip the staff-browser test to assert staff REACHES /receive**

In the staff-browser `test.describe` block, find the test asserting staff is redirected away from `/receive` and replace its body so it asserts staff reaches the screen:

```ts
    await logInUser(page, email, password)
    await page.goto("/receive")
    // Staff can now reach Receive (YGN warehouse intake).
    await expect(
      page.getByRole("heading", { name: "Receive stock" }),
    ).toBeVisible()
    expect(new URL(page.url()).pathname).toBe("/receive")
```

(Keep the surrounding context setup — fresh `storageState`, `seedStaffUser`, `logInUser` — unchanged.)

- [ ] **Step 3: Run the receive E2E (needs a current backend)**

Ensure the dev backend is current: `docker compose up -d --build backend` then reseed (`docker compose up -d prestart`).
Run: `cd frontend && bunx playwright test receive.spec.ts --workers=1`
Expected: all receive tests PASS (staff can receive + reaches /receive; admin paths still pass).

- [ ] **Step 4: Full suite green**

Run: `cd frontend && bunx playwright test --workers=1`
Expected: 0 failed (the only remaining skip is the Phase-3 offline-sale-replay fixme).

- [ ] **Step 5: Commit**

```bash
git add frontend/tests/receive.spec.ts
git commit -m "test(e2e): assert staff can receive + reach /receive"
```

---

## Task 4: Docs — record D4 as superseded

**Files:**
- Modify: `docs/superpowers/specs/2026-06-07-castranova-5.3-frontend-screens-design.md`

- [ ] **Step 1: Annotate D4 and §4.3**

In `docs/superpowers/specs/2026-06-07-castranova-5.3-frontend-screens-design.md`:
- In the §2 decisions table, append to the **D4** row's Rationale cell: `**SUPERSEDED 2026-06-09** — staff receive per FR-005/006; see docs/superpowers/specs/2026-06-09-castranova-staff-receiving-design.md.`
- At the top of §4.3 (Receive → admin-only), add a one-line note: `> **Superseded 2026-06-09:** receiving is staff + admin (revert D4). The redaction concern was sales COGS/margin, not the supplier purchase cost staff enter at receive.`

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-06-07-castranova-5.3-frontend-screens-design.md
git commit -m "docs(5.3): mark D4 (Receive admin-only) superseded by staff-receiving"
```

---

## Review gate (high-risk: role-tiering)

Run `@superpowers:requesting-code-review`, **plus** dispatch `ecc:security-reviewer` (Agent tool) — confirm the role change exposes no cost/margin beyond the staff's own receive input, and no other endpoint lost its gate. Also run `ecc:react-reviewer` for the frontend guard/nav change. Address findings, then open the PR (`@create-pr`) into `dev`. Verify before PR: `cd backend && uv run pytest -q && uv run ruff check . && uv run mypy app` clean; `cd frontend && bunx tsc --noEmit && bunx biome check src tests && bunx playwright test --workers=1` green.

---

## Definition of Done

- Staff token receives serialized + quantity and fetches the unit label (success); unauthenticated → 401.
- Receive reachable by staff in nav + route; admin still reaches it.
- Backend pytest + frontend Playwright green; ruff + mypy + biome + tsc clean.
- Sales COGS/margin, stock/batch cost, project budgets remain redacted from staff (no regression).
- Part 5.3 D4 recorded as superseded.
