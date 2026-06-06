# CastraNova 5.3 — Frontend Screens, Role-Shells & Redaction — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the four operational inventory screens (Receive, Sale, Service-Ticket, Project-Pull) with admin/staff role-shells, an offline indicator + queue counter, and the backend Sale-redaction slice that lets the DoD's "staff see no financial fields over raw HTTP" hold — thereby unblocking Part 5.2 browser E2E.

**Architecture:** Thin role-guarded TanStack file-routes over shared primitives (`useRole`, `useScanLookup`, `ScanCart`), data via the generated SDK + TanStack Query. Backend adds two staff Sale schema variants + role dispatch, and gates `/receipts/*` to admin. Industrial-utilitarian dark theme (Fira Code/Sans) layered on existing shadcn primitives.

**Tech Stack:** FastAPI + SQLModel (backend); React + TS + Vite + TanStack Router/Query + shadcn/ui + Tailwind v4 + react-hook-form + zod (frontend); pytest + Playwright (tests); `@hey-api/openapi-ts` SDK.

**Design spec:** `docs/superpowers/specs/2026-06-07-castranova-5.3-frontend-screens-design.md` (read it before starting — it carries the decisions, role matrix, and rationale).

**Conventions:** Each phase is its own branch + PR (never push to `master`). Inside each task: TDD (@superpowers:test-driven-development), frequent commits. Phase 1 is high-risk (money/redaction) — its review **must** include `ecc:database-reviewer` + `ecc:security-reviewer` in addition to `@superpowers:requesting-code-review`.

**Granularity note:** Phases 1–2 are fully bite-sized below. Phases 3–7 are structured task outlines with explicit acceptance criteria; expand each into bite-sized steps (per this skill) when you reach it, since several screen interactions depend on the prior phase's primitives existing.

---

## Phase 1 — Backend Sale redaction + Receive admin-gating

**Branch:** `feat/5.3-phase1-sale-redaction`

Audit result (from the spec): the ONLY staff-reachable endpoint leaking cost is Sale. Tickets/pulls carry no cost fields; dashboards already exclude cost; receipts become admin-only here.

### Task 1.1: Staff Sale schemas

**Files:**
- Modify: `backend/app/models.py` (after `SalePublic`, ~line 1124)

**Step 1: Write the failing test**

`backend/tests/api/routes/test_sale_redaction.py`:

```python
import uuid
from fastapi.testclient import TestClient

# Reuse existing seeding helpers from the serialized-sale test module.
from tests.api.routes.test_sales_serialized import _seed_unit_in_stock  # adjust to actual helper name


def test_staff_sale_response_omits_cost_fields(
    client: TestClient, staff_token_headers: dict[str, str]
) -> None:
    customer_id, barcode = _seed_unit_in_stock(client)  # admin-seeded fixture data
    resp = client.post(
        "/api/v1/sales",
        headers=staff_token_headers,
        json={
            "customer_id": str(customer_id),
            "idempotency_key": str(uuid.uuid4()),
            "lines": [{"line_kind": "UNIT", "castranova_barcode": barcode, "quantity": 1}],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # DoD: financial fields absent over raw HTTP for staff.
    assert "total_cogs_thb" not in body
    assert all("unit_cost_thb" not in line for line in body["lines"])
    # Selling price still present.
    assert "total_thb" in body


def test_admin_sale_response_includes_cost_fields(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    customer_id, barcode = _seed_unit_in_stock(client)
    resp = client.post(
        "/api/v1/sales",
        headers=superuser_token_headers,
        json={
            "customer_id": str(customer_id),
            "idempotency_key": str(uuid.uuid4()),
            "lines": [{"line_kind": "UNIT", "castranova_barcode": barcode, "quantity": 1}],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "total_cogs_thb" in body
    assert all("unit_cost_thb" in line for line in body["lines"])
```

> Before writing, open `backend/tests/api/routes/test_sales_serialized.py` and reuse its real seeding helper/fixtures (customer, supplier, received serialized unit). Match the actual helper names — the names above are placeholders.

**Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/api/routes/test_sale_redaction.py -v`
Expected: FAIL (staff response still contains `total_cogs_thb`).

**Step 3: Add the staff schemas**

In `backend/app/models.py`, immediately after `SalePublic`:

```python
class SaleLineStaffPublic(SQLModel):
    id: uuid.UUID
    line_kind: SaleLineKind
    unit_id: uuid.UUID | None
    product_id: uuid.UUID | None
    quantity: int
    unit_price_thb: Decimal
    # no unit_cost_thb — redacted for staff (FR / DoD §9)


