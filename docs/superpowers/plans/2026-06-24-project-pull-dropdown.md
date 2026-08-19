# Project-Pull Create Dropdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the barcode scanner on the project-pull *create* screen with a product dropdown + quantity stepper, so remote BKK management can raise stock requests without scanning.

**Architecture:** Frontend-only. The create panel picks a product from the existing `products` list and a quantity. QUANTITY products become one merged `PART` line; SERIALIZED products auto-claim the oldest N in-stock serials (via the existing `GET /dashboards/stock-on-hand/{product_id}/units` endpoint) into N `UNIT` lines. Both produce the exact line shapes `buildCreatePayload` and the backend already accept — no backend, migration, or SDK change. The warehouse *fulfill* panel keeps its scanner.

**Tech Stack:** React + TypeScript, TanStack Query/Router, shadcn/ui `Select`, generated `@hey-api` SDK, Playwright (test runner, incl. pure-logic specs).

## Global Constraints

- **Frontend-only.** No backend edits, no Alembic migration, no `bun run generate-client`.
- **Do not touch `PullFulfillPanel`** or the fulfill path — the scanner stays there.
- **Test runner is Playwright** for both pure-logic and E2E specs (no vitest in this repo). Pure-logic specs import from `src/lib/` and use `@playwright/test`'s `test`/`expect` (see `tests/audit.spec.ts`).
- **E2E runs `--workers=1`** (shared dev DB); seed via the Node-side SDK with random suffixes (see `tests/pulls.spec.ts`).
- **Lint/format: biome.** Run `bunx biome check src` before commits.
- **Accepted ceiling:** two concurrent create requests can auto-pick the same serial → one `UNIT` line settles `SHORT` at fulfillment (no substitution). Same race the scanner flow already tolerates. Mark the auto-pick site with a `ponytail:` comment naming the upgrade path (move serial-claim to fulfill time).

---

### Task 1: Pure cart helpers for dropdown adds

Additive only — `addScanToCreateCart` and its tests stay green here; they're removed in Task 2 once the scanner consumer is gone.

**Files:**
- Modify: `frontend/src/lib/pull-create.ts` (add two exports after `addScanToCreateCart`)
- Test: `frontend/tests/pull-create.spec.ts` (append new tests)

**Interfaces:**
- Consumes: existing `CreateLine` type from `pull-create.ts`.
- Produces:
  - `addPartToCreateCart(lines: CreateLine[], product: { productId: string; sku: string; modelName: string }, qty: number): CreateLine[]` — merges a QUANTITY product into a PART line keyed by sku; qty floored at 1.
  - `addUnitsToCreateCart(lines: CreateLine[], product: { productId: string; sku: string; modelName: string }, serials: string[]): CreateLine[]` — appends one UNIT line per serial, skipping serials already in the cart; returns the same array ref when nothing fresh.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/tests/pull-create.spec.ts`. Add the two new names to the existing import from `../src/lib/pull-create`:

```ts
import {
  addPartToCreateCart,
  addScanToCreateCart,
  addUnitsToCreateCart,
  buildCreatePayload,
  type CreateCatalogEntry,
  type CreateLine,
  removeCreateLine,
  setCreateQty,
} from "../src/lib/pull-create"
```

Then append these tests at the end of the file:

```ts
const PROD_PART = {
  productId: "prod-cable",
  sku: "SKU-CABLE",
  modelName: "HDMI Cable",
}
const PROD_UNIT = {
  productId: "prod-laptop",
  sku: "SKU-LAPTOP",
  modelName: "Laptop 14",
}

test("addPartToCreateCart appends then merges qty by sku", () => {
  let lines = addPartToCreateCart([], PROD_PART, 3)
  expect(lines).toEqual([
    {
      key: "SKU-CABLE",
      lineKind: "PART",
      productId: "prod-cable",
      sku: "SKU-CABLE",
      modelName: "HDMI Cable",
      requestedQty: 3,
    },
  ])
  lines = addPartToCreateCart(lines, PROD_PART, 2)
  expect(lines).toHaveLength(1)
  expect(lines[0].requestedQty).toBe(5)
})

