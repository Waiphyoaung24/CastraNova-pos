# Product Active/Inactive Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an admin retire and reactivate a product from the frontend, and show each product's status in the catalog.

**Architecture:** Frontend only. The backend, the generated SDK, and the active-only pickers already support `is_active` end to end — the control was simply never built. Task 1 threads `is_active` through the pure form logic in `lib/product-edit.ts`; Task 2 adds the Checkbox to the edit dialog and a Status column to the catalog, both mirroring the Users admin, which already solves this exact problem.

**Tech Stack:** React + TypeScript, Vite, TanStack Query/Router, shadcn/ui (Radix Checkbox), Tailwind v4, Playwright, biome.

**Spec:** `docs/superpowers/specs/2026-07-17-product-active-toggle-design.md`

## Global Constraints

- **No backend change, no Alembic migration, no `generate-client` run.** `ProductUpdate.is_active` (`backend/app/models.py:447`) and `ProductPublic.is_active` (via `ProductBase`, `backend/app/models.py:414`) already exist, and `frontend/src/client/types.gen.ts` already types `is_active` on both. Confirm the SDK does not drift; do not regenerate it.
- **Never hand-edit `frontend/src/client/` or `routeTree.gen.ts`.** (CLAUDE.md)
- **Use `Checkbox`, not a switch.** There is no `switch.tsx` in `frontend/src/components/ui/`. `EditUser.tsx:245` uses `Checkbox`; that is the house pattern.
- **Do not add a confirmation dialog, a stock guard on retire, or a status filter.** All three are explicitly out of scope in the spec.
- **Do not add `activeOnly` to the catalog query.** `products.tsx` keeps listing all products.
- **Surgical changes only** (CLAUDE.md §3): touch only the files each task names. `bun run lint` (biome) rewrites files in place across the whole repo — stage only this task's files and leave unrelated churn unstaged.
- **Copy the helper text verbatim:** `Retired products can't be sold, received, or used on tickets. Existing stock stays and can still be drained via Adjust.`
- **Status labels verbatim:** `Active` / `Inactive`. Checkbox label verbatim: `Active`.

## Environment Notes (read before running anything)

- Browserless specs (pure logic, no browser/stack): `cd frontend && bunx playwright test tests/<file> --no-deps`.
- Browser specs need the docker stack up (`docker compose watch`) and reuse the running Vite dev server on `:5173`. `global.setup.ts` truncates the dev DB and re-runs `prestart`, then `auth.setup.ts` logs in as the seeded superuser via `storageState` — specs do not log in themselves.
- **Stale-code trap:** `docker compose up` serves a stale image, and Compose syncs only on *change*, so files edited before the watch started never land. If a browser spec behaves impossibly, confirm the container/bundle actually has your symbol before trusting the result.
- `bun run lint` runs biome across the repo and may churn unrelated files. Stage only the files your task names.

---

### Task 1: Thread `is_active` through the pure edit logic

**Files:**
- Modify: `frontend/src/lib/product-edit.ts`
- Test: `frontend/tests/product-edit.spec.ts` (exists — extend it)

**Interfaces:**
- Consumes: `ProductPublic`, `ProductUpdate` from `@/client/types.gen` (both already carry `is_active`).
- Produces:
  - `ProductEditDraft` gains `isActive: boolean`.
  - `productToDraft(p: ProductPublic): ProductEditDraft` — sets `isActive: p.is_active ?? true`.
  - `buildProductUpdate(d: ProductEditDraft): ProductUpdate` — emits `is_active: d.isActive`.
  - `canSaveProduct(d: ProductEditDraft): boolean` — **unchanged**; a retired product is still valid.

**Heads-up:** three existing tests assert with exact `toEqual({...})` and the `draft()` helper builds a full draft. Adding a field to the draft **will break them** — that is expected, and updating them is part of this task, not collateral damage. `baseProduct` in that spec has no `is_active` key, which is why `productToDraft` must default it.

- [ ] **Step 1: Write the failing tests**

In `frontend/tests/product-edit.spec.ts`, add `isActive: true` to the `draft()` helper so it stays a complete `ProductEditDraft`:

```ts
const draft = (over: Partial<ProductEditDraft> = {}): ProductEditDraft => ({
  modelName: "Compressor",
  brand: "Hitec",
  category: "Machine",
  minStock: "5",
  retailPrice: "1800",
  repairPrice: "300",
  isActive: true,
  ...over,
})
```

