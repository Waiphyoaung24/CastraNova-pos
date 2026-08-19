# Stock Table Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the clipped expander ellipsis, show supplier scope outside the quantity header, and order the desktop columns as SKU, Brand, Model, Category, In stock.

**Architecture:** Keep this as a surgical presentation-only change in the existing Stock route. Add an isolated Playwright regression that mocks authentication and Stock API responses, runs with project dependencies disabled, and therefore never invokes the shared-database reset.

**Tech Stack:** React 19, TypeScript, TanStack Query, Tailwind CSS v4, Playwright, Biome, Vite.

## Global Constraints

- Desktop order is Expand, SKU, Brand, Model, Category, In stock, Labels.
- The quantity header always reads `In stock`.
- A selected supplier renders `Showing stock from: <supplier name>` above the table.
- Mobile cards retain `from <supplier name>` or `in stock` captions and otherwise remain unchanged.
- Do not change API contracts, authorization, filtering, pagination, or inventory calculations.
- Do not run Playwright project dependencies or `frontend/tests/global.setup.ts` against the shared development database.

---

### Task 1: Polish the Stock table presentation

**Files:**
- Create: `frontend/tests/stock-table-polish.spec.ts`
- Modify: `frontend/src/routes/_layout/stock.tsx`

**Interfaces:**
- Consumes: the existing `SupplierOption`, `StockOnHandResponse`, `EntityCombobox`, `Badge`, and `ListTable` interfaces.
- Produces: no new exported interface; the existing `/stock` route renders the revised table and supplier context.

- [ ] **Step 1: Write isolated failing UI regressions**

Create `frontend/tests/stock-table-polish.spec.ts`:

```ts
import { expect, test } from "@playwright/test"

const admin = {
  email: "admin@example.test",
  is_active: true,
  is_superuser: true,
  role: "BKK_ADMIN",
  full_name: "Admin",
  id: "00000000-0000-4000-8000-000000000001",
}
const supplier = {
  id: "00000000-0000-4000-8000-000000000002",
  name: "TEST Comp",
}
const stock = {
  rows: [
    {
      product_id: "00000000-0000-4000-8000-000000000003",
      sku: "SKU-001",
      model_name: "Product",
      brand: "Brand",
      category: "Category",
      tracking_mode: "QUANTITY",
      quantity_on_hand: 1,
    },
  ],
  count: 1,
}

test.use({ storageState: { cookies: [], origins: [] } })

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem(
      "access_token",
      "e30.eyJleHAiOjk5OTk5OTk5OTl9.e30",
    )
  })
  await page.route("**/api/v1/users/me", (route) =>
    route.fulfill({ status: 200, json: admin }),
  )
  await page.route("**/api/v1/suppliers/options", (route) =>
    route.fulfill({ status: 200, json: [supplier] }),
  )
  await page.route("**/api/v1/dashboards/stock-on-hand*", (route) =>
    route.fulfill({ status: 200, json: stock }),
  )
})

test("the expander button fits without clipped overflow", async ({ page }) => {
  await page.goto("/stock")
  const cell = page.getByRole("button", { name: "Expand SKU-001" }).locator("..")
  expect(
    await cell.evaluate((element) => element.scrollWidth <= element.clientWidth),
  ).toBe(true)
})

test("desktop columns follow the requested order", async ({ page }) => {
  await page.goto("/stock")
  const labels = await page
    .locator('[data-slot="table-head"]')
    .allTextContents()
  expect(labels.map((label) => label.trim())).toEqual([
    "",
    "SKU",
    "Brand",
    "Model",
    "Category",
    "In stock",
    "",
  ])
})

test("supplier scope is shown above a short quantity header", async ({
  page,
}) => {
  await page.goto("/stock")
  await page.getByRole("combobox", { name: "Supplier filter" }).click()
  await page.getByText("TEST Comp", { exact: true }).click()

  await expect(page.getByText("Showing stock from: TEST Comp")).toBeVisible()
  await expect(
    page.getByRole("columnheader", { name: "In stock", exact: true }),
  ).toBeVisible()
})
```

- [ ] **Step 2: Run the isolated test to verify it fails for the intended reasons**

Run from `frontend/`:

```powershell
bunx playwright test tests/stock-table-polish.spec.ts --project=chromium --no-deps
```

Expected: three failures showing the expander cell overflows, Brand follows Model, and the supplier context is absent while the supplier is embedded in the header. The `--no-deps` flag is mandatory; output must not mention `global.setup.ts` or database reset.

- [ ] **Step 3: Implement the minimal presentation changes**

In `frontend/src/routes/_layout/stock.tsx`, keep semantic widths attached to their columns when reordering:

```ts
const STOCK_WIDTHS = ["5%", "14%", "15%", "23%", "15%", "10%", "18%"]
```

Delete the derived `inStockLabel`. Immediately after the filter controls, render supplier context only when selected:

```tsx
{selectedSupplier ? (
  <Badge variant="secondary" className="w-fit">
    Showing stock from: {selectedSupplier.name}
  </Badge>
) : null}
```

Order the headers as follows:

```tsx
<TableHead aria-label="Expand" />
<TableHead>SKU</TableHead>
<TableHead>Brand</TableHead>
<TableHead>Model</TableHead>
<TableHead>Category</TableHead>
<TableHead className="text-right">In stock</TableHead>
<TableHead aria-label="Labels" />
```

Order the matching row cells as follows, and narrow padding only on the expander cell:

```tsx
<TableCell className="px-1">
  <Button
    type="button"
    variant="ghost"
    size="icon"
    className="size-8"
    aria-label={isOpen ? `Collapse ${sku}` : `Expand ${sku}`}
    aria-expanded={isOpen}
    onClick={onToggle}
  >
    {isOpen ? <ChevronDown /> : <ChevronRight />}
  </Button>
</TableCell>
<TableCell className="num font-medium">{sku}</TableCell>
<TableCell className="text-muted-foreground">{brand ?? "—"}</TableCell>
<TableCell>{modelName}</TableCell>
<TableCell className="text-muted-foreground">{category ?? "—"}</TableCell>
<TableCell className="num text-right">{quantityOnHand}</TableCell>
<TableCell className="overflow-visible! text-right">
  {isQuantity ? (
    <PrintLabelButton target={{ kind: "sku", productId, sku }} />
  ) : null}
</TableCell>
```

Do not change `StockCard` or its `quantityCaption`.

- [ ] **Step 4: Run the isolated regression to verify it passes without database setup**

Run from `frontend/`:

```powershell
bunx playwright test tests/stock-table-polish.spec.ts --project=chromium --no-deps
```

Expected: `3 passed`; output contains no setup project or database-reset activity.

- [ ] **Step 5: Run frontend static verification**

Run from `frontend/`:

```powershell
bunx biome check src/routes/_layout/stock.tsx tests/stock-table-polish.spec.ts
bun run test:unit
bun run build
```

Expected: Biome reports both files clean, all unit tests pass, and the production build completes successfully. The existing chunk-size advisory is non-blocking.

- [ ] **Step 6: Check the scoped diff and commit**

Run from the repository root:

```powershell
git diff --check
git status --short
git add frontend/src/routes/_layout/stock.tsx frontend/tests/stock-table-polish.spec.ts
git commit -m "fix(stock): clarify supplier-scoped quantities"
```

Expected: no whitespace errors; only the two task files are staged. Preserve the unrelated untracked `.agents/skills/frontend-ui/`, `.codex/`, and `AGENTS.md` entries.
