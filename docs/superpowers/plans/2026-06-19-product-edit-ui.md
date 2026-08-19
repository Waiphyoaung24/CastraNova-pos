# Product Edit UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an admin product-edit dialog (launched per catalog row) so product details/prices can be changed, which makes the existing per-product price-history dialog populate.

**Architecture:** Frontend-only. A new pure helper (`lib/product-edit.ts`) builds the `ProductUpdate` payload and validates input; a new `EditProductDialog` component (useState + the helper, mirroring the page's create form) calls the existing admin `PATCH /products/{id}` via `ProductsService.updateProduct`, then invalidates the catalog and price-history queries. The catalog row gets an Edit button beside History.

**Tech Stack:** React + TypeScript, TanStack Query, shadcn/ui (Dialog/Input/Label/Button), generated SDK, Playwright (pure-logic unit specs + E2E). The backend `update_product` route + `PriceChange` recording already exist (no backend changes).

**Reference spec:** `docs/superpowers/specs/2026-06-19-product-edit-ui-design.md`

**Design refinement vs spec:** the dialog uses `useState` + the tested pure helper (like the create form already on this page) instead of react-hook-form/zod — simpler and consistent with `products.tsx`. Validation lives in the unit-tested `canSaveProduct`.

---

## File Structure

- `frontend/src/lib/product-edit.ts` — NEW. Pure: `ProductEditDraft`, `productToDraft`, `canSaveProduct`, `buildProductUpdate`. Mirrors `lib/product-create.ts`.
- `frontend/tests/product-edit.spec.ts` — NEW. Pure-logic unit tests (no browser), mirroring `tests/useRole.spec.ts`.
- `frontend/src/components/products/EditProductDialog.tsx` — NEW. The edit dialog + trigger button.
- `frontend/src/routes/_layout/products.tsx` — MODIFY (minimal): render `<EditProductDialog product={p} />` beside `<PriceHistoryDialog />` in the catalog row. **This file has unrelated uncommitted WIP — the controller isolates this edit (commit only this change).**
- `frontend/tests/product-edit-flow.spec.ts` — NEW. E2E: edit a price → History shows the change.

---

## Task 1: `product-edit.ts` pure helper + unit tests

**Files:**
- Create: `frontend/src/lib/product-edit.ts`
- Test: `frontend/tests/product-edit.spec.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/tests/product-edit.spec.ts`:

```ts
import { expect, test } from "@playwright/test"
import type { ProductPublic } from "../src/client/types.gen"
import {
  buildProductUpdate,
  canSaveProduct,
  type ProductEditDraft,
  productToDraft,
} from "../src/lib/product-edit"

const baseProduct: ProductPublic = {
  id: "p1",
  sku: "S001",
  model_name: "Compressor",
  brand: "Hitec",
  category: "Machine",
  tracking_mode: "QUANTITY",
  retail_price_thb: "1800.00",
  repair_price_thb: "300.00",
  default_min_stock_level: 5,
}

const draft = (over: Partial<ProductEditDraft> = {}): ProductEditDraft => ({
  modelName: "Compressor",
  brand: "Hitec",
  category: "Machine",
  minStock: "5",
  retailPrice: "1800",
  repairPrice: "300",
  ...over,
})

test("productToDraft maps a product to editable strings", () => {
  expect(productToDraft(baseProduct)).toEqual({
    modelName: "Compressor",
    brand: "Hitec",
    category: "Machine",
    minStock: "5",
    retailPrice: "1800.00",
    repairPrice: "300.00",
  })
})

test("productToDraft blanks null brand/category/min-stock", () => {
  const d = productToDraft({
    ...baseProduct,
    brand: null,
    category: null,
    default_min_stock_level: null,
  })
  expect(d.brand).toBe("")
  expect(d.category).toBe("")
  expect(d.minStock).toBe("")
})

test("canSaveProduct requires model name and valid prices", () => {
  expect(canSaveProduct(draft())).toBe(true)
  expect(canSaveProduct(draft({ modelName: "   " }))).toBe(false)
  expect(canSaveProduct(draft({ retailPrice: "" }))).toBe(false)
  expect(canSaveProduct(draft({ retailPrice: "-1" }))).toBe(false)
  expect(canSaveProduct(draft({ repairPrice: "abc" }))).toBe(false)
})

test("buildProductUpdate trims and sends prices as strings", () => {
  expect(buildProductUpdate(draft({ retailPrice: " 1999 ", repairPrice: "350" }))).toEqual({
    model_name: "Compressor",
    brand: "Hitec",
    category: "Machine",
    retail_price_thb: "1999",
    repair_price_thb: "350",
    default_min_stock_level: 5,
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
  })
})

test("buildProductUpdate drops an invalid min-stock to null", () => {
  expect(buildProductUpdate(draft({ minStock: "-3" })).default_min_stock_level).toBe(
    null,
  )
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && bun run test tests/product-edit.spec.ts`
Expected: FAIL — module `../src/lib/product-edit` does not exist.

- [ ] **Step 3: Implement the helper**

Create `frontend/src/lib/product-edit.ts`:

```ts
import type { ProductPublic, ProductUpdate } from "@/client/types.gen"

// Pure form logic for the admin product EDIT dialog. Mirrors product-create.ts:
// model name + both prices are required; prices are non-negative numbers sent as
// trimmed strings. Cleared optionals are sent as null so the change persists.

export interface ProductEditDraft {
  modelName: string
  brand: string
  category: string
  minStock: string
  retailPrice: string
  repairPrice: string
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
      p.default_min_stock_level != null ? String(p.default_min_stock_level) : "",
    retailPrice: String(p.retail_price_thb),
    repairPrice: String(p.repair_price_thb),
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
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && bun run test tests/product-edit.spec.ts`
Expected: PASS (6 tests).

- [ ] **Step 5: Typecheck + commit**

Run: `cd frontend && bunx tsc --noEmit`
Expected: PASS.

```bash
git add frontend/src/lib/product-edit.ts frontend/tests/product-edit.spec.ts
git commit -m "feat(products): add pure product-edit form helper + tests"
```

---

## Task 2: `EditProductDialog` component

**Files:**
- Create: `frontend/src/components/products/EditProductDialog.tsx`

- [ ] **Step 1: Implement the component**

Create `frontend/src/components/products/EditProductDialog.tsx`:

```tsx
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Pencil } from "lucide-react"
import { useId, useState } from "react"

import { type ProductPublic, ProductsService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import {
  buildProductUpdate,
  canSaveProduct,
  type ProductEditDraft,
  productToDraft,
} from "@/lib/product-edit"
import { handleError } from "@/utils"

/** One labelled text/number input row, matching the create form's Field. */
function EditField({
  label,
  value,
  onChange,
  type = "text",
  numeric = false,
  disabled = false,
}: {
  label: string
  value: string
  onChange?: (v: string) => void
  type?: string
  numeric?: boolean
  disabled?: boolean
}) {
  const id = useId()
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type={type}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange?.(e.target.value)}
        className={numeric ? "num" : undefined}
        {...(numeric ? { inputMode: "decimal" as const } : {})}
        {...(type === "number" ? { min: 0 } : {})}
      />
    </div>
  )
}

export function EditProductDialog({ product }: { product: ProductPublic }) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<ProductEditDraft>(() => productToDraft(product))
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  // Reseed the form from the latest product each time the dialog opens.
  function onOpenChange(next: boolean) {
    if (next) setDraft(productToDraft(product))
    setOpen(next)
  }

  function patch(key: keyof ProductEditDraft, value: string) {
    setDraft((prev) => ({ ...prev, [key]: value }))
  }

  const mutation = useMutation({
    mutationFn: () =>
      ProductsService.updateProduct({
        productId: product.id,
        requestBody: buildProductUpdate(draft),
      }),
    onSuccess: () => {
      showSuccessToast("Product updated")
      setOpen(false)
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["products"] })
      queryClient.invalidateQueries({ queryKey: ["price-history", product.id] })
    },
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button type="button" variant="outline" size="sm">
          <Pencil className="mr-1 size-4" />
          Edit
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Edit product — {product.sku}</DialogTitle>
        </DialogHeader>
        <div className="grid gap-4 py-2 sm:grid-cols-2">
          <EditField label="SKU" value={product.sku} disabled />
          <EditField
            label="Tracking"
            value={product.tracking_mode ?? "QUANTITY"}
            disabled
          />
          <EditField
            label="Model name"
            value={draft.modelName}
            onChange={(v) => patch("modelName", v)}
          />
          <EditField
            label="Brand"
            value={draft.brand}
            onChange={(v) => patch("brand", v)}
          />
          <EditField
            label="Category"
            value={draft.category}
            onChange={(v) => patch("category", v)}
          />
          <EditField
            label="Min stock level"
            value={draft.minStock}
            onChange={(v) => patch("minStock", v)}
            type="number"
            numeric
          />
          <EditField
            label="Retail price (THB)"
            value={draft.retailPrice}
            onChange={(v) => patch("retailPrice", v)}
            type="number"
            numeric
          />
          <EditField
            label="Repair price (THB)"
            value={draft.repairPrice}
            onChange={(v) => patch("repairPrice", v)}
            type="number"
            numeric
          />
        </div>
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline" disabled={mutation.isPending}>
              Cancel
            </Button>
          </DialogClose>
          <LoadingButton
            type="button"
            loading={mutation.isPending}
            disabled={!canSaveProduct(draft)}
            onClick={() => mutation.mutate()}
          >
            Save
          </LoadingButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
```

- [ ] **Step 2: Verify the trigger/util/hook imports exist**

Run:
```
cd frontend && grep -q "showSuccessToast" src/hooks/useCustomToast.ts && \
grep -q "export function handleError" src/utils.tsx 2>/dev/null || grep -rq "handleError" src/utils.* && \
ls src/components/ui/loading-button.tsx && echo OK
```
Expected: `OK` (these are the same imports AddUser/EditUser use; if `handleError` lives elsewhere, match AddUser.tsx's import exactly).

- [ ] **Step 3: Typecheck**

Run: `cd frontend && bunx tsc --noEmit`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/products/EditProductDialog.tsx
git commit -m "feat(products): add EditProductDialog"
```

---

## Task 3: Wire the Edit button into the catalog row

**Files:**
- Modify: `frontend/src/routes/_layout/products.tsx`

> **CONTROLLER NOTE — WIP isolation:** `products.tsx` has unrelated uncommitted WIP.
> Do NOT let a subagent `git add` the whole file. The controller performs this edit
> and commits ONLY this change using the established isolation procedure: back up the
> working copy, `git checkout HEAD -- products.tsx`, apply the edit below to the clean
> version, `git add` + commit, then restore the WIP copy and re-apply the edit so the
> WIP stays uncommitted in the working tree.

- [ ] **Step 1: Import the dialog**

Add to the imports in `frontend/src/routes/_layout/products.tsx`:

```ts
import { EditProductDialog } from "@/components/products/EditProductDialog"
```

- [ ] **Step 2: Render Edit beside History in the catalog row**

Replace the catalog row's History cell:

```tsx
                  <TableCell className="text-right">
                    <PriceHistoryDialog productId={p.id} sku={p.sku} />
                  </TableCell>
```

with:

```tsx
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      <EditProductDialog product={p} />
                      <PriceHistoryDialog productId={p.id} sku={p.sku} />
                    </div>
                  </TableCell>
```

- [ ] **Step 3: Typecheck + lint**

Run: `cd frontend && bunx tsc --noEmit && bunx biome check src/routes/_layout/products.tsx src/components/products/EditProductDialog.tsx src/lib/product-edit.ts`
Expected: PASS / clean.

- [ ] **Step 4: Commit (controller-isolated — only this file's Edit-button change)**

```bash
git add frontend/src/routes/_layout/products.tsx
git commit -m "feat(products): add Edit button to catalog rows"
```

---

## Task 4: E2E — edit a price, see it in history

**Files:**
- Create: `frontend/tests/product-edit-flow.spec.ts`

- [ ] **Step 1: Discover the E2E auth/setup pattern**

Run: `cd frontend && sed -n '1,30p' tests/roles.spec.ts`
Expected: shows the superuser `storageState`/setup the suite uses (admin session). Reuse the same mechanism; admin sees Products + Edit.

- [ ] **Step 2: Write the E2E spec**

Create `frontend/tests/product-edit-flow.spec.ts` (adapt selectors/auth to what Step 1 shows). It must create a product first (via the create form) so the test is self-contained, then edit its retail price and assert history:

```ts
import { expect, test } from "@playwright/test"

test("editing a product's retail price records it in price history", async ({
  page,
}) => {
  await page.goto("/products")

  // Create a throwaway product via the create form.
  const sku = `E2E-${Date.now()}`
  await page.getByLabel("SKU").fill(sku)
  await page.getByLabel("Model name").fill("E2E Edit Target")
  await page.getByLabel("Retail price (THB)").fill("1000")
  await page.getByLabel("Repair price (THB)").fill("200")
  await page.getByRole("button", { name: "Create product" }).click()

  // Open that product's row Edit dialog and change the retail price.
  const row = page.getByRole("row", { name: new RegExp(sku) })
  await row.getByRole("button", { name: "Edit" }).click()
  const dialog = page.getByRole("dialog", { name: new RegExp(`Edit product`) })
  const retail = dialog.getByLabel("Retail price (THB)")
  await retail.fill("1500")
  await dialog.getByRole("button", { name: "Save" }).click()
  await expect(page.getByText("Product updated")).toBeVisible()

  // Open History → it must now list the retail_price_thb change.
  await row.getByRole("button", { name: "History" }).click()
  const history = page.getByRole("dialog", { name: new RegExp("Price history") })
  await expect(history.getByText("retail_price_thb")).toBeVisible()
  await expect(history.getByText("1500", { exact: false })).toBeVisible()
})
```

- [ ] **Step 3: Run the E2E**

Run: `cd frontend && bun run test tests/product-edit-flow.spec.ts`
Expected: PASS against the running dev stack. If the stack/DB isn't running, that's an infra limit (report DONE_WITH_CONCERNS); do not weaken assertions to pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/tests/product-edit-flow.spec.ts
git commit -m "test(products): E2E edit price -> price history"
```

---

## Final verification

- [ ] **Step 1: Typecheck + lint + unit**

Run: `cd frontend && bunx tsc --noEmit && bun run test tests/product-edit.spec.ts`
Expected: PASS.

- [ ] **Step 2: Confirm no SDK regen needed**

Run: `cd frontend && grep -n "updateProduct" src/client/sdk.gen.ts`
Expected: present (no backend schema change → no `generate-client`).

- [ ] **Step 3: Confirm products.tsx WIP preserved uncommitted**

Run: `git -C /Users/waiphyoaung/Desktop/CastraNova-POS/CastraNova-pos status --short -- frontend/src/routes/_layout/products.tsx`
Expected: ` M ...products.tsx` (the WIP is still uncommitted; only the Edit-button change is committed).

---

## Notes / backlog (from the spec)

- Deactivating products (`is_active`), editing `specs`, changing tracking mode — out of scope.
- The `EditField` helper duplicates the create form's `Field` slightly; if a third
  consumer appears, extract a shared `LabeledInput`.