Add `isActive: true` to the expectation in `productToDraft maps a product to editable strings`:

```ts
test("productToDraft maps a product to editable strings", () => {
  expect(productToDraft(baseProduct)).toEqual({
    modelName: "Compressor",
    brand: "Hitec",
    category: "Machine",
    minStock: "5",
    retailPrice: "1800.00",
    repairPrice: "300.00",
    isActive: true,
  })
})
```

Add `is_active: true` to both `buildProductUpdate` `toEqual` expectations:

```ts
test("buildProductUpdate trims and sends prices as strings", () => {
  expect(
    buildProductUpdate(draft({ retailPrice: " 1999 ", repairPrice: "350" })),
  ).toEqual({
    model_name: "Compressor",
    brand: "Hitec",
    category: "Machine",
    retail_price_thb: "1999",
    repair_price_thb: "350",
    default_min_stock_level: 5,
    is_active: true,
  })
})

test("buildProductUpdate sends null for cleared brand/category/min-stock", () => {
  expect(
    buildProductUpdate(draft({ brand: "  ", category: "", minStock: "" })),
  ).toEqual({
    model_name: "Compressor",
    brand: null,
    category: null,
    retail_price_thb: "1800",
    repair_price_thb: "300",
    default_min_stock_level: null,
    is_active: true,
  })
})
```

Then append these four new tests to the end of the file:

```ts
test("productToDraft carries is_active through", () => {
  expect(productToDraft({ ...baseProduct, is_active: false }).isActive).toBe(
    false,
  )
  expect(productToDraft({ ...baseProduct, is_active: true }).isActive).toBe(true)
})

test("productToDraft defaults a missing is_active to true", () => {
  // ProductPublic types is_active as optional (it has a server-side default),
  // so a missing value must read as active — never silently as retired.
  expect(productToDraft(baseProduct).isActive).toBe(true)
})

test("buildProductUpdate round-trips is_active", () => {
  expect(buildProductUpdate(draft({ isActive: false })).is_active).toBe(false)
  expect(buildProductUpdate(draft({ isActive: true })).is_active).toBe(true)
})

test("canSaveProduct allows saving a retired product", () => {
  // Retiring must not make the form unsavable.
  expect(canSaveProduct(draft({ isActive: false }))).toBe(true)
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
cd frontend && bunx playwright test tests/product-edit.spec.ts --no-deps
```

Expected: FAIL. TypeScript errors that `isActive` does not exist on `ProductEditDraft`, and/or assertion failures showing the received object lacks `isActive` / `is_active`.

- [ ] **Step 3: Write the implementation**

Replace `frontend/src/lib/product-edit.ts` with:

```ts
import type { ProductPublic, ProductUpdate } from "@/client/types.gen"

// Pure form logic for the admin product EDIT dialog. Mirrors product-create.ts:
// model name + both prices are required; prices are non-negative numbers sent as
// trimmed strings. Cleared optionals are sent as null so the change persists.
// is_active is always sent: retiring/reactivating is an ordinary edit here.

export interface ProductEditDraft {
  modelName: string
  brand: string
  category: string
  minStock: string
  retailPrice: string
  repairPrice: string
  isActive: boolean
}

function isValidPrice(value: string): boolean {
  const trimmed = value.trim()
  if (trimmed === "") return false
  const n = Number(trimmed)
  return Number.isFinite(n) && n >= 0
}

export function productToDraft(p: ProductPublic): ProductEditDraft {
  return {
    modelName: p.model_name,
    brand: p.brand ?? "",
    category: p.category ?? "",
    minStock:
      p.default_min_stock_level != null
        ? String(p.default_min_stock_level)
        : "",
    retailPrice: String(p.retail_price_thb),
    repairPrice: String(p.repair_price_thb),
    // Optional on ProductPublic (server-side default), so absence means active.
    isActive: p.is_active ?? true,
  }
}

export function canSaveProduct(d: ProductEditDraft): boolean {
  return (
    d.modelName.trim() !== "" &&
    isValidPrice(d.retailPrice) &&
    isValidPrice(d.repairPrice)
  )
}

export function buildProductUpdate(d: ProductEditDraft): ProductUpdate {
  const minStock = d.minStock.trim()
  const minStockNum = Number(minStock)
  const brand = d.brand.trim()
  const category = d.category.trim()
  return {
    model_name: d.modelName.trim(),
    brand: brand === "" ? null : brand,
    category: category === "" ? null : category,
    retail_price_thb: d.retailPrice.trim(),
    repair_price_thb: d.repairPrice.trim(),
    default_min_stock_level:
      minStock !== "" && Number.isFinite(minStockNum) && minStockNum >= 0
        ? minStockNum
        : null,
    is_active: d.isActive,
  }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
cd frontend && bunx playwright test tests/product-edit.spec.ts --no-deps
```

