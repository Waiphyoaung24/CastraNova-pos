# Audit SKU + Batch Filters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `sku` and `batch_no` filters to the admin audit log (FR-019), backend endpoint through frontend UI.

**Architecture:** Extend `crud.list_audit` with two optional params. `sku` resolves to a product and scopes **both** ledgers (PART by `product_id`, UNIT by a `unit_id IN (units of product)` sub-select) — correct for QUANTITY and SERIALIZED products. `batch_no` is PART-only and matches a movement two ways OR'd together: the RECEIVED movement that created the batch (`part_movement.part_batch_id`) and consumption movements that drew from it (`cost_line.part_batch_id → part_movement_id`). The route passes the params through; the frontend adds a SKU `Select` and a Batch `Input` and regenerates the SDK.

**Tech Stack:** FastAPI, SQLModel/SQLAlchemy, psycopg3, pytest, TestClient (backend); React + TanStack Query, shadcn/ui, `@hey-api/openapi-ts`, Playwright (frontend).

## Global Constraints

- **No schema change → no Alembic migration.** `AuditEntryPublic` is unchanged; `batch_no` is filtered on, never returned in a row.
- **All DB access goes through `crud.py`.** The route calls `crud.list_audit`; no `session.exec` in the route.
- **Strict mypy** — annotate everything; new params are `str | None = None`.
- **Never hand-edit `frontend/src/client/` or `routeTree.gen.ts`** — regenerate the SDK with `scripts/generate-client.sh`.
- **Frontend lint/format is biome** (`bun run lint`), not ESLint/Prettier.
- **Primary keys are UUIDs**; `sku`/`batch_no` are human strings (`str`), not UUIDs.

---

## File Structure

- `backend/app/crud.py` — `list_audit` gains `sku` + `batch_no` params and their predicates; import `or_`.
- `backend/app/api/routes/audit.py` — `list_audit` route gains two `Query` params, passes them through, docstring updated.
- `backend/tests/api/routes/test_audit.py` — extend the `seed_audit` fixture (yield `serial_sku`, `batch_no`); add 5 tests.
- `frontend/src/lib/audit.ts` — `AuditFilter` + `buildAuditQuery` gain `sku`, `batchNo`.
- `frontend/tests/audit.spec.ts` — extend the two `buildAuditQuery` cases.
- `frontend/src/routes/_layout/audit.tsx` — SKU `Select` + Batch `Input` (commit on Enter/blur).
- `frontend/src/client/*` — regenerated (do not hand-edit).

Task order: **1 (SKU backend) → 2 (batch backend) → 3 (regen SDK) → 4 (frontend helper) → 5 (frontend UI).** Tasks 4–5 depend on the regenerated types from Task 3.

---

### Task 1: Backend SKU filter (spans both ledgers)

**Files:**
- Modify: `backend/app/crud.py` — `list_audit` (currently ~lines 3266-3367)
- Modify: `backend/app/api/routes/audit.py` — `list_audit` route (lines 16-52)
- Test: `backend/tests/api/routes/test_audit.py` — `seed_audit` fixture + new tests

**Interfaces:**
- Consumes: existing `crud.list_audit(*, session, event_type, from_date, to_date, actor_user_id, product_id, unit_id, skip, limit)`; models `Product`, `Unit`, `UnitMovement`, `PartMovement` (already imported in `crud.py`).
- Produces: `crud.list_audit(..., sku: str | None = None, ...)`. Endpoint `GET /audit?sku=<str>` restricts to the product with that SKU across whichever ledger it lives in; an unknown SKU returns `[]`.

- [ ] **Step 1: Extend the `seed_audit` fixture to expose the serialized SKU**

In `backend/tests/api/routes/test_audit.py`, in the `yield {...}` dict of `seed_audit`, add the serialized product's SKU alongside the existing keys:

```python
        "serial_product_id": ser.id,
        "serial_sku": ser.sku,
```

(Add the `"serial_sku"` line; `"serial_product_id"` already exists — keep it.)

- [ ] **Step 2: Write the failing SKU tests**

Append to `backend/tests/api/routes/test_audit.py`:

