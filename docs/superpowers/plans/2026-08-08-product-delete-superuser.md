# Product Delete (Superuser Only) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a superuser hard-delete a product that has never entered the stock system, from the footer of the existing product edit dialog.

**Architecture:** One `DELETE /products/{product_id}` endpoint guarded by the existing `get_current_active_superuser` dependency, refusing with 409 unless `crud.is_product_fresh()` is true. The delete removes the product's `PriceChange` child rows and the product itself in one transaction. On the frontend, a pure `canDeleteProduct()` predicate gates a two-step confirm button added to `EditProductDialog`'s footer. No new model, no Alembic migration, no new component file.

**Tech Stack:** FastAPI + SQLModel + pytest (backend); React + TanStack Query + vitest (frontend); `@hey-api/openapi-ts` for the SDK.

**Design doc:** `docs/superpowers/specs/2026-08-08-product-delete-superuser-design.md`

## Global Constraints

- Branch is `feat/product-delete-superuser`, cut from `dev`. Never commit to `master`.
- All DB access goes through `backend/app/crud.py`. Routes never call `session.exec` or `session.delete` directly.
- mypy runs in strict mode. Annotate every parameter and return type.
- No change to `backend/app/models.py`, therefore **no schema migration**. One grant-only migration (m037, `GRANT DELETE ON product` to the least-privilege app role) is required and expected — see the correction note at the end of this plan. Any migration that alters a table, column, constraint, or trigger means the design is being violated; stop.
- The append-only ledgers (`UnitMovement`, `PartMovement`) and every table holding stock or money are never deleted from, under any circumstance.
- `frontend/src/client/` and `frontend/src/routeTree.gen.ts` are generated. Never hand-edit them.
- `crud.py` signals HTTP failures by raising `HTTPException` directly (see `create_product`, `update_product`). Follow that existing pattern rather than inventing a new error type.
- Backend tests run with `bash scripts/test.sh` from the repo root. Running `pytest` against a stale container gives false greens — see the warning in Task 1, Step 2.
- Frontend unit tests run with `bun run test:unit` from `frontend/`. They are vitest, collected only from `src/**/*.test.ts`, and need no stack, no browser, and no database.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `backend/app/crud.py` | `delete_product()` — the only place the DELETE statement lives | Modify (add ~18 lines after `is_product_fresh`, around line 611) |
| `backend/app/api/routes/products.py` | `DELETE /products/{product_id}` — auth, 404, freshness gate | Modify (add endpoint + import) |
| `backend/tests/api/routes/test_products.py` | Endpoint tests across all four caller tiers | Modify (append 6 tests) |
| `frontend/src/lib/product-edit.ts` | `canDeleteProduct()` — the pure visibility rule | Modify (add ~10 lines beside `canSaveProduct`) |
| `frontend/src/lib/product-edit.test.ts` | vitest coverage of the predicate | Modify (append a `describe` block) |
| `frontend/src/components/products/EditProductDialog.tsx` | Two-step delete button in the footer | Modify (footer + delete mutation + confirm state) |
| `frontend/src/client/**` | Generated SDK gains `ProductsService.deleteProduct` | Regenerate — never hand-edit |

---

### Task 1: Backend — DELETE endpoint, superuser-only, fresh-products-only

**Files:**
- Modify: `backend/app/crud.py` (insert after `is_product_fresh`, which ends at line 611)
- Modify: `backend/app/api/routes/products.py` (imports at lines 4-19; new endpoint appended after `set_min_stock_level`)
- Test: `backend/tests/api/routes/test_products.py` (append at end)

**Interfaces:**
- Consumes: `crud.get_product(*, session, product_id) -> Product | None`; `crud.is_product_fresh(*, session, product_id) -> bool`; `deps.get_current_active_superuser`; the existing test helper `_receive_quantity(db, product_id)` and `_product_body(sku, **over)` at the top of `test_products.py`; the `superuser_token_headers`, `bkk_admin_token_headers`, and `staff_token_headers` fixtures from `backend/tests/conftest.py`.
- Produces: `crud.delete_product(*, session: Session, db_product: Product) -> None`, and `DELETE {API_V1_STR}/products/{product_id}` returning 204 with an empty body.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/api/routes/test_products.py`. Note that `_receive_quantity` and `_product_body` already exist at the top of this file — do not redefine them.

```python
def _create_product(client: TestClient, headers: dict[str, str]) -> dict[str, object]:
    """Create one product via the API and return its JSON body."""
    sku = f"DEL-{uuid.uuid4().hex[:8]}"
    r = client.post(f"{PREFIX}/products/", headers=headers, json=_product_body(sku))
    assert r.status_code == 200
    return dict(r.json())