Expected: PASS — 11 passed (7 pre-existing, 4 new).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/product-edit.ts frontend/tests/product-edit.spec.ts
git commit -m "feat(products): thread is_active through the product edit draft

The edit dialog's PATCH never carried is_active, so a product's active flag
was unreachable from the UI. productToDraft now seeds it (defaulting a missing
value to active, since ProductPublic types it optional) and buildProductUpdate
always sends it. canSaveProduct is unchanged: a retired product is still valid.

The three existing toEqual assertions gained the new field by construction."
```

---

### Task 2: Add the Active checkbox and the catalog Status column

**Files:**
- Modify: `frontend/src/components/products/EditProductDialog.tsx`
- Modify: `frontend/src/routes/_layout/products.tsx`
- Test: `frontend/tests/product-active-toggle.spec.ts` (create)

**Interfaces:**
- Consumes from Task 1: `ProductEditDraft.isActive`, `productToDraft`, `buildProductUpdate`, `canSaveProduct` — all from `@/lib/product-edit`.
- Consumes: `Checkbox` from `@/components/ui/checkbox` (Radix `Checkbox.Root`; spreads `id`, takes `checked` and `onCheckedChange: (v: boolean | "indeterminate") => void`).
- Produces: no exported API. User-visible surface: a checkbox labelled `Active` in the Edit dialog, and a `Status` column in the catalog table.

**Why both files ship together:** the browser spec asserts the round trip — retire via the dialog, then read the result in the Status column. Neither half is observable without the other.

- [ ] **Step 1: Write the failing browser spec**

Create `frontend/tests/product-active-toggle.spec.ts`:

```ts
import { expect, test } from "@playwright/test"

// Browser E2E for retiring a product from the catalog (admin-only):
//   1. Create a throwaway SERIALIZED product — it starts Active.
//   2. Retire it via the Edit dialog's Active checkbox.
//   3. The catalog Status column must read Inactive.
//   4. It must vanish from Receive's serialized picker, which fetches
//      { activeOnly: true } — proving the flag reaches the real picker and
//      not just the form.
//   5. Reactivating brings it back (the flag is not one-way).
// Runs against the shared dev DB (reset by global.setup), authed as the
// seeded superuser via storageState — no explicit login needed.

/** Random suffix to dodge shared-dev-DB SKU collisions. */
const rand = () => Math.random().toString(36).slice(2, 8).toUpperCase()