```python
def test_audit_filter_sku_quantity_product(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    seed_audit: dict[str, object],
) -> None:
    sku = seed_audit["part_sku"]
    pid = seed_audit["part_product_id"]
    r = client.get(
        f"{PREFIX}/audit", params={"sku": sku}, headers=superuser_token_headers
    )
    assert r.status_code == 200
    rows = r.json()
    assert rows
    for row in rows:
        assert row["ledger"] == "PART"
        assert row["product_id"] == str(pid)
        assert row["unit_id"] is None


def test_audit_filter_sku_serialized_product_reaches_unit_ledger(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    seed_audit: dict[str, object],
) -> None:
    sku = seed_audit["serial_sku"]
    uid = seed_audit["unit_id"]
    r = client.get(
        f"{PREFIX}/audit", params={"sku": sku}, headers=superuser_token_headers
    )
    assert r.status_code == 200
    rows = r.json()
    assert rows, "SKU filter must reach the UNIT ledger for a serialized product"
    for row in rows:
        assert row["ledger"] == "UNIT"
        assert row["unit_id"] == str(uid)


def test_audit_filter_sku_unknown_returns_empty(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    r = client.get(
        f"{PREFIX}/audit",
        params={"sku": "NO-SUCH-SKU-zzz"},
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    assert r.json() == []
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/api/routes/test_audit.py -k sku -v`
Expected: FAIL — the endpoint ignores the unknown `sku` query param (so `test_audit_filter_sku_unknown_returns_empty` returns rows instead of `[]`, and the serialized case returns nothing because there is no `sku` handling yet). (Requires the Postgres `db` service up — e.g. `docker compose up -d db` — as the `db` fixture connects to it.)

- [ ] **Step 4: Add the `sku` param + resolution + predicates in `crud.list_audit`**

In `backend/app/crud.py`, add `sku` to the signature (after `unit_id`):

```python
    unit_id: uuid.UUID | None = None,
    sku: str | None = None,
    skip: int = 0,
```

Immediately after `bound = skip + limit`, resolve the SKU to a product id and short-circuit an unknown SKU:

```python
    bound = skip + limit

    product_id_from_sku: uuid.UUID | None = None
    if sku is not None:
        product_id_from_sku = session.exec(
            select(col(Product.id)).where(col(Product.sku) == sku)
        ).first()
        if product_id_from_sku is None:
            return []  # unknown SKU matches nothing
```