test("addPartToCreateCart floors qty at 1", () => {
  expect(addPartToCreateCart([], PROD_PART, 0)[0].requestedQty).toBe(1)
  expect(addPartToCreateCart([], PROD_PART, 4.9)[0].requestedQty).toBe(4)
})

test("addUnitsToCreateCart appends one UNIT line per serial", () => {
  const lines = addUnitsToCreateCart([], PROD_UNIT, ["CN-A1", "CN-A2"])
  expect(lines).toHaveLength(2)
  expect(lines.map((l) => l.key)).toEqual(["CN-A1", "CN-A2"])
  expect(
    lines.every((l) => l.lineKind === "UNIT" && l.requestedQty === 1),
  ).toBe(true)
  expect(lines[0].unitSerial).toBe("CN-A1")
})

test("addUnitsToCreateCart skips serials already in the cart", () => {
  const lines = addUnitsToCreateCart([], PROD_UNIT, ["CN-A1"])
  // all-duplicate → same ref
  expect(addUnitsToCreateCart(lines, PROD_UNIT, ["CN-A1"])).toBe(lines)
  // partial overlap → only the fresh serial is appended
  const merged = addUnitsToCreateCart(lines, PROD_UNIT, ["CN-A1", "CN-A2"])
  expect(merged.map((l) => l.key)).toEqual(["CN-A1", "CN-A2"])
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && bunx playwright test tests/pull-create.spec.ts`
Expected: FAIL — `addPartToCreateCart`/`addUnitsToCreateCart` are not exported.

- [ ] **Step 3: Implement the helpers**

Append to `frontend/src/lib/pull-create.ts` (after `addScanToCreateCart`, before `setCreateQty`):

```ts
/** Merge a QUANTITY product into the cart as a PART line, keyed by sku. */
export function addPartToCreateCart(
  lines: CreateLine[],
  product: { productId: string; sku: string; modelName: string },
  qty: number,
): CreateLine[] {
  const add = Math.max(1, Math.floor(Number.isFinite(qty) ? qty : 1))
  const key = product.sku
  if (lines.some((l) => l.key === key)) {
    return lines.map((l) =>
      l.key === key ? { ...l, requestedQty: l.requestedQty + add } : l,
    )
  }
  return [
    ...lines,
    {
      key,
      lineKind: "PART",
      productId: product.productId,
      sku: product.sku,
      modelName: product.modelName,
      requestedQty: add,
    },
  ]
}

/**
 * Append one UNIT line per serial (keyed by serial), skipping serials already
 * in the cart. Returns the same array ref when nothing fresh is added.
 */
export function addUnitsToCreateCart(
  lines: CreateLine[],
  product: { productId: string; sku: string; modelName: string },
  serials: string[],
): CreateLine[] {
  const present = new Set(
    lines.filter((l) => l.lineKind === "UNIT").map((l) => l.key),
  )
  const fresh = serials.filter((s) => s.length > 0 && !present.has(s))
  if (fresh.length === 0) return lines
  return [
    ...lines,
    ...fresh.map(
      (serial): CreateLine => ({
        key: serial,
        lineKind: "UNIT",
        productId: product.productId,
        sku: product.sku,
        modelName: product.modelName,
        unitSerial: serial,
        requestedQty: 1,
      }),
    ),
  ]
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && bunx playwright test tests/pull-create.spec.ts`
Expected: PASS — all existing + 4 new tests green.

- [ ] **Step 5: Lint**

Run: `cd frontend && bunx biome check src/lib/pull-create.ts`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/pull-create.ts frontend/tests/pull-create.spec.ts
git commit -m "feat(pulls): cart helpers for dropdown item adds"
```

---

### Task 2: Swap create-panel scanner for product dropdown + qty

Removes the scanner from the create flow only and wires the dropdown. Drops the now-orphaned `addScanToCreateCart`/`CreateCatalogEntry` (their only consumer was create-mode scanning) and rewrites their tests onto the new helpers. Fulfill panel untouched.

**Files:**
- Modify: `frontend/src/components/pos/PullCreatePanel.tsx` (replace scanner block + props)
- Modify: `frontend/src/routes/_layout/pulls.tsx` (add-item handler, drop create-mode scan wiring)
- Modify: `frontend/src/lib/pull-create.ts` (remove `addScanToCreateCart`, `CreateCatalogEntry`, unused `ScanLookupResult` import)
- Modify: `frontend/tests/pull-create.spec.ts` (drop scan-based tests; rebuild remaining tests on the new helpers)

**Interfaces:**
- Consumes: `addPartToCreateCart`, `addUnitsToCreateCart` (Task 1); `DashboardsService.getStockOnHandUnits({ productId })` → `Array<UnitDrillRow>` (`{ castranova_barcode, ... }`); `ProductPublic` (`{ id, sku, model_name, tracking_mode? }`).
- Produces: `PullCreatePanel` props `{ products: ProductPublic[]; onAddItem: (productId: string, qty: number) => void; addNotice: string; isAdding: boolean }` replacing the old scan props.

- [ ] **Step 1: Rewrite `PullCreatePanel.tsx`**

Replace the file's imports, props interface, signature, and the Project→Notes→Scanner region. Keep the cart `<Table>`, qty steppers, remove buttons, and the "Create request" button exactly as they are.

New imports block (drop `ScanField`/`ScanFieldHandle`/`Ref`; add `useState`):

```tsx
import { ArrowLeft, Minus, Plus, Trash2 } from "lucide-react"
import { useId, useState } from "react"
import type { ProductPublic, ProjectPublic } from "@/client/types.gen"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectEmpty,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { CreateLine } from "@/lib/pull-create"
```

New props interface (replaces the old one):

```tsx
interface PullCreatePanelProps {
  projects: ProjectPublic[]
  projectId: string
  onProjectChange: (value: string) => void
  adminNotes: string
  onNotesChange: (value: string) => void
  products: ProductPublic[]
  onAddItem: (productId: string, qty: number) => void
  addNotice: string
  isAdding: boolean
  lines: CreateLine[]
  onQtyChange: (key: string, qty: number) => void
  onRemove: (key: string) => void
  onSubmit: () => void
  onBack: () => void
  isPending: boolean
}
```

New signature + local state (replaces the old destructure and `projectSelectId`/`notesId`/`canCreate` setup):

```tsx
export function PullCreatePanel({
  projects,
  projectId,
  onProjectChange,
  adminNotes,
  onNotesChange,
  products,
  onAddItem,
  addNotice,
  isAdding,
  lines,
  onQtyChange,
  onRemove,
  onSubmit,
  onBack,
  isPending,
}: PullCreatePanelProps) {
  const projectSelectId = useId()
  const notesId = useId()
  const itemSelectId = useId()
  const [selectedProductId, setSelectedProductId] = useState("")
  const [qty, setQty] = useState(1)
  const canCreate = projectId !== "" && lines.length > 0 && !isPending
```

Replace the `<ScanField ... />` element (old lines 108–133) with this selection block (the Project `Select` and Notes `Input` above it stay unchanged):

```tsx
      <div className="space-y-2">
        <Label htmlFor={itemSelectId}>Add item to request</Label>
        <div className="flex items-end gap-2">
          <Select
            value={selectedProductId}
            onValueChange={setSelectedProductId}
          >
            <SelectTrigger id={itemSelectId} className="w-full">
              <SelectValue placeholder="Select an item" />
            </SelectTrigger>
            <SelectContent>
              {products.length ? (
                products.map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.model_name} ({p.sku})
                  </SelectItem>
                ))
              ) : (
                <SelectEmpty>No items available</SelectEmpty>
              )}
            </SelectContent>
          </Select>
          <div className="flex items-center gap-1">
            <Button
              type="button"
              variant="outline"
              size="icon"
              className="size-11"
              disabled={qty <= 1}
              aria-label="Decrease quantity"
              onClick={() => setQty((q) => Math.max(1, q - 1))}
            >
              <Minus />
            </Button>
            <span className="num w-8 text-center" aria-hidden="true">
              {qty}
            </span>
            <Button
              type="button"
              variant="outline"
              size="icon"
              className="size-11"
              aria-label="Increase quantity"
              onClick={() => setQty((q) => q + 1)}
            >
              <Plus />
            </Button>
          </div>
          <Button
            type="button"
            className="h-11"
            disabled={selectedProductId === "" || isAdding}
            onClick={() => {
              onAddItem(selectedProductId, qty)
              setSelectedProductId("")
              setQty(1)
            }}
          >
            {isAdding ? "Adding…" : "Add"}
          </Button>
        </div>
        <p
          aria-live="polite"
          className="text-muted-foreground min-h-5 text-sm"
        >
          {addNotice}
        </p>
      </div>
```

- [ ] **Step 2: Rewire `pulls.tsx`**

In `frontend/src/routes/_layout/pulls.tsx`:

(a) Update the top-of-file imports. Add `DashboardsService` to the `@/client` import. Change the `@/lib/pull-create` import to drop `addScanToCreateCart`/`CreateCatalogEntry` and add the new helpers:

```tsx
import {
  addPartToCreateCart,
  addUnitsToCreateCart,
  buildCreatePayload,
  type CreateLine,
  removeCreateLine,
  setCreateQty,
} from "@/lib/pull-create"
```

(b) Delete the `createCatalog` `useMemo` (old lines 106–113) entirely — it was scanner-only.

(c) Add an `isAddingItem` state next to the other `useState` calls:

```tsx
  const [isAddingItem, setIsAddingItem] = useState(false)
```

(d) Replace the scan-routing `useEffect` (old lines 125–153) — it now handles **fulfill only**:

```tsx
  // Route each fulfill scan to the selected pull. A scan that matches no line
  // (and isn't NOT_FOUND) surfaces a context notice. Create mode no longer scans.
  useEffect(() => {
    if (!result) return
    if (selectedPull) {
      const next = applyScanToFulfill(fulfillDraft, selectedPull.lines, result)
      if (next === fulfillDraft && result.kind !== "NOT_FOUND") {
        setScanNotice("That part isn't on this request — scan a different one.")
      } else {
        setFulfillDraft(next)
        setScanNotice("")
      }
    }
    reset()
  }, [result, selectedPull, fulfillDraft, reset])
```

(e) Add the add-item handler (near the other `useCallback`s). The `addUnitsToCreateCart` call re-dedups against `prev`, so a slightly stale `createLines` read can't create duplicate keys:

```tsx
  const handleAddItem = useCallback(
    async (productId: string, qty: number) => {
      const product = (products ?? []).find((p) => p.id === productId)
      if (!product) return
      const meta = {
        productId: product.id,
        sku: product.sku,
        modelName: product.model_name,
      }
      if (product.tracking_mode === "SERIALIZED") {
        setIsAddingItem(true)
        try {
          // ponytail: auto-claim oldest N serials at create time. A concurrent
          // create can grab the same serial → one line settles SHORT at
          // fulfillment. Upgrade path: claim serials at fulfill time instead.
          const units = await DashboardsService.getStockOnHandUnits({
            productId,
          })
          const present = new Set(
            createLines.filter((l) => l.lineKind === "UNIT").map((l) => l.key),
          )
          const available = units
            .map((u) => u.castranova_barcode)
            .filter((s) => !present.has(s))
          const take = available.slice(0, qty)
          if (take.length === 0) {
            setScanNotice("No units in stock for that item.")
          } else {
            setCreateLines((prev) => addUnitsToCreateCart(prev, meta, take))
            setScanNotice(
              take.length < qty
                ? `Only ${take.length} in stock — added what's available.`
                : "",
            )
          }
        } catch {
          setScanNotice("Couldn't load stock for that item. Try again.")
        } finally {
          setIsAddingItem(false)
        }
      } else {
        setScanNotice("")
        setCreateLines((prev) => addPartToCreateCart(prev, meta, qty))
      }
    },
    [products, createLines],
  )