test("an admin can retire a product and bring it back", async ({ page }) => {
  await page.goto("/products")

  // Create a throwaway SERIALIZED product. The create form lives behind the
  // "New product" dialog (ProductCreateDialog), so it must be opened first.
  const sku = `E2E-ACT-${rand()}`
  await page.getByRole("button", { name: "New product" }).click()
  const create = page.getByRole("dialog", { name: "New product" })
  await expect(create).toBeVisible()
  await create.getByLabel("SKU").fill(sku)
  await create.getByLabel("Model name").fill("E2E Retire Target")
  // Radix Select: the trigger carries the "Tracking" label; options are
  // portalled to the body, so query them off `page`, not the dialog. The
  // option text is the raw enum ("SERIALIZED"), not a prettified label.
  await create.getByLabel("Tracking").click()
  await page.getByRole("option", { name: "SERIALIZED" }).click()
  await create.getByLabel("Retail price (THB)").fill("1000")
  await create.getByLabel("Repair price (THB)").fill("200")
  await create.getByRole("button", { name: "Create product" }).click()

  const row = page.getByRole("row", { name: new RegExp(sku) })
  await expect(row).toBeVisible()
  // A new product starts active.
  await expect(row.getByText("Active", { exact: true })).toBeVisible()

  // Retire it via the Edit dialog.
  await row.getByRole("button", { name: "Edit" }).click()
  const dialog = page.getByRole("dialog", { name: /Edit product/ })
  await expect(dialog).toBeVisible()
  await dialog.getByLabel("Active").uncheck()
  await dialog.getByRole("button", { name: "Save" }).click()
  await expect(page.getByText("Product updated")).toBeVisible()

  // The catalog now reports it as retired.
  await expect(row.getByText("Inactive", { exact: true })).toBeVisible()

  // ...and the active-only serialized picker must no longer offer it.
  // The picker is an EntityCombobox with ariaLabel="Product"; its search box
  // placeholder uses a real ellipsis character, not three dots.
  await page.goto("/receive")
  await page.getByRole("combobox", { name: "Product" }).click()
  await page.getByPlaceholder("Search products…").fill(sku)
  await expect(page.getByRole("option", { name: new RegExp(sku) })).toHaveCount(
    0,
  )
  await page.keyboard.press("Escape")

  // Reactivating restores it — retiring is reversible.
  await page.goto("/products")
  await row.getByRole("button", { name: "Edit" }).click()
  await expect(dialog).toBeVisible()
  await dialog.getByLabel("Active").check()
  await dialog.getByRole("button", { name: "Save" }).click()
  await expect(page.getByText("Product updated")).toBeVisible()
  await expect(row.getByText("Active", { exact: true })).toBeVisible()
})
```

- [ ] **Step 2: Run the spec to verify it fails**

Ensure the stack is up (`docker compose watch`), then run:

```bash
cd frontend && bunx playwright test tests/product-active-toggle.spec.ts
```

Expected: FAIL at `row.getByText("Active", { exact: true })` — the catalog has no Status column yet.

The selectors above were verified against the current components on 2026-07-17 (`ProductCreateDialog.tsx:105,116,145,154,202`; `receive.tsx:218-232`; `EntityCombobox.tsx:106-107`). If a selector still misses, fix the **spec** to match the real accessible name — never change the app to suit the spec.

**Protect the seeded demo data:** the default run triggers `global.setup.ts`, which **truncates the dev database** and re-seeds via `prestart`. If the hand-seeded demo data is still needed, run with `E2E_SKIP_DB_RESET=1`:

```bash
cd frontend && E2E_SKIP_DB_RESET=1 bunx playwright test tests/product-active-toggle.spec.ts
```

- [ ] **Step 3: Add the Active checkbox to the Edit dialog**

In `frontend/src/components/products/EditProductDialog.tsx`, add the import:

```ts
import { Checkbox } from "@/components/ui/checkbox"
```

Add this component directly below the existing `EditField` function:

```tsx
/** The active/retired toggle plus its consequence note. Spans the grid. */
function ActiveField({
  checked,
  onChange,
}: {
  checked: boolean
  onChange: (v: boolean) => void
}) {
  const id = useId()
  return (
    <div className="space-y-2 sm:col-span-2">
      <div className="flex items-center gap-3">
        <Checkbox
          id={id}
          checked={checked}
          onCheckedChange={(v) => onChange(v === true)}
        />
        <Label htmlFor={id} className="font-normal">
          Active
        </Label>
      </div>
      <p className="text-muted-foreground text-xs">
        Retired products can't be sold, received, or used on tickets. Existing
        stock stays and can still be drained via Adjust.
      </p>
    </div>
  )
}
```

Then render it inside the dialog's `<div className="grid gap-4 py-2 sm:grid-cols-2">`, immediately after the "Repair price (THB)" `EditField` and before the closing `</div>`:

```tsx
          <ActiveField
            checked={draft.isActive}
            onChange={(v) => setDraft((prev) => ({ ...prev, isActive: v }))}
          />
```

Note: use `setDraft` directly as shown. The existing `patch` helper is typed `(key: keyof ProductEditDraft, value: string)` and cannot carry a boolean; do not widen it.

No other change is needed here — `isUnchanged` (`EditProductDialog.tsx:103`) compares the whole draft, so it picks up `isActive` for free, and the mutation, toast, `handleError`, and cache invalidation are already wired.

- [ ] **Step 4: Add the Status column to the catalog**

In `frontend/src/routes/_layout/products.tsx`, add the import:

```ts
import { cn } from "@/lib/utils"
```

Replace the `PRODUCT_WIDTHS` block (currently 9 entries summing to 100%) with a 10-entry version that still sums to 100%:

```ts
// Column widths in header order (SKU, Model, Brand, Category, Tracking,
// Status, Purchase, Retail, Repair, History); sum to 100%.
const PRODUCT_WIDTHS = [
  "11%",
  "15%",
  "8%",
  "9%",
  "9%",
  "8%",
  "8%",
  "8%",
  "8%",
  "16%",
]
```

Widen the table's `minWidth` to fit the extra column:

```tsx
              minWidth={1140}