In the `if audit_unit:` block, after the existing `if unit_id is not None:` where-clause and before `u_stmt = u_stmt.order_by(...)`, add the UNIT-ledger SKU predicate (reach the product's units via a sub-select):

```python
        if sku is not None:
            u_stmt = u_stmt.where(
                col(UnitMovement.unit_id).in_(
                    select(col(Unit.id)).where(
                        col(Unit.product_id) == product_id_from_sku
                    )
                )
            )
```

In the `if audit_part:` block, after the existing `if product_id is not None:` where-clause and before `p_stmt = p_stmt.order_by(...)`, add the PART-ledger SKU predicate:

```python
        if sku is not None:
            p_stmt = p_stmt.where(
                col(PartMovement.product_id) == product_id_from_sku
            )
```

- [ ] **Step 5: Add the `sku` param to the route**

In `backend/app/api/routes/audit.py`, add the param after `unit_id` (before `skip`):

```python
    sku: Annotated[
        str | None,
        Query(description="Restrict to a product's SKU (spans UNIT + PART ledgers)"),
    ] = None,
```

Pass it through in the `crud.list_audit(...)` call:

```python
        unit_id=unit_id,
        sku=sku,
        skip=skip,
```

Update the route docstring's filter sentence to mention SKU, e.g. append: `` ``sku`` scopes to a product across whichever ledger it uses.``

- [ ] **Step 6: Run the SKU tests to verify they pass**

Run: `cd backend && uv run pytest tests/api/routes/test_audit.py -k sku -v`
Expected: PASS (3 passed).

- [ ] **Step 7: Run the full audit suite + mypy to confirm no regression**

Run: `cd backend && uv run pytest tests/api/routes/test_audit.py -v && uv run mypy app/crud.py app/api/routes/audit.py`
Expected: all audit tests PASS; mypy reports no new errors. (If mypy flags the `.in_(select(...))` sub-select typing, wrap the inner select with `col(...)` as shown — it is the codebase's `col()` idiom — or fall back to `.scalar_subquery()` on the inner select.)

- [ ] **Step 8: Commit**

```bash
git add backend/app/crud.py backend/app/api/routes/audit.py backend/tests/api/routes/test_audit.py
git commit -m "feat(audit): filter audit log by SKU across both ledgers (FR-019)"
```

---

### Task 2: Backend batch filter (PART-only, RECEIVED + consumption)

**Files:**
- Modify: `backend/app/crud.py` — `list_audit` (ledger gating + PART predicate); import `or_`
- Modify: `backend/app/api/routes/audit.py` — `list_audit` route
- Test: `backend/tests/api/routes/test_audit.py` — `seed_audit` fixture + new tests

**Interfaces:**
- Consumes: `crud.list_audit(..., sku=..., ...)` from Task 1; models `PartBatch`, `CostLine`, `PartMovement` (already imported).
- Produces: `crud.list_audit(..., batch_no: str | None = None, ...)`. Endpoint `GET /audit?batch_no=<str>` returns only PART rows tied to a batch of that number (created it, or drew from it).

- [ ] **Step 1: Capture the batch in the fixture and expose its `batch_no`**

In `backend/tests/api/routes/test_audit.py`, change the QUANTITY receive call to bind its return, then yield the batch number.

Change:
```python
    crud.receive_quantity(
        session=db,
        product_id=qty.id,
```
to:
```python
    batch = crud.receive_quantity(
        session=db,
        product_id=qty.id,
```

Add to the `yield {...}` dict:
```python
        "batch_no": batch.batch_no,
```

- [ ] **Step 2: Write the failing batch tests**

Append to `backend/tests/api/routes/test_audit.py`:

```python
def test_audit_filter_batch_no_spans_receive_and_consumption(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    seed_audit: dict[str, object],
) -> None:
    batch_no = seed_audit["batch_no"]
    pid = seed_audit["part_product_id"]
    r = client.get(
        f"{PREFIX}/audit",
        params={"batch_no": batch_no},
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    rows = r.json()
    assert rows
    for row in rows:
        assert row["ledger"] == "PART"
        assert row["product_id"] == str(pid)
    events = {row["event_type"] for row in rows}
    # RECEIVED matches via part_movement.part_batch_id; SOLD via cost_line draw.
    assert {"RECEIVED", "SOLD"} <= events


def test_audit_filter_batch_no_excludes_unit_ledger(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    seed_audit: dict[str, object],
) -> None:
    batch_no = seed_audit["batch_no"]
    r = client.get(
        f"{PREFIX}/audit",
        params={"batch_no": batch_no},
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    rows = r.json()
    assert rows
    assert all(row["ledger"] == "PART" for row in rows)
    assert all(row["unit_id"] is None for row in rows)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/api/routes/test_audit.py -k batch_no -v`
Expected: FAIL — `batch_no` is ignored, so results include unrelated/UNIT rows (or the fixture `KeyError` if Step 1 was skipped).

- [ ] **Step 4: Import `or_` and add the batch param + PART predicate in `crud.list_audit`**

In `backend/app/crud.py`, extend the sqlalchemy import (line 9):

```python
from sqlalchemy import ColumnElement, case, func, or_
```

Add `batch_no` to the signature (after `sku`):

```python
    sku: str | None = None,
    batch_no: str | None = None,
    skip: int = 0,
```

Update the ledger gating so `batch_no` (PART-only) excludes the UNIT ledger. Change:

```python
    audit_unit = product_id is None
    audit_part = unit_id is None
```
to:
```python
    audit_unit = product_id is None and batch_no is None
    audit_part = unit_id is None
```

In the `if audit_part:` block, after the SKU predicate added in Task 1 and before `p_stmt = p_stmt.order_by(...)`, add the batch predicate (direct link OR via cost lines):

```python
        if batch_no is not None:
            batch_ids = select(col(PartBatch.id)).where(
                col(PartBatch.batch_no) == batch_no
            )
            p_stmt = p_stmt.where(
                or_(
                    col(PartMovement.part_batch_id).in_(batch_ids),
                    col(PartMovement.id).in_(
                        select(col(CostLine.part_movement_id)).where(
                            col(CostLine.part_batch_id).in_(batch_ids)
                        )
                    ),
                )
            )
```

- [ ] **Step 5: Add the `batch_no` param to the route**

In `backend/app/api/routes/audit.py`, add after the `sku` param (before `skip`):

```python
    batch_no: Annotated[
        str | None,
        Query(description="Restrict to PART entries that created or drew from a batch"),
    ] = None,
```

Pass it through:

```python
        sku=sku,
        batch_no=batch_no,
        skip=skip,
```

Update the docstring to note: `` ``batch_no`` restricts to PART entries that created or consumed that batch.``

- [ ] **Step 6: Run the batch tests to verify they pass**

Run: `cd backend && uv run pytest tests/api/routes/test_audit.py -k batch_no -v`
Expected: PASS (2 passed).

- [ ] **Step 7: Run the full audit suite + mypy**

Run: `cd backend && uv run pytest tests/api/routes/test_audit.py -v && uv run mypy app/crud.py app/api/routes/audit.py`
Expected: all audit tests PASS; mypy clean.

- [ ] **Step 8: Commit**

```bash
git add backend/app/crud.py backend/app/api/routes/audit.py backend/tests/api/routes/test_audit.py
git commit -m "feat(audit): filter audit log by batch_no (receive + consumption) (FR-019)"
```

---

### Task 3: Regenerate the SDK client

**Files:**
- Modify (generated, do not hand-edit): `frontend/src/client/types.gen.ts`, `frontend/src/client/sdk.gen.ts`, `frontend/src/client/schemas.gen.ts`, `frontend/openapi.json`

**Interfaces:**
- Consumes: the backend `GET /audit` OpenAPI now advertising `sku` and `batch_no` query params (Tasks 1–2).
- Produces: `AuditListAuditData` type with optional `sku?: string` and `batchNo?: string` — consumed by Task 4.

- [ ] **Step 1: Regenerate**

Run: `bash scripts/generate-client.sh`
(Imports the FastAPI app to dump `openapi.json`, runs `@hey-api/openapi-ts`, then `bun run lint`. Needs `uv` and `bun`.)

- [ ] **Step 2: Verify the new params landed in the generated types**

Run: `grep -nE "batchNo|sku" frontend/src/client/types.gen.ts | head`
Expected: `AuditListAuditData` shows `sku?: string` and `batchNo?: string` (hey-api camelCases `batch_no` → `batchNo`).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/client frontend/openapi.json
git commit -m "chore(client): regenerate SDK for audit sku/batch_no params"
```

---

### Task 4: Frontend query helper (`lib/audit.ts`)

**Files:**
- Modify: `frontend/src/lib/audit.ts` — `AuditFilter`, `buildAuditQuery`
- Test: `frontend/tests/audit.spec.ts` — extend the two `buildAuditQuery` cases

**Interfaces:**
- Consumes: `AuditListAuditData` (regenerated, Task 3).
- Produces: `AuditFilter` with `sku: string` and `batchNo: string`; `buildAuditQuery` maps non-blank `sku`/`batchNo` onto the query. Consumed by Task 5.

- [ ] **Step 1: Update the failing unit tests**

In `frontend/tests/audit.spec.ts`, update both `buildAuditQuery` cases.

"drops blank filters" — add the two blank fields to the input:
```typescript
    buildAuditQuery({
      eventType: "",
      fromDate: "",
      toDate: "",
      actorUserId: "",
      sku: "",
      batchNo: "",
    }),
  ).toEqual({})
```

"includes set filters" — add the two fields to input and expected:
```typescript
    buildAuditQuery({
      eventType: "SOLD",
      fromDate: "2026-06-01",
      toDate: "2026-07-01",
      actorUserId: "u-1",
      sku: "ABC-123",
      batchNo: "20260601-ABC-001",
    }),
  ).toEqual({
    eventType: "SOLD",
    fromDate: "2026-06-01",
    toDate: "2026-07-01",
    actorUserId: "u-1",
    sku: "ABC-123",
    batchNo: "20260601-ABC-001",
  })
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && bunx playwright test tests/audit.spec.ts`
Expected: FAIL — `AuditFilter` has no `sku`/`batchNo` (type error) and `buildAuditQuery` omits them. (Playwright may start the configured `webServer`; that is fine.)

- [ ] **Step 3: Extend `AuditFilter` and `buildAuditQuery`**

In `frontend/src/lib/audit.ts`, add the two fields to the interface:

```typescript
export interface AuditFilter {
  eventType: string
  fromDate: string
  toDate: string
  /** UUID of a single acting user, or "" for all users. */
  actorUserId: string
  /** Product SKU to scope to (spans both ledgers), or "" for all. */
  sku: string
  /** Batch number to scope to (PART only), or "" for all. */
  batchNo: string
}
```

Map them in `buildAuditQuery` (drop blanks), before `return q`:

```typescript
  if (f.actorUserId) q.actorUserId = f.actorUserId
  if (f.sku) q.sku = f.sku
  if (f.batchNo) q.batchNo = f.batchNo
  return q
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && bunx playwright test tests/audit.spec.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/audit.ts frontend/tests/audit.spec.ts
git commit -m "feat(audit-ui): add sku/batchNo to audit filter query builder"
```

---

### Task 5: Frontend audit page UI (`audit.tsx`)

**Files:**
- Modify: `frontend/src/routes/_layout/audit.tsx`

**Interfaces:**
- Consumes: `AuditFilter` (with `sku`, `batchNo`) and `buildAuditQuery` (Task 4); the already-loaded `products` query for SKU options.
- Produces: SKU `Select` + Batch `Input` wired into the existing `filter` state; no new exports.

- [ ] **Step 1: Add ids and batch-input state; seed the new filter fields**

In `frontend/src/routes/_layout/audit.tsx`, add two ids next to the existing `useId()` calls:

```typescript
  const userSelectId = useId()
  const skuSelectId = useId()
  const batchId = useId()