```

(f) Replace the create-mode scan props in the `<PullCreatePanel ... />` JSX. Remove `scanRef`, `onScan`, `isSearching`, `notFound`, `isError`, `scanNotice`; add:

```tsx
          products={products ?? []}
          onAddItem={handleAddItem}
          addNotice={scanNotice}
          isAdding={isAddingItem}
```

Leave the `<PullFulfillPanel ... />` block (which still uses `scanRef`/`onScan`/`scanNotice`) unchanged.

- [ ] **Step 3: Remove the orphaned scanner cart logic**

In `frontend/src/lib/pull-create.ts`: delete the `CreateCatalogEntry` type, the entire `addScanToCreateCart` function, and the now-unused `import type { ScanLookupResult } from "@/hooks/useScanLookup"` line. Keep `CreateLine`, `addPartToCreateCart`, `addUnitsToCreateCart`, `setCreateQty`, `removeCreateLine`, `buildCreatePayload`.

- [ ] **Step 4: Rebuild the pure-logic spec onto the new helpers**

Replace `frontend/tests/pull-create.spec.ts` entirely with:

```ts
import { expect, test } from "@playwright/test"
import {
  addPartToCreateCart,
  addUnitsToCreateCart,
  buildCreatePayload,
  removeCreateLine,
  setCreateQty,
} from "../src/lib/pull-create"