```

Add the header cell immediately after `<TableHead>Tracking</TableHead>`:

```tsx
                  <TableHead>Status</TableHead>
```

Add the matching body cell immediately after the Tracking `<TableCell>` (the one containing the `Badge`), mirroring `Admin/columns.tsx:53-65`:

```tsx
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          "size-2 rounded-full",
                          p.is_active ? "bg-green-500" : "bg-gray-400",
                        )}
                      />
                      <span
                        className={p.is_active ? "" : "text-muted-foreground"}
                      >
                        {p.is_active ? "Active" : "Inactive"}
                      </span>
                    </div>
                  </TableCell>
```

- [ ] **Step 5: Run the spec to verify it passes**

```bash
cd frontend && bunx playwright test tests/product-active-toggle.spec.ts
```

Expected: PASS — 1 passed.

If it fails at the Receive picker step, confirm the running bundle actually contains your change (see Environment Notes) before debugging the app.

- [ ] **Step 6: Verify nothing else regressed**

```bash
cd frontend && bunx playwright test tests/product-edit.spec.ts tests/product-create.spec.ts --no-deps
cd frontend && bun run build
```

Expected: both browserless specs PASS; `bun run build` completes with no TypeScript errors.

**`product-edit-flow.spec.ts` is already failing before this work starts — do not chase it as a regression.** Verified on 2026-07-17 at `dev-kwg`: it fails at its line 22, `page.getByLabel("SKU").fill(sku)`, because it never opens the "New product" dialog that now houses the create form. It is stale, unrelated to this change, and out of scope here. If you want to confirm the state you inherited:

```bash
cd frontend && E2E_SKIP_DB_RESET=1 bunx playwright test tests/product-edit-flow.spec.ts --reporter=line
```

Expected: FAIL at line 22 — same before and after this task. Fixing it (open the dialog first, as `product-active-toggle.spec.ts` does) is a good separate commit, but it is **not** part of this plan.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/products/EditProductDialog.tsx frontend/src/routes/_layout/products.tsx frontend/tests/product-active-toggle.spec.ts
git commit -m "feat(products): retire/reactivate a product from the catalog UI

A product's is_active flag decides whether it can be sold, received, or used
on a ticket, but nothing in the frontend could set it — the flag was reachable
only by a hand-written PATCH. The catalog was silent about it too: retired
products were listed with no way to tell them from live ones.

Adds an Active checkbox to the Edit dialog and a Status column to the catalog,
both mirroring the Users admin (Admin/columns.tsx, EditUser.tsx), which already
solved this. Backend, SDK and the active-only pickers already supported it, so
this is frontend-only — no migration, no client regeneration.

Retiring with stock on hand stays allowed: it is the documented precondition
for draining discontinued stock via Adjust."
```

---

## Review

- [ ] **Run the specialist reviewers on the diff**

Per the spec: `ecc:react-reviewer` + `ecc:typescript-reviewer` via the Agent tool. This change is not append-only/FIFO/role-tiering code, so the high-risk `ecc:database-reviewer` + `ecc:security-reviewer` pair is **not** required.

- [ ] **Confirm the backend suite is untouched**

This is a frontend-only change, so it must not move the suite. Compare failure **names**, never the pass count. Three tests fail on a clean tree and are not regressions:
`test_staff_redaction_lock::test_staff_get_sweep_carries_no_financial_keys[/products/]`,
`…[/project-pulls]`, and `test_reports::test_adjacent_month_not_counted`.

```bash
docker compose exec -T backend python -m pytest -q 2>&1 | tail -5
```

## Out of scope — do not fix here

Both are recorded in the spec and in `notes.md`, and both are pre-existing:

- **FR-012 misses serialized purchases** (`crud.py:4419-4426` never joins `unit_id → Unit.product_id`).
- **Stock adjustments can restock a retired product** (`crud.py:2065` skips the guard for both signs of `quantity_delta`).
