# CodeRabbit Review Remediation — Design

**Date:** 2026-06-12
**Branch:** `feat/hardening-pr3-e2e-infra`
**Source:** `/coderabbit:coderabbit-review` over the full branch diff vs `master`, run in two scoped passes (`--dir backend`, `--dir frontend`) to stay under the free-CLI 150-file cap. 18 raw findings; verified against current code.

## Summary

CodeRabbit produced 18 findings. We scoped to the 9 critical/major/frontend-major ones, then **verified each against the actual code** (two read-only Explore agents over `models.py`, the migrations, `crud.py`, `tickets.tsx`, `receive.tsx`, and the test suite). **5 were false positives or intentional design.** This spec covers the **4 confirmed-real fixes**.

## Confirmed-real fixes (in scope)

| # | Defect | Evidence | Fix |
|---|--------|----------|-----|
| #5 | `saleline.quantity` has no DB-level `CHECK quantity > 0`. API enforces via Pydantic `gt=0`, but a raw INSERT could write 0/negative. `ServiceTicketPart` already has this exact check. | m010 migration L43; `SaleLine.__table_args__` lacks it; `SaleLineInput` has `gt=0`. | Add `ck_saleline_quantity_positive` in `models.py` + m027. |
| #6 | `product.retail_price_thb` / `repair_price_thb` lack non-negative CHECKs. m021 added these for `unit`/`saleline` cost fields but skipped product prices. | m005 L29-30; m021 only touches `unit`/`saleline`; `Product.__table_args__` has none. | Add `ck_product_retail_price_nonneg`, `ck_product_repair_price_nonneg` in `models.py` + m027. |
| #7 | `systemsetting.updated_by_user_id → user.id` FK lacks `ondelete='SET NULL'`. Blocks user deletion; m024 set exactly this on an analogous audit field. | m006 L29-31; `SystemSetting` model declares FK without `ondelete`. | Recreate FK with `ondelete='SET NULL'` in m027; declare `ondelete` on the model field. |
| #8 | `tickets.tsx submitTicket` opens ticket → adds parts → closes with **no try/catch**: a failed part-add orphans an OPEN ticket. Retry generates a fresh `crypto.randomUUID()` idempotency key, risking duplicates after a partial success. | `tickets.tsx` L93-107 (no try/catch); L205-216 (`crypto.randomUUID()` per call). | Reuse idempotency key across retries; wrap flow in try/catch with cleanup. |

## Dismissed findings (no action) — with evidence

- **#1 (critical)** — `partmovement` FKs for `service_ticket_id` / `project_pull_id` / `stock_adjustment_id` **are** declared, added in m012/m014/m025 after their parent tables exist; the model declares all three; `tests/crud/test_movement_fks.py` already asserts `service_ticket_id` rejects bad IDs. Correct as designed.
- **#2** — `crud.set_min_stock_level` already does `raise HTTPException(404)` (crud.py L825-837). False positive.
- **#3** — m017 FKs omit `ondelete`, which defaults to `RESTRICT` in Postgres — the intended append-only behavior (documented in m025). Design intent.
- **#4** — `ck_cost_line_total` exact-equality concern assumes float drift; Postgres `NUMERIC(12,2)` is exact decimal, so `int * NUMERIC` cannot drift. False positive.
- **#9** — `receive.tsx handlePrint` already guards with `if (!token)` + `try/catch` around the fetch; `getItem` throwing is a rare edge with a non-crashing fallback. False positive.

The 9 remaining minor findings (NaN/format guards, `barcode.py` caption truncation, `export.py` empty-headers, m003/m005 `server_default=now()`, m026 uppercase-role regex, `privateApi.ts` global-token mutation) are deferred — none are correctness-critical.

## Design

### Backend: new migration `m027` + `models.py` sync

Decision: **additive corrective migration** (not edit-in-place), matching the repo's own convention (m021 `create_check_constraint`, m024/m025 `create_foreign_key` on existing tables). Editing originals would break from that pattern and force a dev/CI DB reset; a new migration does not.

Each constraint is declared in **both** layers so the ORM and the DB stay consistent and future autogenerate diffs are clean:

- `models.py`:
  - `SaleLine.__table_args__` += `CheckConstraint("quantity > 0", name="ck_saleline_quantity_positive")`
  - `Product.__table_args__` += `CheckConstraint("retail_price_thb >= 0", name="ck_product_retail_price_nonneg")`, `CheckConstraint("repair_price_thb >= 0", name="ck_product_repair_price_nonneg")`
  - `SystemSetting.updated_by_user_id` field → declare FK with `ondelete="SET NULL"` (via `sa_column`/`ForeignKey`).
- `m027` (`down_revision` = m026's revision id):
  - `upgrade()`: `op.create_check_constraint` ×3; drop + recreate the `systemsetting` FK with `ondelete='SET NULL'`.
  - `downgrade()`: drop the 3 CHECKs; recreate the FK without `ondelete`.
- **Data precondition:** if a dev DB already holds violating rows (qty ≤ 0 / negative price), `m027` will fail on the CHECK. That is the correct signal — surface it, don't silence it. Inspect/clean before re-running if it occurs.

### Frontend: `tickets.tsx` (#8)

Two parts, sequenced by risk:

1. **Idempotency-key reuse (primary, low-risk):** generate the key once and hold it (ref/state) so a retry reuses it. The backend `openServiceTicket` idempotency then resumes the same ticket rather than creating a duplicate. *First impl step:* confirm `openServiceTicket` honors the idempotency key.
2. **Orphan handling (secondary):** wrap open→parts→close in try/catch. *First impl step:* check whether a cancel/void service-ticket endpoint exists. If yes → call it on part-add failure. If no → surface a clear "ticket left open, needs attention" error instead of a silent throw. Do **not** invent a backend endpoint in this PR.

## Testing (high-risk: money + append-only ledger → CLAUDE.md stages 3–5 mandatory)

- **Backend (TDD, failing test first):**
  - raw INSERT `saleline` with `quantity <= 0` → `IntegrityError`.
  - product with negative `retail_price_thb` / `repair_price_thb` → `IntegrityError`.
  - deleting a user referenced by `systemsetting.updated_by_user_id` now succeeds and nulls the column.
- **Frontend:**
  - unit-test that a retry reuses the same idempotency key.
  - test the part-add failure / cleanup branch.
  - existing `tickets.spec.ts` E2E stays green.

## Review gates

`requesting-code-review` **plus** mandatory `ecc:database-reviewer` + `ecc:security-reviewer` (ledger/money rule from CLAUDE.md) before opening the PR.

## Out of scope

The 9 minor findings above; the false-positive/design-intent findings (#1, #2, #3, #4, #9).