// Pure-logic coverage of the project-pull create cart (dropdown adds).

const PROD_PART = {
  productId: "prod-cable",
  sku: "SKU-CABLE",
  modelName: "HDMI Cable",
}
const PROD_UNIT = {
  productId: "prod-laptop",
  sku: "SKU-LAPTOP",
  modelName: "Laptop 14",
}

test("addPartToCreateCart appends then merges qty by sku", () => {
  let lines = addPartToCreateCart([], PROD_PART, 3)
  expect(lines).toEqual([
    {
      key: "SKU-CABLE",
      lineKind: "PART",
      productId: "prod-cable",
      sku: "SKU-CABLE",
      modelName: "HDMI Cable",
      requestedQty: 3,
    },
  ])
  lines = addPartToCreateCart(lines, PROD_PART, 2)
  expect(lines).toHaveLength(1)
  expect(lines[0].requestedQty).toBe(5)
})

test("addPartToCreateCart floors qty at 1", () => {
  expect(addPartToCreateCart([], PROD_PART, 0)[0].requestedQty).toBe(1)
  expect(addPartToCreateCart([], PROD_PART, 4.9)[0].requestedQty).toBe(4)
})

test("addUnitsToCreateCart appends one UNIT line per serial", () => {
  const lines = addUnitsToCreateCart([], PROD_UNIT, ["CN-A1", "CN-A2"])
  expect(lines).toHaveLength(2)
  expect(lines.map((l) => l.key)).toEqual(["CN-A1", "CN-A2"])
  expect(
    lines.every((l) => l.lineKind === "UNIT" && l.requestedQty === 1),
  ).toBe(true)
  expect(lines[0].unitSerial).toBe("CN-A1")
})