```

Add `sku` and `batchNo` to the initial filter state:

```typescript
  const [filter, setFilter] = useState<AuditFilter>({
    eventType: "",
    fromDate: "",
    toDate: "",
    actorUserId: "",
    sku: "",
    batchNo: "",
  })
```

Add local state for the batch input (committed on Enter/blur) after the `selected` state:

```typescript
  const [batchInput, setBatchInput] = useState("")
  const commitBatch = () =>
    setFilter((f) => ({ ...f, batchNo: batchInput.trim() }))
```

- [ ] **Step 2: Add the SKU `Select` and Batch `Input` to the filter bar**

In the `<div className="flex flex-wrap items-end gap-3">` filter bar, after the "To" date `<div>`, add:

```tsx
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={skuSelectId}>SKU</Label>
          <Select
            value={filter.sku || ALL}
            onValueChange={(v) =>
              setFilter((f) => ({ ...f, sku: v === ALL ? "" : v }))
            }
          >
            <SelectTrigger id={skuSelectId} className="w-full sm:w-48">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All SKUs</SelectItem>
              {(products ?? []).map((p) => (
                <SelectItem key={p.id} value={p.sku}>
                  {p.sku}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={batchId}>Batch #</Label>
          <Input
            id={batchId}
            value={batchInput}
            onChange={(e) => setBatchInput(e.target.value)}
            onBlur={commitBatch}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault()
                commitBatch()
              }
            }}
            placeholder="e.g. 20260611-ABC-001"
            className="w-full sm:w-52"
          />
        </div>
