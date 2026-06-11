# CodeRabbit Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 4 verified-real CodeRabbit findings — 3 missing DB constraints (saleline qty, product prices, systemsetting FK) via a new migration `m027`, and the `tickets.tsx` orphan-ticket / idempotency-key bug.

**Architecture:** Backend constraints are declared in **both** `models.py` (ORM truth) and an additive migration `m027` (matches the repo's m021/m024/m025 hardening convention — no edit-in-place, no DB reset). Frontend reuses one idempotency key across retries (via `useRef`) and wraps the open→parts→close flow in try/catch; there is no backend cancel endpoint, so a failure surfaces a clear error instead of silently orphaning.

**Tech Stack:** FastAPI / SQLModel / Alembic / psycopg3 / pytest (backend); React + TS / TanStack Query / Playwright (frontend).

**Spec:** `docs/superpowers/specs/2026-06-12-coderabbit-remediation-design.md`

**Risk tier:** HIGH — touches money (`saleline`, `product` prices) and an append-only domain. CLAUDE.md mandates stages 3–5 + `ecc:database-reviewer` + `ecc:security-reviewer` before PR (Task 3).

---

## File Structure

| File | Change | Responsibility |
|------|--------|----------------|
| `backend/app/models.py` | Modify | Add CHECK constraints to `SaleLine` (#5) and `Product` (#6) `__table_args__`; add `ondelete="SET NULL"` to `SystemSetting.updated_by_user_id` FK (#7). |
| `backend/app/alembic/versions/<rev>_m027_constraint_hardening.py` | Create | Forward migration adding the 3 CHECKs + recreating the systemsetting FK with `ON DELETE SET NULL`. |
| `backend/tests/crud/test_constraints_m027.py` | Create | DB-level integrity tests for #5/#6/#7. |
| `frontend/src/routes/_layout/tickets.tsx` | Modify | Reuse idempotency key across retries (`useRef`), reset on success; wrap `submitTicket` in try/catch with a clear failure message. |
| `frontend/tests/tickets.spec.ts` | Modify | E2E: force first part-add to fail, retry, assert same `idempotency_key` + a single ticket created. |

**Prerequisites for all backend steps:** the dev stack must be running so a Postgres test DB exists. Start with `docker compose watch` (or `docker compose up -d db`). Backend commands below run inside the backend container via `docker compose exec backend …`; if you run the suite host-side instead, use `cd backend && uv run …` with `scripts/test.sh` having prepared the DB.

---

## Task 1: Backend constraints (#5, #6, #7) — migration `m027` + model sync

**Files:**
- Create: `backend/tests/crud/test_constraints_m027.py`
- Modify: `backend/app/models.py` (SaleLine `__table_args__` ~L1109; Product class ~L372; SystemSetting field ~L225)
- Create: `backend/app/alembic/versions/<rev>_m027_constraint_hardening.py`

- [ ] **Step 1: Write the failing integrity tests**

Create `backend/tests/crud/test_constraints_m027.py`. This mirrors `tests/crud/test_movement_fks.py` (same `db: Session` fixture, append-only rows cleaned by the session-end TRUNCATE).

```python
"""M027 constraint-hardening tests: DB-level CHECKs for saleline.quantity (#5)
and product prices (#6), plus systemsetting.updated_by_user_id ON DELETE SET
NULL (#7). Defense-in-depth — the API already validates, these assert the DB
rejects raw writes that bypass it."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    Product,
    Sale,
    SaleLine,
    SaleLineKind,
    SystemSetting,
    User,
)


def _make_product(db: Session, *, retail: str = "100.00", repair: str = "20.00") -> Product:
    product = Product(
        sku=f"M027-{uuid.uuid4().hex[:8]}",
        model_name="Widget",
        retail_price_thb=Decimal(retail),
        repair_price_thb=Decimal(repair),
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


def test_saleline_quantity_must_be_positive(db: Session) -> None:
    """#5: a raw saleline insert with quantity <= 0 must be rejected by the DB."""
    product = _make_product(db)
    sale = Sale(total_thb=Decimal("0.00"))
    db.add(sale)
    db.commit()
    db.refresh(sale)
    line = SaleLine(
        sale_id=sale.id,
        line_kind=SaleLineKind.PRODUCT,
        product_id=product.id,
        quantity=0,
        unit_price_thb=Decimal("10.00"),
        unit_cost_thb=Decimal("5.00"),
    )
    db.add(line)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_product_prices_must_be_non_negative(db: Session) -> None:
    """#6: negative retail/repair price must be rejected by the DB."""
    bad_retail = Product(
        sku=f"M027-{uuid.uuid4().hex[:8]}",
        model_name="Widget",
        retail_price_thb=Decimal("-1.00"),
        repair_price_thb=Decimal("20.00"),
    )
    db.add(bad_retail)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_systemsetting_user_delete_sets_null(db: Session) -> None:
    """#7: deleting a user referenced by systemsetting.updated_by_user_id
    succeeds and nulls the column (instead of being blocked by the FK)."""
    user = User(
        email=f"m027-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    setting = SystemSetting(
        key=f"m027_{uuid.uuid4().hex[:8]}",
        value={"v": 1},
        updated_by_user_id=user.id,
    )
    db.add(setting)
    db.commit()
    setting_id = setting.id

    db.delete(user)
    db.commit()  # must NOT raise

    refreshed = db.exec(select(SystemSetting).where(SystemSetting.id == setting_id)).one()
    assert refreshed.updated_by_user_id is None
```

> Before running: confirm the `Sale` and `User` constructor fields above match the real models (open `backend/app/models.py`, search `class Sale(` and `class User(`). Adjust required fields (e.g. a `Sale` may need a `status` or `customer_id`) to the minimal valid row. Keep the assertion logic unchanged.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose exec backend pytest tests/crud/test_constraints_m027.py -v`
Expected: `test_saleline_quantity_must_be_positive` and `test_product_prices_must_be_non_negative` FAIL (commit succeeds, no `IntegrityError` raised); `test_systemsetting_user_delete_sets_null` FAILS with an `IntegrityError` on `db.delete(user)` (current FK has no `ON DELETE` action → RESTRICT blocks it).

- [ ] **Step 3: Add the model constraints (#5, #6, #7)**

In `backend/app/models.py`:

**(a) #5 — append to `SaleLine.__table_args__`** (currently ends with the `uq_saleline_pricing_override_request_id` UniqueConstraint):

```python
    __table_args__ = (
        CheckConstraint(
            "unit_cost_thb >= 0", name="ck_saleline_unit_cost_nonneg"
        ),
        CheckConstraint(
            "line_kind != 'UNIT' OR unit_id IS NOT NULL",
            name="ck_saleline_unit_requires_unit_id",
        ),
        CheckConstraint("quantity > 0", name="ck_saleline_quantity_positive"),
        # An override applies to at most one line (nullable unique → many NULLs OK).
        UniqueConstraint(
            "pricing_override_request_id",
            name="uq_saleline_pricing_override_request_id",
        ),
    )
```

**(b) #6 — add a `__table_args__` to the `Product` table class** (it has none today). Insert it as the first line of `class Product(ProductBase, table=True):`:

```python
class Product(ProductBase, table=True):
    __table_args__ = (
        CheckConstraint(
            "retail_price_thb >= 0", name="ck_product_retail_price_nonneg"
        ),
        CheckConstraint(
            "repair_price_thb >= 0", name="ck_product_repair_price_nonneg"
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    ...
```

(`CheckConstraint` is already imported — it's used by `SaleLine`.)

**(c) #7 — declare `ondelete="SET NULL"` on `SystemSetting.updated_by_user_id`.** Replace:

```python
    updated_by_user_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id"
    )
```

with:

```python
    updated_by_user_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            Uuid(), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
        ),
    )
```

Then ensure the imports exist at the top of `models.py`. `Column` is already imported (used by `SystemSetting.value`). Add `ForeignKey` and `Uuid` if missing — check the existing `from sqlalchemy import ...` line and append them:

```python
from sqlalchemy import (
    ...,
    Column,
    ForeignKey,
    Uuid,
)
```

> Verify by grep: `grep -nE "ForeignKey|Uuid|^from sqlalchemy" backend/app/models.py`. If `Uuid` isn't available from `sqlalchemy` in this version, use `sa.Uuid` equivalently or reuse the type already used for other UUID FK columns in the file — match the existing pattern.

- [ ] **Step 4: Create the `m027` migration**

Find the revision filename convention (random hex prefix + slug). Create `backend/app/alembic/versions/<newhex>_m027_constraint_hardening.py`. Use the same style as `0d75e85a30ef_m024_*.py`. `down_revision` is m026 = `5c22a636e00e`.

```python
"""m027 constraint hardening

Revision ID: <newhex>
Revises: 5c22a636e00e
Create Date: 2026-06-12

Defense-in-depth DB constraints (CodeRabbit remediation #5/#6/#7):
- saleline.quantity > 0
- product retail/repair price >= 0
- systemsetting.updated_by_user_id FK -> ON DELETE SET NULL
"""
from alembic import op

revision = "<newhex>"
down_revision = "5c22a636e00e"
branch_labels = None
depends_on = None

# m006 created this FK inline in create_table, so Postgres auto-named it.
# Confirm the name before running (see Step 5 note); default autogenerated
# name for an inline FK is "<table>_<column>_fkey".
_SS_FK = "systemsetting_updated_by_user_id_fkey"


def upgrade() -> None:
    op.create_check_constraint(
        "ck_saleline_quantity_positive", "saleline", "quantity > 0"
    )
    op.create_check_constraint(
        "ck_product_retail_price_nonneg", "product", "retail_price_thb >= 0"
    )
    op.create_check_constraint(
        "ck_product_repair_price_nonneg", "product", "repair_price_thb >= 0"
    )
    op.drop_constraint(_SS_FK, "systemsetting", type_="foreignkey")
    op.create_foreign_key(
        _SS_FK,
        "systemsetting",
        "user",
        ["updated_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(_SS_FK, "systemsetting", type_="foreignkey")
    op.create_foreign_key(
        _SS_FK, "systemsetting", "user", ["updated_by_user_id"], ["id"]
    )
    op.drop_constraint("ck_product_repair_price_nonneg", "product", type_="check")
    op.drop_constraint("ck_product_retail_price_nonneg", "product", type_="check")
    op.drop_constraint("ck_saleline_quantity_positive", "saleline", type_="check")
```

- [ ] **Step 5: Confirm the FK name, then apply the migration**

Confirm the real constraint name (the `_SS_FK` default may differ):

Run: `docker compose exec backend python -c "from sqlalchemy import create_engine, text; from app.core.config import settings; e=create_engine(str(settings.SQLALCHEMY_DATABASE_URI)); print([r[0] for r in e.connect().execute(text(\"select conname from pg_constraint c join pg_class t on c.conrelid=t.oid where t.relname='systemsetting' and contype='f'\"))])"`
Expected: prints the FK name(s) on `systemsetting`. If it differs from `systemsetting_updated_by_user_id_fkey`, update `_SS_FK` in the migration.

Then apply:
Run: `docker compose exec backend alembic upgrade head`
Expected: completes without error; `alembic current` shows the m027 revision.

> If `alembic upgrade head` fails on a CHECK, the dev DB already holds violating rows (qty ≤ 0 / negative price). That is the correct signal — inspect and clean those rows, then re-run. Do not weaken the constraint.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `docker compose exec backend pytest tests/crud/test_constraints_m027.py -v`
Expected: all 3 tests PASS.

- [ ] **Step 7: Run mypy + the focused suite to check nothing regressed**

Run: `docker compose exec backend bash -c "mypy app && pytest tests/crud -q"`
Expected: mypy clean; crud suite green. (The model FK change must not break existing systemsetting usage.)

- [ ] **Step 8: Commit**

```bash
git add backend/app/models.py backend/app/alembic/versions/ backend/tests/crud/test_constraints_m027.py
git commit -m "fix(db): m027 — saleline qty + product price CHECKs, systemsetting FK ON DELETE SET NULL

CodeRabbit remediation #5/#6/#7. Defense-in-depth DB constraints mirroring
the m021/m024/m025 hardening convention.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Frontend ticket idempotency + orphan handling (#8)

**Files:**
- Modify: `frontend/src/routes/_layout/tickets.tsx` (`submitTicket` ~L93-107; `Tickets` component state; `handleClose` ~L205-216; mutation `onSuccess`/`onError` ~L182-200)
- Modify: `frontend/tests/tickets.spec.ts`

- [ ] **Step 1: Write the failing E2E test**

Append to `frontend/tests/tickets.spec.ts`. The test forces the **first** `addServiceTicketPart` call to fail via Playwright request interception, captures the `idempotency_key` sent on each `openServiceTicket`, then retries and asserts the key is reused (so the backend resumes the same ticket rather than creating a duplicate).

```ts
test("retry after a failed part-add reuses the same idempotency key", async ({
  page,
}) => {
  const openKeys: string[] = []
  let failNextPartAdd = true

  // Capture the idempotency_key on every ticket-open call.
  await page.route("**/api/v1/service-tickets", async (route) => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON() as { idempotency_key: string }
      openKeys.push(body.idempotency_key)
    }
    await route.continue()
  })

  // Fail the first part-add, let subsequent ones through.
  await page.route("**/api/v1/service-tickets/*/parts", async (route) => {
    if (failNextPartAdd) {
      failNextPartAdd = false
      await route.fulfill({ status: 500, body: "{}" })
      return
    }
    await route.continue()
  })

  // --- Drive the ticket UI: select customer, enter issue, scan one PART,
  //     then click Close. Reuse the existing helpers/selectors already used
  //     by the other tests in this file (mirror their setup exactly). ---
  await openTicketsPageWithOnePart(page) // existing-style helper; build from current test setup

  await page.getByRole("button", { name: /close/i }).click()
  await expect(page.getByText(/could not close the ticket/i)).toBeVisible()

  // Retry.
  await page.getByRole("button", { name: /close/i }).click()
  await expect(page.getByText(/ticket closed/i)).toBeVisible()

  // The two opens must have carried the SAME idempotency key.
  expect(openKeys.length).toBeGreaterThanOrEqual(2)
  expect(new Set(openKeys).size).toBe(1)
})
```

> Build `openTicketsPageWithOnePart` (or inline the steps) from the existing `tickets.spec.ts` setup — reuse the same login, navigation, customer-select, and scan helpers the current tests use. Do not invent new selectors; match what's already there.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && bunx playwright test tickets.spec.ts -g "reuses the same idempotency key"`
Expected: FAIL — `new Set(openKeys).size` is 2 (current code generates a fresh `crypto.randomUUID()` per click).

- [ ] **Step 3: Reuse the idempotency key across retries**

In `frontend/src/routes/_layout/tickets.tsx`, inside the `Tickets` component, add a ref that holds the current submission's key (lazily initialized once), and reset it on success.

Add near the other refs (after `const scanRef = useRef<ScanInputHandle>(null)`):

```tsx
  // One idempotency key per logical submission. Reused across retries so a
  // retry after a partial failure resumes the same ticket instead of opening
  // a duplicate. Reset only after a ticket successfully closes.
  const idempotencyKeyRef = useRef<string>(crypto.randomUUID())
```

In `handleClose`, pass the ref instead of a fresh UUID:

```tsx
  const handleClose = useCallback(() => {
    if (!canClose) return
    const submission = buildTicketSubmission(
      parts,
      customerId,
      issue,
      notes,
      resolution,
      idempotencyKeyRef.current,
    )
    mutation.mutate(submission)
  }, [canClose, parts, customerId, issue, notes, resolution, mutation])
```

In the mutation `onSuccess`, rotate the key for the next ticket (add this line alongside the existing resets):

```tsx
    onSuccess: (ticket) => {
      // ... existing resets ...
      idempotencyKeyRef.current = crypto.randomUUID()
    },
```

- [ ] **Step 4: Wrap `submitTicket` so a mid-flight failure is explicit**

Replace `submitTicket` (L93-107) with a version that wraps the parts/close phase and tags a post-open failure, so the user is told the ticket may be left open (there is no cancel endpoint to roll it back):

```tsx
/** Run the full ticket lifecycle in one online-only sequence. The idempotency
 * key is reused on retry, so a retry resumes the same opened ticket. If a
 * part-add or close fails after the ticket is opened, we surface a clear error
 * (no cancel endpoint exists to roll back). */
async function submitTicket(s: TicketSubmission): Promise<ServiceTicketPublic> {
  const ticket = await ServiceTicketsService.openServiceTicket({
    requestBody: s.open,
  })
  try {
    for (const part of s.parts) {
      await ServiceTicketsService.addServiceTicketPart({
        ticketId: ticket.id,
        requestBody: part,
      })
    }
    return await ServiceTicketsService.closeServiceTicket({
      ticketId: ticket.id,
      requestBody: s.close,
    })
  } catch (err) {
    throw new Error(
      "Ticket opened but could not be completed. Retry to resume it.",
      { cause: err },
    )
  }
}
```

Update `onError` to show the thrown message when present (keep the generic fallback):

```tsx
    onError: (err) => {
      showErrorToast(
        err.message || "Could not close the ticket. Please try again.",
      )
    },
```

> Note: the E2E test in Step 1 asserts the text `/could not close the ticket/i` on the first failure. Since the failure now happens **after** open (during part-add), the surfaced message is the "Retry to resume it." string. Update the test's first-failure assertion to match: `await expect(page.getByText(/retry to resume it/i)).toBeVisible()`.

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd frontend && bunx playwright test tickets.spec.ts -g "reuses the same idempotency key"`
Expected: PASS — both opens use one key; second attempt closes the ticket.

- [ ] **Step 6: Run the full tickets E2E + typecheck to confirm no regression**

Run: `cd frontend && bunx tsc --noEmit && bunx playwright test tickets.spec.ts`
Expected: typecheck clean; all `tickets.spec.ts` tests green.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/routes/_layout/tickets.tsx frontend/tests/tickets.spec.ts
git commit -m "fix(tickets): reuse idempotency key on retry + explicit post-open failure

CodeRabbit remediation #8. A retry now resumes the same opened ticket instead
of creating a duplicate; a part-add/close failure surfaces a clear message
(no cancel endpoint exists to auto-roll-back).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Mandatory review gate (high-risk: money + append-only)

No code in this task — it's the CLAUDE.md-required review before the PR.

- [ ] **Step 1: Dispatch `ecc:database-reviewer`** on the m027 migration + `models.py` constraint changes. Focus: constraint correctness, naming convention vs m021/m024/m025, downgrade reversibility, the FK drop/recreate name match.

- [ ] **Step 2: Dispatch `ecc:security-reviewer`** on the same diff + `tickets.tsx`. Focus: the `ON DELETE SET NULL` audit-data implication, and that the idempotency-key reuse can't leak or replay across users/sessions.

- [ ] **Step 3: Run `superpowers:requesting-code-review`** (orchestrator) over the full branch diff for this work.

- [ ] **Step 4: Address any blocking findings** via `superpowers:receiving-code-review`, then re-run the affected tests.

- [ ] **Step 5: Ship** via `create-pr` — one scoped PR for this remediation. PR body must note: m027 adds constraints to existing tables (no edit-in-place), dev/CI DBs just need `alembic upgrade head` (no reset), and #8 has a known residual (re-adding parts on a resumed ticket needs a future backend idempotent part-add / cancel endpoint).

---

## Self-Review

- **Spec coverage:** #5 → Task 1 Step 3a + migration; #6 → Step 3b + migration; #7 → Step 3c + migration; #8 (idempotency) → Task 2 Steps 3; #8 (orphan/try-catch) → Task 2 Step 4; testing (backend TDD) → Task 1 Steps 1-2-6; testing (frontend) → Task 2 Steps 1-2-5; review gates → Task 3. All spec sections mapped.
- **Known adaptation points flagged inline:** exact `Sale`/`User` constructor fields (Task 1 Step 1), `Uuid`/`ForeignKey` import availability (Step 3c), real FK constraint name (Step 5), and reuse of existing `tickets.spec.ts` helpers (Task 2 Step 1). These require reading current code at execution time — called out rather than guessed.
- **Type/name consistency:** constraint names (`ck_saleline_quantity_positive`, `ck_product_retail_price_nonneg`, `ck_product_repair_price_nonneg`, `_SS_FK`) are identical in `models.py`, the migration, and the tests. `idempotencyKeyRef` is used consistently in Task 2.
- **No placeholders:** every code step shows the actual code; every run step shows the command + expected result.