test("addUnitsToCreateCart skips serials already in the cart", () => {
  const lines = addUnitsToCreateCart([], PROD_UNIT, ["CN-A1"])
  expect(addUnitsToCreateCart(lines, PROD_UNIT, ["CN-A1"])).toBe(lines)
  const merged = addUnitsToCreateCart(lines, PROD_UNIT, ["CN-A1", "CN-A2"])
  expect(merged.map((l) => l.key)).toEqual(["CN-A1", "CN-A2"])
})

test("setCreateQty floors PART at 1; leaves UNIT untouched", () => {
  let lines = addPartToCreateCart([], PROD_PART, 1)
  lines = addUnitsToCreateCart(lines, PROD_UNIT, ["CN-A1"])
  expect(setCreateQty(lines, "SKU-CABLE", 0)[0].requestedQty).toBe(1)
  expect(setCreateQty(lines, "SKU-CABLE", 4.9)[0].requestedQty).toBe(4)
  // UNIT line (second) is unaffected by a qty change targeting it
  expect(setCreateQty(lines, "CN-A1", 9)[1].requestedQty).toBe(1)
})

test("removeCreateLine drops the matching line", () => {
  let lines = addPartToCreateCart([], PROD_PART, 1)
  lines = addUnitsToCreateCart(lines, PROD_UNIT, ["CN-A1"])
  expect(removeCreateLine(lines, "SKU-CABLE")).toEqual([
    expect.objectContaining({ key: "CN-A1" }),
  ])
})