```

(`Select`, `SelectTrigger`, `SelectValue`, `SelectContent`, `SelectItem`, `Label`, `Input`, and `ALL` are already imported/defined in this file.)

- [ ] **Step 3: Typecheck and lint**

Run: `cd frontend && bunx tsc --noEmit && bun run lint`
Expected: no type errors; biome clean. (Confirms `products` element type exposes `id` and `sku`, and the new JSX is well-typed.)

- [ ] **Step 4: Manual UI verification**

With the dev stack up (`docker compose watch`), open `/audit` as an admin and confirm: the **SKU** select lists product SKUs and narrows the ledger to that product (try both a QUANTITY and a SERIALIZED SKU); typing a **Batch #** and pressing Enter (or blurring) narrows to that batch's RECEIVED + consumption rows; clearing both restores the full ledger.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/_layout/audit.tsx
git commit -m "feat(audit-ui): SKU select + batch number filter on the audit page"
```

---

## Self-Review

**Spec coverage:**
- SKU filter (both ledgers, unknown → `[]`) → Task 1. ✓
- Batch filter (`batch_no`, RECEIVED direct link + consumption via `cost_line`, PART-only excludes UNIT) → Task 2. ✓
- No schema change / no migration → honored (no `models.py` table change, no `AuditEntryPublic` field). ✓
- Frontend SKU `Select` + Batch `Input` (commit on Enter/blur) → Task 5. ✓
- `AuditFilter` + `buildAuditQuery` extension → Task 4. ✓
- SDK regeneration (no hand-edit of `client/`) → Task 3. ✓
- Backend tests (SKU on QUANTITY, SKU on SERIALIZED, unknown SKU, batch spans receive+consumption, batch excludes UNIT) → Tasks 1–2. ✓

**Placeholder scan:** No TBD/TODO; every code step shows the exact code and command.

**Type/name consistency:** `sku: str | None` / `batch_no: str | None` used identically in `crud.list_audit` and the route; `product_id_from_sku` defined before use; `batch_ids` sub-select defined before both `.in_()` uses; frontend `sku`/`batchNo` names match the regenerated `AuditListAuditData` (hey-api camelCase) and the `AuditFilter` fields; `commitBatch`/`batchInput`/`skuSelectId`/`batchId` all defined in Task 5 Step 1 before use in Step 2.

**Note on `db`-dependent steps:** backend `pytest` steps need the Postgres `db` service reachable (the `db` fixture connects to it); this is the normal backend test prerequisite and does **not** reset the dev data volume (that is the frontend E2E suite, out of scope here).