class SaleStaffPublic(SQLModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    total_thb: Decimal
    sold_at: datetime
    lines: list[SaleLineStaffPublic]
    # no total_cogs_thb — redacted for staff
```

**Step 4: Run mypy**

Run: `cd backend && uv run mypy app`
Expected: clean.

**Step 5: Commit**

```bash
git add backend/app/models.py backend/tests/api/routes/test_sale_redaction.py
git commit -m "test(sales): add staff Sale redaction schemas + failing tests"
```

### Task 1.2: Role-dispatch in the sales route

**Files:**
- Modify: `backend/app/api/routes/sales.py:1-53`

**Step 1: Make `_to_public` role-aware and branch on the caller**

Replace the imports + `_to_public` + `create_sale` return annotation:

```python
from app.models import (
    Sale,
    SaleCreateRequest,
    SaleLine,
    SaleLinePublic,
    SaleLineStaffPublic,
    SalePublic,
    SaleStaffPublic,
)
from app.models import User, UserRole  # if not already imported


def _is_admin(user: User) -> bool:
    return user.is_superuser or user.role == UserRole.BKK_ADMIN


def _to_public(
    *, session: SessionDep, sale: Sale, user: User
) -> SalePublic | SaleStaffPublic:
    lines = session.exec(select(SaleLine).where(SaleLine.sale_id == sale.id)).all()
    if _is_admin(user):
        return SalePublic(
            id=sale.id,
            customer_id=sale.customer_id,
            total_thb=sale.total_thb,
            total_cogs_thb=sale.total_cogs_thb,
            sold_at=sale.sold_at,
            lines=[SaleLinePublic.model_validate(line) for line in lines],
        )
    return SaleStaffPublic(
        id=sale.id,
        customer_id=sale.customer_id,
        total_thb=sale.total_thb,
        sold_at=sale.sold_at,
        lines=[SaleLineStaffPublic.model_validate(line) for line in lines],
    )
```

Change `create_sale` to drop the fixed `response_model=SalePublic` decorator arg and use the union return annotation so FastAPI infers it, and pass `user=current_user`:

```python
@router.post("")
def create_sale(
    *, session: SessionDep, current_user: CurrentUser,
    background_tasks: BackgroundTasks, payload: SaleCreateRequest,
) -> SalePublic | SaleStaffPublic:
    ...
    return _to_public(session=session, sale=sale, user=current_user)
```

Do the same for the `read_sale_receipt` JSON path if it returns `_to_public` (the `receipt.pdf` route is separate — see Task 1.4).

**Step 2: Run the Task 1.1 tests**

Run: `cd backend && uv run pytest tests/api/routes/test_sale_redaction.py -v`
Expected: PASS (both staff-omits and admin-includes).

**Step 3: Run the existing sales suites (no regressions)**

Run: `cd backend && uv run pytest tests/api/routes/test_sales_serialized.py tests/api/routes/test_sales_part.py -v`
Expected: PASS. If an existing test asserted `total_cogs_thb` using a staff/normal-user token, update it to use `superuser_token_headers` (cost is admin-only now) — note any such change in the commit.

**Step 4: Commit**

```bash
git add backend/app/api/routes/sales.py backend/tests
git commit -m "feat(sales): role-dispatch Sale response, redact cost/COGS for staff"
```

### Task 1.3: Receive → admin-only

**Files:**
- Modify: `backend/app/api/routes/receipts.py` (the two POST routes + label route)

**Step 1: Write failing 403 tests**

Add to `backend/tests/api/routes/test_receipts_quantity.py` (and the serialized receipts test module):

```python
def test_staff_cannot_receive_quantity(
    client: TestClient, staff_token_headers: dict[str, str]
) -> None:
    resp = client.post("/api/v1/receipts/quantity", headers=staff_token_headers, json={})
    assert resp.status_code == 403
```

(Add the equivalent for `/receipts/serialized` and the label route.)

**Step 2: Run to verify fail**

Run: `cd backend && uv run pytest tests/api/routes/test_receipts_quantity.py -k staff_cannot -v`
Expected: FAIL (currently 422/200, not 403).

**Step 3: Gate the routes**

Add `dependencies=[Depends(get_admin)]` to each `@router.post(...)`/label `@router.get(...)` decorator in `receipts.py`, importing `get_admin` from `app.api.deps`. Keep `current_user: CurrentUser` params (used for `created_by_user_id`).

**Step 4: Run to verify pass + no regression**

Run: `cd backend && uv run pytest tests/api/routes/ -k receipt -v`
Expected: PASS. Existing admin/normal-user receive tests must now use an admin token — update any that used a non-admin token and note it.

**Step 5: Commit**

```bash
git add backend/app/api/routes/receipts.py backend/tests
git commit -m "feat(receipts): gate receive endpoints to admin (cost entry is admin-only)"
```

### Task 1.4: receipt.pdf cost check + comment cleanup

**Files:**
- Verify: `backend/app/services/receipt_pdf.py`
- Modify: `backend/app/api/routes/project_pulls.py:81` (stale comment)

**Step 1:** Inspect `render_sale_receipt`; confirm the customer receipt PDF renders selling price only (no cost/COGS). Add a test that fetches `/sales/{id}/receipt.pdf` as staff and asserts 200 + (if text-extractable) no cost string. If the PDF *does* embed cost, redact it there too (treat as a found bug, write the failing test first).

**Step 2:** Fix the `project_pulls.py:81` comment to state that staff fulfilment is intentional per the role matrix (not "deferred to Part 4").

**Step 3: Commit**

```bash
git add backend/app backend/tests
git commit -m "test(sales): assert receipt.pdf carries no cost; fix stale pull comment"
```

### Task 1.5: Regenerate the SDK

**Step 1:** With the backend running (`docker compose up -d backend`), run `cd frontend && bun run generate-client`.

**Step 2:** Confirm only `src/client/*.gen.ts` changed and that `SaleStaffPublic`/`SaleLineStaffPublic` (or an optional-cost union) appear. Resolve the §11 open question: if the union is awkward to consume, fall back to a single Public with `unit_cost_thb`/`total_cogs_thb` as `Optional` (still backend-redacted) and re-gen.

**Step 3: Commit**

```bash
git add frontend/src/client
git commit -m "chore(sdk): regenerate client for staff-redacted Sale schema"
```

### Phase 1 review gate

Run `@superpowers:requesting-code-review`, **plus** dispatch `ecc:database-reviewer` and `ecc:security-reviewer` (Agent tool). Address findings, then open the PR (`@create-pr`). Verify `uv run ruff check . && uv run mypy app` clean and the full backend suite passes (`bash scripts/test.sh` or `cd backend && uv run pytest`).

---

## Phase 2 — Frontend foundation (theme, role, scan, offline counter)

**Branch:** `feat/5.3-phase2-foundation`

No screens yet — just the shared infrastructure every screen depends on.

### Task 2.1: Fonts + theme tokens

**Files:**
- Modify: `frontend/index.html` (font `<link>` or self-host), `frontend/src/index.css` (Tailwind v4 `@theme` tokens)

**Steps:** Add Fira Code + Fira Sans; set `--font-sans: "Fira Sans"`, `--font-mono: "Fira Code"`; introduce the data-dense dark palette tokens (primary `#3B82F6`, CTA accent `#F97316`, success/warn/bad) within the existing shadcn token structure; add a `.num` tabular-numeric utility. Keep light mode functional.
**Acceptance:** app builds (`bun run build`), existing pages render with the new fonts, dark + light both legible (contrast ≥ 4.5:1). Run the existing E2E suite — must stay green (46 passed).
**Commit** per logical step.

### Task 2.2: `useRole` hook

**Files:** Create `frontend/src/hooks/useRole.ts`; Test: `frontend/tests/useRole.spec.ts` (pure-logic, like `scanner.spec.ts`).
**Behavior:** `{ isAdmin: user.is_superuser || user.role === "BKK_ADMIN", isStaff: user.role === "YGN_STAFF", role }` from `useAuth()`.
**TDD:** test the predicate logic for each role + superuser. **Commit.**

### Task 2.3: Route-guard helpers

**Files:** Create `frontend/src/lib/route-guards.ts` (`requireAdmin`, `requireAuth` for TanStack `beforeLoad`), mirroring `admin.tsx`'s `readUserMe` + `redirect` pattern.
**Acceptance:** `requireAdmin` redirects non-admin to `/`; `requireAuth` redirects logged-out to `/login`. **Commit.**

### Task 2.4: `useScanLookup` hook

**Files:** Create `frontend/src/hooks/useScanLookup.ts`; compose existing `useScanner` + `SearchService.searchSerial`/`searchSku` + `CameraScanFallback`. Returns `{ resolved, isSearching, notFound }`; auto-focus + re-focus the scan field.
**TDD:** mock the SDK; test serial vs SKU dispatch and not-found. **Commit.**

### Task 2.5: OfflineIndicator + queue counter

**Files:** Modify `frontend/src/components/OfflineIndicator.tsx`.
**Behavior:** `useMutationState({ filters: { predicate: (m) => m.state.isPaused } })` → show "N queued"; announce transitions via `aria-live="polite"`. (Confirmed TanStack pattern.)
**Acceptance:** offline → queued sale increments the badge; reconnect → drains. Covered properly by E2E in Phase 3. **Commit.**

### Phase 2 review gate

`@superpowers:requesting-code-review` + `ecc:react-reviewer`. Re-run existing E2E suite (still 46 passing). PR.

---

## Phase 3 — Sale / POS screen  *(unblocks 5.2 sale online + offline replay)*

**Branch:** `feat/5.3-phase3-sale`

**Build:** `frontend/src/routes/_layout/sale.tsx` (guard `requireAuth`) + `frontend/src/components/pos/ScanCart.tsx`. Responsive two-pane → single-column + sticky checkout (spec §6.1). `SalesService.createSale` with client `idempotency_key`; offline-capable (mutation default already wired). Cost columns only when `useRole().isAdmin`. Sidebar nav entry.

**Acceptance / tests:**
- Component test: `ScanCart` assembles the correct `SaleCreateRequest` payload; cost columns hidden for staff.
- E2E (write now, runs under 5.2 banner): **sale online** (scan UNIT → complete → unit becomes SOLD); **sale offline → reload → reconnect → replay** asserts exactly one sale (idempotency) and the queue counter behavior.
- a11y: scan auto-focus, `aria-live` cart/scan announcements, 44px targets, focus rings.

**Review:** `ecc:react-reviewer` + `@superpowers:requesting-code-review`. PR.

---

## Phase 4 — Receive screen (admin-only)  *(unblocks 5.2 receive serial+qty)*

**Branch:** `feat/5.3-phase4-receive`

**Build:** `frontend/src/routes/_layout/receive.tsx` (guard `requireAdmin`) with Serialized + Quantity tabs (spec §6.2); supplier + `purchase_cost_thb` capture; `ReceiptsService.receiveSerialized`/`receiveQuantity` with `idempotency_key`; serialized label PDF link. Offline-capable.

**Acceptance / tests:** E2E receive serialized (per-piece) + quantity (batch); replay same `idempotency_key` → no duplicate. Staff → route redirect + backend 403 (role E2E). **Review:** `ecc:react-reviewer`. PR.

---

## Phase 5 — Service-ticket screen  *(unblocks 5.2 ticket close)*

**Branch:** `feat/5.3-phase5-tickets`

**Build:** `frontend/src/routes/_layout/tickets.tsx` (guard `requireAuth`): open (customer + issue) → add parts (scan SKU, price only) → close (spec §6.3). `ServiceTicketsService.*`. Online-only.

**Acceptance / tests:** E2E open → add part → close (assert `closed_at` set); re-close idempotent. No cost field anywhere. **Review:** `ecc:react-reviewer`. PR.

---

## Phase 6 — Project-pull screen  *(unblocks 5.2 pull fulfill with short)*

**Branch:** `feat/5.3-phase6-pulls`

**Build:** `frontend/src/routes/_layout/pulls.tsx` (fulfill: `requireAuth`; create/cancel buttons admin-only). List by state; fulfill = checklist vs requested lines; SHORT badge on partial (spec §6.4). `ProjectPullsService.fulfillProjectPull`. Online-only.
**Resolve here:** the §11 open question — concrete UNIT-line scan-vs-checklist interaction for serialized pull lines.

**Acceptance / tests:** E2E fulfill full → `FULFILLED`; fulfill partial (request > stock) → line + pull `SHORT` with badge. **Review:** `ecc:react-reviewer`. PR.

---

## Phase 7 — Role-shell polish + close-out

**Branch:** `feat/5.3-phase7-roleshell`

**Build:** finalize `AppSidebar.tsx` role-filtered nav (spec §6.5: staff = Dashboard/Sale/Tickets/Pulls; admin += Receive/Admin); final role + redaction E2E (staff blocked from `/receive`; cost absent in DOM *and* raw HTTP). Update `docs/plans/2026-06-04-castranova-pos-implementation.md`: mark 5.3 ✅ and 5.2 unblocked/done; close the Sale half of the `deferred-security-hardening` memory note.

**Acceptance:** full E2E suite green incl. the five 5.2 paths; biome + tsc + ruff + mypy clean. **Review:** `@superpowers:requesting-code-review` + `ecc:security-reviewer`. PR.

---

## Definition of Done (this plan)

- Phase 1 pytest proves staff Sale JSON omits cost/COGS (raw HTTP) and `/receipts/*` 403s for staff.
- Four screens reachable per the role matrix; cost hidden from staff in UI and payload.
- Offline sale survives reload + replays once; queue counter visible.
- The five 5.2 Playwright paths pass.
- `uv run ruff check . && uv run mypy app` clean; biome + tsc clean; pre-commit passes.