test("buildCreatePayload shapes UNIT and PART lines; blank notes -> null", () => {
  let lines = addUnitsToCreateCart([], PROD_UNIT, ["CN-A1"])
  lines = addPartToCreateCart(lines, PROD_PART, 5)
  expect(buildCreatePayload(lines, "proj-1", "  ")).toEqual({
    project_id: "proj-1",
    admin_notes: null,
    lines: [
      { line_kind: "UNIT", product_id: "prod-laptop", unit_serial: "CN-A1" },
      { line_kind: "PART", product_id: "prod-cable", requested_qty: 5 },
    ],
  })
})
```

- [ ] **Step 5: Typecheck, lint, and run the pure-logic spec**

Run: `cd frontend && bunx tsc --noEmit`
Expected: no errors (confirms no dangling references to the removed exports/props).

Run: `cd frontend && bunx biome check src`
Expected: no errors.

Run: `cd frontend && bunx playwright test tests/pull-create.spec.ts`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/pos/PullCreatePanel.tsx frontend/src/routes/_layout/pulls.tsx frontend/src/lib/pull-create.ts frontend/tests/pull-create.spec.ts
git commit -m "feat(pulls): replace create scanner with item dropdown + qty"
```

---

### Task 3: E2E — create a pull via the dropdown

**Files:**
- Modify: `frontend/tests/pulls.spec.ts` (add one test in the existing `describe`)

**Interfaces:**
- Consumes: the create UI from Task 2 (labels: combobox `Project`, combobox `Add item to request`, buttons `Increase quantity`/`Add`/`Create request`/`New request`) and `DashboardsService.getStockOnHandUnits`.

- [ ] **Step 1: Add the failing E2E test**

Append inside the `test.describe("Pulls screen", ...)` block in `frontend/tests/pulls.spec.ts` (the file already seeds via the Node SDK; `ReceiptsService` is already imported). Add `DashboardsService` is **not** needed here — assertions read pulls back via `ProjectPullsService`.