def test_superuser_deletes_fresh_product(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    product = _create_product(client, superuser_token_headers)
    product_id = product["id"]

    r = client.delete(
        f"{PREFIX}/products/{product_id}", headers=superuser_token_headers
    )
    assert r.status_code == 204

    listed = client.get(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        params={"q": product["sku"]},
    )
    assert listed.status_code == 200
    assert listed.json()["data"] == []


def test_delete_removes_price_history_rows(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """A price edit writes PriceChange children; they must not block the delete."""
    product = _create_product(client, superuser_token_headers)
    product_id = product["id"]
    patched = client.patch(
        f"{PREFIX}/products/{product_id}",
        headers=superuser_token_headers,
        json={"retail_price_thb": "1500.00"},
    )
    assert patched.status_code == 200
    history = client.get(
        f"{PREFIX}/products/{product_id}/price-history",
        headers=superuser_token_headers,
    )
    assert len(history.json()) >= 1

    r = client.delete(
        f"{PREFIX}/products/{product_id}", headers=superuser_token_headers
    )
    assert r.status_code == 204


def test_cannot_delete_product_with_stock(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    product = _create_product(client, superuser_token_headers)
    product_id = str(product["id"])
    _receive_quantity(db, product_id)

    r = client.delete(
        f"{PREFIX}/products/{product_id}", headers=superuser_token_headers
    )
    assert r.status_code == 409
    assert "history" in r.json()["detail"].lower()

    listed = client.get(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        params={"q": product["sku"]},
    )
    assert listed.json()["count"] == 1


def test_bkk_admin_cannot_delete_product(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    bkk_admin_token_headers: dict[str, str],
) -> None:
    product = _create_product(client, superuser_token_headers)

    r = client.delete(
        f"{PREFIX}/products/{product['id']}", headers=bkk_admin_token_headers
    )
    assert r.status_code == 403


def test_staff_cannot_delete_product(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
) -> None:
    product = _create_product(client, superuser_token_headers)

    r = client.delete(
        f"{PREFIX}/products/{product['id']}", headers=staff_token_headers
    )
    assert r.status_code == 403


def test_delete_unknown_product_404(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.delete(
        f"{PREFIX}/products/{uuid.uuid4()}", headers=superuser_token_headers
    )
    assert r.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run from the repo root:

```bash
bash scripts/test.sh -k "delete_product or deletes_fresh or delete_removes or delete_unknown"
```

Expected: all six FAIL with 405 Method Not Allowed (the route does not exist yet), not 403/404.

**Trap — read this before believing a green run.** `docker compose up` runs a stale image that does not contain your new test file, which produces a false pass. Use `scripts/test.sh` (or `docker compose watch`), and if a result looks surprising, confirm the container actually has your code:

```bash
docker compose exec backend grep -c "test_superuser_deletes_fresh_product" /app/tests/api/routes/test_products.py
```

- [ ] **Step 3: Add `delete_product` to crud.py**

Insert immediately after `is_product_fresh` (which ends at line 611), before `products_fresh_ids`:

```python
def delete_product(*, session: Session, db_product: Product) -> None:
    """Hard-delete a product that has never entered the stock system.

    Callers MUST have checked ``is_product_fresh`` first — this function does
    not re-check. Its own ``PriceChange`` rows go with it (they are meaningless
    without the product, and are the only children a fresh product is expected
    to have). Any other table still referencing the product surfaces as an
    IntegrityError, which is reported as 409 rather than a 500 — most plausibly
    a ``PricingOverrideRequest``, whose product_id the freshness check does not
    cover.
    """
    for stale in session.exec(
        select(PriceChange).where(PriceChange.product_id == db_product.id)
    ).all():
        session.delete(stale)
    session.delete(db_product)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Product has stock history and cannot be deleted",
        )
```

No new imports are needed: `select`, `Session`, `IntegrityError`, `HTTPException`, `PriceChange`, and `Product` are all already imported in `crud.py`. The select-then-`session.delete` loop (rather than a bulk `delete()` statement) matches the only other delete in this file, at line 3870 — a fresh product has at most a handful of price-change rows, so there is nothing to optimize here.

- [ ] **Step 4: Add the endpoint to products.py**

Add `get_current_active_superuser` to the existing `from app.api.deps import ...` line (line 7), and `status` to the `from fastapi import ...` line (line 4). Then append after `set_min_stock_level`:

```python
@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(get_current_active_superuser)],
)
def delete_product(*, session: SessionDep, product_id: uuid.UUID) -> Response:
    """Superuser-only hard delete, allowed only while the product has never
    entered the stock system (same condition that keeps its SKU editable).
    Anything with stock or sales stays and is retired via is_active instead."""
    db_product = crud.get_product(session=session, product_id=product_id)
    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")
    if not crud.is_product_fresh(session=session, product_id=product_id):
        raise HTTPException(
            status_code=409,
            detail="Product has stock history and cannot be deleted",
        )
    crud.delete_product(session=session, db_product=db_product)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

The freshness re-check here is authoritative. The `is_fresh` flag sent to clients is a rendering hint and is never trusted.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
bash scripts/test.sh -k "delete_product or deletes_fresh or delete_removes or delete_unknown"
```

Expected: 6 passed.

- [ ] **Step 6: Run the full backend suite and lint**

```bash
bash scripts/test.sh
cd backend && uv run ruff check . && uv run mypy app
```

Expected: no new failures. Three failures are known and pre-existing on `dev` (two stale redaction sweeps and one date-dependent July-2026 report test), plus occasional ordering flakes on catalog tests that pass on re-run. Compare failure *names* against a run on `dev`, not counts. ruff and mypy must be clean.

- [ ] **Step 7: Commit**

```bash
git add backend/app/crud.py backend/app/api/routes/products.py backend/tests/api/routes/test_products.py
git commit -m "feat(products): superuser-only delete for never-stocked products"
```

---

### Task 2: Frontend — `canDeleteProduct` predicate

**Files:**
- Modify: `frontend/src/lib/product-edit.ts` (add after `canSaveProduct`, line 52)
- Test: `frontend/src/lib/product-edit.test.ts` (append)

**Interfaces:**
- Consumes: `ProductPublic` from `@/client/types.gen` (its `is_fresh?: boolean` field).
- Produces: `canDeleteProduct(product: ProductPublic, isSuperuser: boolean): boolean`, consumed by Task 3.

There is no jsdom and no React Testing Library in this repo, so component rendering cannot be unit-tested. Extracting the rule into a pure predicate — exactly as `canSaveProduct` already is — puts the part that can actually be wrong under test with the runner that already exists.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/lib/product-edit.test.ts`. `baseProduct` is already defined at the top of that file (`is_fresh: true`); add `canDeleteProduct` to the existing import block from `"./product-edit"`.

```ts
describe("canDeleteProduct", () => {
  it("allows a superuser to delete a fresh product", () => {
    expect(canDeleteProduct(baseProduct, true)).toBe(true)
  })

  it("refuses a non-superuser even on a fresh product", () => {
    expect(canDeleteProduct(baseProduct, false)).toBe(false)
  })

  it("refuses a superuser once the product has stock history", () => {
    expect(canDeleteProduct({ ...baseProduct, is_fresh: false }, true)).toBe(
      false,
    )
  })

  it("refuses when is_fresh is absent, rather than assuming fresh", () => {
    const { is_fresh, ...withoutFlag } = baseProduct
    void is_fresh
    expect(canDeleteProduct(withoutFlag, true)).toBe(false)
  })
})
```

The last case matters: `is_fresh` is optional on `ProductPublic`, and a backend schema regression that drops it must fail closed. This mirrors the same fail-safe reasoning documented in `frontend/src/hooks/useRole.ts`.

- [ ] **Step 2: Run the test to verify it fails**

From `frontend/`:

```bash
bun run test:unit
```

Expected: FAIL — `canDeleteProduct` is not exported from `./product-edit`.

- [ ] **Step 3: Write the implementation**

Add to `frontend/src/lib/product-edit.ts`, directly after `canSaveProduct`:

```ts
/**
 * Delete is superuser-only and limited to products that never entered the
 * stock system — the backend enforces both and is authoritative. `is_fresh`
 * absent means "unknown", which fails closed (same rule as roleFlags).
 */
export function canDeleteProduct(
  product: ProductPublic,
  isSuperuser: boolean,
): boolean {
  return isSuperuser && product.is_fresh === true
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
bun run test:unit
```

Expected: PASS, with the pre-existing tests in this file still passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/product-edit.ts frontend/src/lib/product-edit.test.ts
git commit -m "feat(products): canDeleteProduct visibility predicate"
```

---

### Task 3: Frontend — regenerate the SDK and wire the two-step delete button

**Files:**
- Regenerate: `frontend/src/client/**` (via script — never hand-edit)
- Modify: `frontend/src/components/products/EditProductDialog.tsx` (imports at lines 1-31; footer at lines 263-277)

**Interfaces:**
- Consumes: `canDeleteProduct(product, isSuperuser)` from Task 2; `ProductsService.deleteProduct({ productId })` from the regenerated SDK (Task 1's endpoint); `useRole()` from `@/hooks/useRole`; the `showSuccessToast` / `showErrorToast` / `handleError` trio already imported by this file.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Regenerate the SDK**

The backend must be running for its OpenAPI schema to include the new route. From the repo root:

```bash
bash scripts/generate-client.sh
```

- [ ] **Step 2: Verify the generated method exists**

```bash
grep -n "deleteProduct" frontend/src/client/sdk.gen.ts
```

Expected: a `deleteProduct` method taking `{ productId }`. If it is missing, the backend serving the schema is stale — rebuild it and re-run Step 1 before continuing.

- [ ] **Step 3: Add the delete mutation and confirm state to `EditProductDialog`**

Add to the imports at the top of the file:

```ts
import { useEffect, useId, useRef, useState } from "react"
import { canDeleteProduct } from "@/lib/product-edit"   // add to the existing "@/lib/product-edit" import block
import { useRole } from "@/hooks/useRole"
```

Inside the component, after the existing `mutation` (which ends at line 175), add:

```tsx
  const { isSuperuser } = useRole()
  const [confirmingDelete, setConfirmingDelete] = useState(false)

  // A stray first click must not leave a live confirm sitting in the footer.
  useEffect(() => {
    if (!confirmingDelete) return
    const t = setTimeout(() => setConfirmingDelete(false), 4000)
    return () => clearTimeout(t)
  }, [confirmingDelete])

  const deleteMutation = useMutation({
    mutationFn: () => ProductsService.deleteProduct({ productId: product.id }),
    onSuccess: () => {
      showSuccessToast("Product deleted")
      onClose()
    },
    // A 409 here means the product gained stock in another tab since this
    // dialog rendered; the backend's message is the right thing to show.
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["products"] })
    },
  })
```

- [ ] **Step 4: Replace the footer**

Replace lines 263-277 (the whole `<DialogFooter>` block) with:

```tsx
        <DialogFooter className="sm:justify-between">
          {canDeleteProduct(product, isSuperuser) ? (
            <LoadingButton
              type="button"
              variant={confirmingDelete ? "destructive" : "outline"}
              loading={deleteMutation.isPending}
              disabled={mutation.isPending}
              onClick={() => {
                if (confirmingDelete) deleteMutation.mutate()
                else setConfirmingDelete(true)
              }}
            >
              {confirmingDelete ? "Click again to delete" : "Delete"}
            </LoadingButton>
          ) : (
            <span />
          )}
          <div className="flex flex-col-reverse gap-2 sm:flex-row">
            <DialogClose asChild>
              <Button
                variant="outline"
                disabled={mutation.isPending || deleteMutation.isPending}
              >
                Cancel
              </Button>
            </DialogClose>
            <LoadingButton
              type="button"
              loading={mutation.isPending}
              disabled={
                !canSaveProduct(draft) || isUnchanged || deleteMutation.isPending
              }
              onClick={() => mutation.mutate()}
            >
              Save
            </LoadingButton>
          </div>
        </DialogFooter>
```

The empty `<span />` keeps Save right-aligned under `justify-between` when the delete button is absent. Delete sits at the opposite end of the footer from Save, so a misclick on one cannot hit the other.

- [ ] **Step 5: Verify types, lint, and unit tests**

From `frontend/`:

```bash
bunx tsc --noEmit
bun run test:unit
```

Then from the repo root:

```bash
bun run lint
```

Expected: no type errors, unit tests pass, lint clean. Biome may reformat unrelated files repo-wide — that churn is cosmetic; stage only the files this task touched.

- [ ] **Step 6: Verify by hand in the running app**

Start the stack with `docker compose watch`, sign in as a superuser, and check all four states:

1. Open a product with no stock → **Delete** is present. Click once → it turns red and reads "Click again to delete". Wait 5 seconds → it reverts to "Delete".
2. Click twice → toast "Product deleted", dialog closes, the row is gone from the list.
3. Open a product that has been received into stock → no Delete button at all (its SKU field is also locked — same `is_fresh` rule).
4. Sign in as a BKK_ADMIN → no Delete button on any product.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/client frontend/src/components/products/EditProductDialog.tsx
git commit -m "feat(products): two-step delete button in the edit dialog"
```

---

### Task 4: Review and PR

**Files:** none modified — this task gates the work.

- [ ] **Step 1: Re-read the diff**

```bash
git diff dev...HEAD
```

Confirm: no file under `backend/app/alembic/` changed, no change to `backend/app/models.py`, and nothing under `frontend/src/client/` was hand-edited (its only diff should be the generated `deleteProduct` additions).

- [ ] **Step 2: Run the code review skill**

Use `superpowers:requesting-code-review`. This change touches deletion of catalog data behind a permission boundary, so also dispatch `ecc:database-reviewer` and `ecc:security-reviewer` per the project's high-risk rule in CLAUDE.md.

- [ ] **Step 3: Address findings, then open the PR**

Use `superpowers:finishing-a-development-branch`, then the `create-pr` skill. Target branch is `dev` — never `master`.

---

## Correction note (2026-08-08, during execution)

Two things the plan got wrong, both caught by running the tests rather than by reading:

1. **A grant migration is required.** The least-privilege `castranova_app` role holds no DELETE privilege, so the endpoint died at commit with `InsufficientPrivilege`. Migration `m037` (`a1b2c3d4e5f7`) adds `GRANT DELETE ON product`, following m034's precedent. Grants only — no schema change.
2. **Products with price history cannot be deleted at all.** `pricechange` is one of m026's `LEDGERS` and carries m021's `reject_ledger_mutation` trigger, so the planned "delete the `PriceChange` children first" is refused by the database by design. The endpoint now returns 409 for a re-priced product, `crud.delete_product` deletes only the product row, and `crud.product_has_price_history()` is the new gate. User-approved on 2026-08-08 over weakening the trigger.

Also: `scripts/test.sh` cannot run these tests. The backend Dockerfile copies `app/`, `scripts/`, and `pyproject.toml` but **not** `tests/`, and `compose watch` performs no initial sync — so the container never receives the test files and pytest exits with "file or directory not found: tests/". Use `docker compose cp ./backend/tests backend:/app/backend/tests` (and the same for `./backend/app` after each edit), then `docker compose exec -T backend python -m pytest tests/...`. Run docker commands through PowerShell; Git Bash mangles `/app/...` into a Windows path.

## Notes on what this plan deliberately does not do

- **No Playwright spec.** The E2E suite needs the full stack and carries 17 known pre-existing failures on `dev`; a button-visibility assertion is already covered by the pure predicate in Task 2 plus the four permission tests in Task 1. Add one later if delete grows a more complex flow.
- **No `ON DELETE CASCADE` migration** on `price_change.product_id`. It is the more idiomatic database answer but costs a migration and an FK rewrite for two lines of application code on a single path. Revisit if more child tables need the same treatment.
- **No audit entry.** The audit trail is derived from the movement ledgers, and a product eligible for deletion has no movements by definition.
- **No bulk delete, no list-view delete, no undo.**