```ts
  test("create via dropdown: QUANTITY + SERIALIZED → PENDING pull with PART and UNIT lines", async ({
    page,
  }) => {
    const r = rand()

    const partProduct = await ProductsService.createProduct({
      requestBody: {
        sku: `DPQ-${r}`,
        model_name: `Drop Part ${r}`,
        tracking_mode: "QUANTITY",
        retail_price_thb: "200.00",
        repair_price_thb: "80.00",
      },
    })
    const serialProduct = await ProductsService.createProduct({
      requestBody: {
        sku: `DPS-${r}`,
        model_name: `Drop Serial ${r}`,
        tracking_mode: "SERIALIZED",
        retail_price_thb: "900.00",
        repair_price_thb: "100.00",
      },
    })
    const supplier = await SuppliersService.createSupplier({
      requestBody: { name: `Drop Supplier ${r}` },
    })
    const customer = await CustomersService.createCustomer({
      requestBody: { name: `Drop Customer ${r}` },
    })
    const project = await ProjectsService.createProject({
      requestBody: {
        code: `DPRJ-${r}`,
        name: `Drop Project ${r}`,
        customer_id: customer.id,
      },
    })
    await ReceiptsService.receiveQuantity({
      requestBody: {
        product_id: partProduct.id,
        supplier_id: supplier.id,
        received_qty: 10,
        purchase_cost_thb: "60.00",
        idempotency_key: crypto.randomUUID(),
      },
    })
    const recv = await ReceiptsService.receiveSerialized({
      requestBody: {
        product_id: serialProduct.id,
        supplier_id: supplier.id,
        pieces: [
          { supplier_serial: `SN-${r}-1`, purchase_cost_thb: "500.00" },
          { supplier_serial: `SN-${r}-2`, purchase_cost_thb: "500.00" },
        ],
        idempotency_key: crypto.randomUUID(),
      },
    })
    const barcodes = recv.units.map((u) => u.castranova_barcode)

    await page.goto("/pulls")
    await page.getByRole("button", { name: "New request" }).click()

    await page.getByRole("combobox", { name: "Project" }).click()
    await page
      .getByRole("option", { name: `Drop Project ${r} (DPRJ-${r})` })
      .click()

    // QUANTITY item, qty 2 → PART line
    await page.getByRole("combobox", { name: "Add item to request" }).click()
    await page
      .getByRole("option", { name: `Drop Part ${r} (DPQ-${r})` })
      .click()
    await page.getByRole("button", { name: "Increase quantity" }).click()
    await page.getByRole("button", { name: "Add", exact: true }).click()
    await expect(page.getByText(`Drop Part ${r}`)).toBeVisible()

    // SERIALIZED item, qty 2 → two UNIT lines (oldest 2 serials auto-claimed)
    await page.getByRole("combobox", { name: "Add item to request" }).click()
    await page
      .getByRole("option", { name: `Drop Serial ${r} (DPS-${r})` })
      .click()
    await page.getByRole("button", { name: "Increase quantity" }).click()
    await page.getByRole("button", { name: "Add", exact: true }).click()
    await expect(page.getByText(barcodes[0])).toBeVisible()
    await expect(page.getByText(barcodes[1])).toBeVisible()

    // Scanner is gone from the create screen.
    await expect(page.getByText("Scan with camera")).toHaveCount(0)

    await page.getByRole("button", { name: "Create request" }).click()
    await expect(page.getByText("Request created.")).toBeVisible()

    // Backend: the seeded project now has a PENDING pull with 1 PART (qty 2)
    // and 2 UNIT lines bound to the two oldest serials.
    await expect
      .poll(
        async () => {
          const list = await ProjectPullsService.readProjectPulls({
            state: "PENDING",
          })
          return list.some((p) => p.project_id === project.id)
        },
        { timeout: 10_000, intervals: [500, 1_000] },
      )
      .toBe(true)

    const list = await ProjectPullsService.readProjectPulls({
      state: "PENDING",
    })
    const created = list.find((p) => p.project_id === project.id)
    expect(created).toBeTruthy()
    const partLines = created!.lines.filter((l) => l.line_kind === "PART")
    const unitLines = created!.lines.filter((l) => l.line_kind === "UNIT")
    expect(partLines).toHaveLength(1)
    expect(partLines[0].requested_qty).toBe(2)
    expect(unitLines).toHaveLength(2)
    expect(unitLines.map((l) => l.unit_serial).sort()).toEqual(
      [...barcodes].sort(),
    )
  })
```

- [ ] **Step 2: Run the E2E test**

Run: `cd frontend && bunx playwright test tests/pulls.spec.ts --workers=1`
Expected: PASS (both the existing fulfill test and the new create test).

> If the dev stack isn't running, start it first (`docker compose watch` per CLAUDE.md) so Playwright's webServer/API target is reachable.

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/pulls.spec.ts
git commit -m "test(pulls): e2e create request via item dropdown"
```

---

## Self-Review

- **Spec coverage:**
  - Dropdown replaces scanner on create only → Task 2 (panel + route); fulfill untouched (Global Constraints, Task 2 leaves `PullFulfillPanel` alone). ✓
  - QUANTITY → PART line → `addPartToCreateCart` (Task 1) + handler else-branch (Task 2). ✓
  - SERIALIZED → auto-claim oldest N serials → N UNIT lines → `addUnitsToCreateCart` + `getStockOnHandUnits` (Tasks 1–2). ✓
  - Error handling: 0 in stock / fewer than requested / fetch failure → handler notices (Task 2 step 2e). ✓
  - Accepted race ceiling marked with `ponytail:` comment (Task 2 step 2e). ✓
  - Tests: pure-logic (Tasks 1–2) + E2E both modes + scanner-absent assertion (Task 3). ✓
  - Frontend-only, no SDK regen, biome, workers=1 → Global Constraints + per-task commands. ✓
- **Placeholder scan:** none — every code/step is concrete.
- **Type consistency:** `addPartToCreateCart`/`addUnitsToCreateCart` signatures, `PullCreatePanel` prop names (`products`/`onAddItem`/`addNotice`/`isAdding`), and `handleAddItem(productId, qty)` match across Tasks 1–3. UNIT line key = serial = `castranova_barcode`, consistent with display (`line.unitSerial`) and the E2E assertion. ✓
