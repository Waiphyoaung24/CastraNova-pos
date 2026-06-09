# Project-Pull Screen (`/pulls`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a frontend `/pulls` screen (staff + admin, online-only, no cost shown) covering all of FR-009: a pull queue, scan-assisted fulfill (staff+admin), and admin-only create + cancel.

**Architecture:** One `/pulls` route (`requireAuth`) orchestrating three composed presentational views (Queue / FulfillPanel / CreatePanel) plus three online-only mutations. All non-trivial logic lives in two pure, unit-tested libs (`pull-fulfill.ts`, `pull-create.ts`). Fulfill holds a draft `line_id → fulfilled_qty` **seeded with every line at 0** (the backend full-fills omitted lines, so every line must be sent explicitly). Create accumulates an editable scan cart and POSTs once.

**Tech Stack:** React + TypeScript, TanStack Router (file-based) + Query, generated `@hey-api` SDK, shadcn/ui, Tailwind v4, `@playwright/test` (pure-logic runner for lib tests).

**Spec:** `docs/superpowers/specs/2026-06-10-castranova-project-pull-screen-design.md`

**No backend changes. No `bun run generate-client`** (SDK already has `ProjectPullsService`/`ProjectsService`).

**Run all `bun`/`bunx` commands from `frontend/`.**

---

## File Structure

| File | Responsibility |
|---|---|
| `frontend/src/lib/pull-fulfill.ts` | **Create.** Pure fulfill-draft logic: seed, scan-apply, clamp, payload, projected state. |
| `frontend/tests/pull-fulfill.spec.ts` | **Create.** Unit tests for the above. |
| `frontend/src/lib/pull-create.ts` | **Create.** Pure create-cart logic: scan-add, qty, remove, payload. |
| `frontend/tests/pull-create.spec.ts` | **Create.** Unit tests for the above. |
| `frontend/src/components/pos/PullQueue.tsx` | **Create.** Queue list + state filter + admin new/cancel. |
| `frontend/src/components/pos/PullFulfillPanel.tsx` | **Create.** Selected pull lines + scan + qty steppers + submit. |
| `frontend/src/components/pos/PullCreatePanel.tsx` | **Create.** Project picker + scan cart + submit. |
| `frontend/src/routes/_layout/pulls.tsx` | **Create.** Route + queries + scan routing + 3 mutations + view switching. |
| `frontend/src/components/Sidebar/AppSidebar.tsx` | **Modify.** Add the Pulls nav entry. |
| `frontend/src/routeTree.gen.ts` | Auto-regenerated — never hand-edit. |

---

## Task 1: Pure fulfill logic — `lib/pull-fulfill.ts` (TDD)

**Files:**
- Create: `frontend/src/lib/pull-fulfill.ts`
- Test: `frontend/tests/pull-fulfill.spec.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/tests/pull-fulfill.spec.ts`:

```ts
import { expect, test } from "@playwright/test"
import type {
  ProjectPullLinePublic,
  SerialSearchResult,
  SkuSearchResult,
} from "../src/client/types.gen"
import type { ScanLookupResult } from "../src/hooks/useScanLookup"
import {
  applyScanToFulfill,
  buildFulfillPayload,
  type FulfillDraft,
  lineCap,
  projectedPullState,
  seedFulfillDraft,
  setLineFulfilledQty,
} from "../src/lib/pull-fulfill"

// Pure-logic coverage of the project-pull fulfill draft. No browser/React/backend
// — mirrors ticket-parts.spec.ts.

// --- Fixtures --------------------------------------------------------------

const UNIT_LINE: ProjectPullLinePublic = {
  id: "line-unit",
  line_kind: "UNIT",
  product_id: "prod-laptop",
  unit_serial: "CN-UNIT-1",
  requested_qty: null,
  fulfilled_qty: 0,
  line_state: "PENDING",
}

const PART_LINE: ProjectPullLinePublic = {
  id: "line-part",
  line_kind: "PART",
  product_id: "prod-cable",
  unit_serial: null,
  requested_qty: 3,
  fulfilled_qty: 0,
  line_state: "PENDING",
}

const LINES = [UNIT_LINE, PART_LINE]

const unitScan = (barcode: string): ScanLookupResult => ({
  kind: "UNIT",
  data: {
    castranova_barcode: barcode,
    product_id: "prod-laptop",
    sku: "SKU-LAPTOP",
    supplier_serial: "SUP-1",
    current_state: "IN_STOCK",
    movements: [],
  } satisfies SerialSearchResult,
})

const partScan = (productId: string): ScanLookupResult => ({
  kind: "PART",
  data: {
    sku: "SKU-CABLE",
    product_id: productId,
    tracking_mode: "QUANTITY",
    total_on_hand: 10,
    batches: [],
  } satisfies SkuSearchResult,
})

const NOT_FOUND: ScanLookupResult = { kind: "NOT_FOUND" }

// --- lineCap / seed --------------------------------------------------------

test("lineCap is 1 for UNIT and requested_qty for PART", () => {
  expect(lineCap(UNIT_LINE)).toBe(1)
  expect(lineCap(PART_LINE)).toBe(3)
})

test("seedFulfillDraft sets every line to 0", () => {
  expect(seedFulfillDraft(LINES)).toEqual({ "line-unit": 0, "line-part": 0 })
})

// --- applyScanToFulfill ----------------------------------------------------

test("UNIT scan matching unit_serial sets that line to 1", () => {
  const draft = seedFulfillDraft(LINES)
  expect(applyScanToFulfill(draft, LINES, unitScan("CN-UNIT-1"))).toEqual({
    "line-unit": 1,
    "line-part": 0,
  })
})

test("UNIT scan with no matching serial leaves draft unchanged (same ref)", () => {
  const draft = seedFulfillDraft(LINES)
  expect(applyScanToFulfill(draft, LINES, unitScan("CN-NOPE"))).toBe(draft)
})

test("PART scan matching product_id increments, clamped to cap", () => {
  let draft: FulfillDraft = seedFulfillDraft(LINES)
  draft = applyScanToFulfill(draft, LINES, partScan("prod-cable")) // 1
  draft = applyScanToFulfill(draft, LINES, partScan("prod-cable")) // 2
  draft = applyScanToFulfill(draft, LINES, partScan("prod-cable")) // 3
  draft = applyScanToFulfill(draft, LINES, partScan("prod-cable")) // capped at 3
  expect(draft["line-part"]).toBe(3)
})

test("PART scan with no matching product leaves draft unchanged (same ref)", () => {
  const draft = seedFulfillDraft(LINES)
  expect(applyScanToFulfill(draft, LINES, partScan("prod-gone"))).toBe(draft)
})

test("NOT_FOUND scan leaves draft unchanged (same ref)", () => {
  const draft = seedFulfillDraft(LINES)
  expect(applyScanToFulfill(draft, LINES, NOT_FOUND)).toBe(draft)
})

// --- setLineFulfilledQty ---------------------------------------------------

test("setLineFulfilledQty clamps to [0, cap] and floors", () => {
  const draft = seedFulfillDraft(LINES)
  expect(setLineFulfilledQty(draft, PART_LINE, 9)["line-part"]).toBe(3)
  expect(setLineFulfilledQty(draft, PART_LINE, -1)["line-part"]).toBe(0)
  expect(setLineFulfilledQty(draft, PART_LINE, 2.9)["line-part"]).toBe(2)
  expect(setLineFulfilledQty(draft, UNIT_LINE, 5)["line-unit"]).toBe(1)
})

// --- buildFulfillPayload (the contract guard) ------------------------------

test("buildFulfillPayload emits an explicit entry for EVERY line", () => {
  const draft = seedFulfillDraft(LINES) // all zero
  const payload = buildFulfillPayload(draft)
  expect(payload.lines).toHaveLength(2)
  expect(payload.lines).toEqual(
    expect.arrayContaining([
      { line_id: "line-unit", fulfilled_qty: 0 },
      { line_id: "line-part", fulfilled_qty: 0 },
    ]),
  )
})

// --- projectedPullState ----------------------------------------------------

test("projectedPullState is SHORT until all lines reach cap, then FULFILLED", () => {
  let draft = seedFulfillDraft(LINES)
  expect(projectedPullState(LINES, draft)).toBe("SHORT")
  draft = setLineFulfilledQty(draft, UNIT_LINE, 1)
  draft = setLineFulfilledQty(draft, PART_LINE, 3)
  expect(projectedPullState(LINES, draft)).toBe("FULFILLED")
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && bunx playwright test tests/pull-fulfill.spec.ts --reporter=line`
Expected: FAIL — module `../src/lib/pull-fulfill` not found.

- [ ] **Step 3: Write the implementation**

Create `frontend/src/lib/pull-fulfill.ts`:

```ts
import type {
  ProjectPullFulfill,
  ProjectPullLinePublic,
} from "@/client/types.gen"
import type { ScanLookupResult } from "@/hooks/useScanLookup"

// ---------------------------------------------------------------------------
// Pure fulfill-draft logic for the project-pull screen.
//
// The draft maps line_id -> fulfilled_qty and ALWAYS holds every line on the
// pull (seeded to 0). This is mandatory: crud.fulfill_project_pull FULL-fills a
// line that is OMITTED from the payload, so an unscanned line must be sent as an
// explicit 0 to settle SHORT. Nothing here references cost (pulls are cost-only).
// ---------------------------------------------------------------------------

export type FulfillDraft = Record<string, number>

/** Max fulfillable qty for a line: 1 for UNIT, requested_qty (or 0) for PART. */
export function lineCap(line: ProjectPullLinePublic): number {
  return line.line_kind === "UNIT" ? 1 : (line.requested_qty ?? 0)
}

/** Seed a draft with every line at 0 (required — see file header). */
export function seedFulfillDraft(lines: ProjectPullLinePublic[]): FulfillDraft {
  const draft: FulfillDraft = {}
  for (const line of lines) draft[line.id] = 0
  return draft
}

/**
 * Apply a scan to the draft.
 * UNIT: match the line whose unit_serial === scanned barcode → set qty 1.
 * PART: match the PART line whose product_id === scanned product → increment,
 *       clamped to lineCap.
 * No match, or NOT_FOUND → return the same draft reference unchanged.
 */
export function applyScanToFulfill(
  draft: FulfillDraft,
  lines: ProjectPullLinePublic[],
  scan: ScanLookupResult,
): FulfillDraft {
  if (scan.kind === "UNIT") {
    const barcode = scan.data.castranova_barcode
    const line = lines.find(
      (l) => l.line_kind === "UNIT" && l.unit_serial === barcode,
    )
    if (!line) return draft
    return { ...draft, [line.id]: 1 }
  }
  if (scan.kind === "PART") {
    const productId = scan.data.product_id
    const line = lines.find(
      (l) => l.line_kind === "PART" && l.product_id === productId,
    )
    if (!line) return draft
    const next = Math.min((draft[line.id] ?? 0) + 1, lineCap(line))
    return { ...draft, [line.id]: next }
  }
  return draft
}

/** Set a line's qty, clamped to [0, cap], floored. */
export function setLineFulfilledQty(
  draft: FulfillDraft,
  line: ProjectPullLinePublic,
  qty: number,
): FulfillDraft {
  const clamped = Math.max(
    0,
    Math.min(lineCap(line), Math.floor(Number.isFinite(qty) ? qty : 0)),
  )
  return { ...draft, [line.id]: clamped }
}

/** Build the fulfill payload — every draft entry sent explicitly (see header). */
export function buildFulfillPayload(draft: FulfillDraft): ProjectPullFulfill {
  return {
    lines: Object.entries(draft).map(([line_id, fulfilled_qty]) => ({
      line_id,
      fulfilled_qty,
    })),
  }
}

/** Preview: FULFILLED iff every line's drafted qty >= its cap, else SHORT. */
export function projectedPullState(
  lines: ProjectPullLinePublic[],
  draft: FulfillDraft,
): "FULFILLED" | "SHORT" {
  const allFull = lines.every((l) => (draft[l.id] ?? 0) >= lineCap(l))
  return allFull ? "FULFILLED" : "SHORT"
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && bunx playwright test tests/pull-fulfill.spec.ts --reporter=line`
Expected: PASS (10 logic tests + 1 auth setup = green).

- [ ] **Step 5: Lint + commit**

```bash
cd frontend && bunx biome check src/lib/pull-fulfill.ts tests/pull-fulfill.spec.ts
cd /Users/waiphyoaung/Desktop/CastraNova-POS/CastraNova-pos
git add frontend/src/lib/pull-fulfill.ts frontend/tests/pull-fulfill.spec.ts
git commit -m "feat(pulls): pure fulfill-draft logic (Task 5.3)"
```

(If biome reports fixable issues, run it with `--write`, then re-check before committing.)

---

## Task 2: Pure create-cart logic — `lib/pull-create.ts` (TDD)

**Files:**
- Create: `frontend/src/lib/pull-create.ts`
- Test: `frontend/tests/pull-create.spec.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/tests/pull-create.spec.ts`:

```ts
import { expect, test } from "@playwright/test"
import type {
  SerialSearchResult,
  SkuSearchResult,
} from "../src/client/types.gen"
import type { ScanLookupResult } from "../src/hooks/useScanLookup"
import {
  addScanToCreateCart,
  buildCreatePayload,
  type CreateCatalogEntry,
  type CreateLine,
  removeCreateLine,
  setCreateQty,
} from "../src/lib/pull-create"

// Pure-logic coverage of the project-pull create cart. Mirrors ticket-parts.spec.ts.

const CATALOG = new Map<string, CreateCatalogEntry>([
  ["SKU-LAPTOP", { productId: "prod-laptop", modelName: "Laptop 14" }],
  ["SKU-CABLE", { productId: "prod-cable", modelName: "HDMI Cable" }],
])

const unitScan = (barcode: string): ScanLookupResult => ({
  kind: "UNIT",
  data: {
    castranova_barcode: barcode,
    product_id: "prod-laptop",
    sku: "SKU-LAPTOP",
    supplier_serial: "SUP-1",
    current_state: "IN_STOCK",
    movements: [],
  } satisfies SerialSearchResult,
})

const partScan = (sku: string): ScanLookupResult => ({
  kind: "PART",
  data: {
    sku,
    product_id: CATALOG.get(sku)?.productId ?? "prod-unknown",
    tracking_mode: "QUANTITY",
    total_on_hand: 10,
    batches: [],
  } satisfies SkuSearchResult,
})

const NOT_FOUND: ScanLookupResult = { kind: "NOT_FOUND" }

test("UNIT scan appends a UNIT line keyed by barcode, qty 1", () => {
  const lines = addScanToCreateCart([], unitScan("CN-A1"), CATALOG)
  expect(lines).toEqual([
    {
      key: "CN-A1",
      lineKind: "UNIT",
      productId: "prod-laptop",
      sku: "SKU-LAPTOP",
      modelName: "Laptop 14",
      unitSerial: "CN-A1",
      requestedQty: 1,
    },
  ])
})

test("re-scanning the same UNIT barcode is a no-op (same ref)", () => {
  const lines = addScanToCreateCart([], unitScan("CN-A1"), CATALOG)
  expect(addScanToCreateCart(lines, unitScan("CN-A1"), CATALOG)).toBe(lines)
})

test("PART scan in catalog appends, re-scan increments requestedQty", () => {
  let lines = addScanToCreateCart([], partScan("SKU-CABLE"), CATALOG)
  lines = addScanToCreateCart(lines, partScan("SKU-CABLE"), CATALOG)
  expect(lines).toHaveLength(1)
  expect(lines[0]).toMatchObject({
    key: "SKU-CABLE",
    lineKind: "PART",
    productId: "prod-cable",
    requestedQty: 2,
  })
})

test("PART scan not in catalog leaves cart unchanged (same ref)", () => {
  const lines: CreateLine[] = []
  expect(addScanToCreateCart(lines, partScan("SKU-GONE"), CATALOG)).toBe(lines)
})

test("NOT_FOUND scan leaves cart unchanged (same ref)", () => {
  const lines: CreateLine[] = []
  expect(addScanToCreateCart(lines, NOT_FOUND, CATALOG)).toBe(lines)
})

test("setCreateQty floors PART at 1; leaves UNIT untouched", () => {
  let lines = addScanToCreateCart([], partScan("SKU-CABLE"), CATALOG)
  lines = addScanToCreateCart(lines, unitScan("CN-A1"), CATALOG)
  expect(setCreateQty(lines, "SKU-CABLE", 0)[0].requestedQty).toBe(1)
  expect(setCreateQty(lines, "SKU-CABLE", 4.9)[0].requestedQty).toBe(4)
  // UNIT line (second) is unaffected by a qty change targeting it
  expect(setCreateQty(lines, "CN-A1", 9)[1].requestedQty).toBe(1)
})

test("removeCreateLine drops the matching line", () => {
  let lines = addScanToCreateCart([], partScan("SKU-CABLE"), CATALOG)
  lines = addScanToCreateCart(lines, unitScan("CN-A1"), CATALOG)
  expect(removeCreateLine(lines, "SKU-CABLE")).toEqual([
    expect.objectContaining({ key: "CN-A1" }),
  ])
})

test("buildCreatePayload shapes UNIT and PART lines; blank notes -> null", () => {
  let lines = addScanToCreateCart([], unitScan("CN-A1"), CATALOG)
  lines = addScanToCreateCart(lines, partScan("SKU-CABLE"), CATALOG)
  lines = setCreateQty(lines, "SKU-CABLE", 5)
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

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && bunx playwright test tests/pull-create.spec.ts --reporter=line`
Expected: FAIL — module `../src/lib/pull-create` not found.

- [ ] **Step 3: Write the implementation**

Create `frontend/src/lib/pull-create.ts`:

```ts
import type {
  ProjectPullCreate,
  ProjectPullLineCreate,
} from "@/client/types.gen"
import type { ScanLookupResult } from "@/hooks/useScanLookup"

// ---------------------------------------------------------------------------
// Pure create-cart logic for the project-pull screen (admin create flow).
//
// UNIT scans become serialized request lines (keyed by barcode, qty 1). PART
// scans become quantity request lines (keyed by sku, qty merges). The catalog
// (sku -> {productId, modelName}) supplies display names. No cost anywhere.
// ---------------------------------------------------------------------------

/** Catalog entry keyed by sku, built from the products query. */
export type CreateCatalogEntry = {
  productId: string
  modelName: string
}

/** A request line in the create cart, keyed by barcode (UNIT) or sku (PART). */
export type CreateLine = {
  key: string
  lineKind: "UNIT" | "PART"
  productId: string
  sku: string
  modelName: string
  /** Present for UNIT lines (the scanned barcode). */
  unitSerial?: string
  /** Always 1 for UNIT; the requested amount for PART. */
  requestedQty: number
}

/**
 * Append a scanned item to the create cart, or merge it.
 * UNIT: keyed by barcode; re-scan is a no-op (same ref). Always added (a scanned
 *       unit is real); name falls back to its sku if absent from the catalog.
 * PART: keyed by sku; must be in the catalog, else unchanged (same ref); re-scan
 *       increments requestedQty.
 * NOT_FOUND: unchanged (same ref).
 */
export function addScanToCreateCart(
  lines: CreateLine[],
  scan: ScanLookupResult,
  catalog: Map<string, CreateCatalogEntry>,
): CreateLine[] {
  if (scan.kind === "UNIT") {
    const key = scan.data.castranova_barcode
    if (lines.some((l) => l.lineKind === "UNIT" && l.key === key)) return lines
    const entry = catalog.get(scan.data.sku)
    return [
      ...lines,
      {
        key,
        lineKind: "UNIT",
        productId: scan.data.product_id,
        sku: scan.data.sku,
        modelName: entry?.modelName ?? scan.data.sku,
        unitSerial: key,
        requestedQty: 1,
      },
    ]
  }
  if (scan.kind === "PART") {
    const entry = catalog.get(scan.data.sku)
    if (!entry) return lines
    const key = scan.data.sku
    if (lines.some((l) => l.key === key)) {
      return lines.map((l) =>
        l.key === key ? { ...l, requestedQty: l.requestedQty + 1 } : l,
      )
    }
    return [
      ...lines,
      {
        key,
        lineKind: "PART",
        productId: entry.productId,
        sku: scan.data.sku,
        modelName: entry.modelName,
        requestedQty: 1,
      },
    ]
  }
  return lines
}

/** Set a PART line's requestedQty (floored at 1). UNIT lines are left at 1. */
export function setCreateQty(
  lines: CreateLine[],
  key: string,
  qty: number,
): CreateLine[] {
  return lines.map((l) => {
    if (l.key !== key || l.lineKind === "UNIT") return l
    return {
      ...l,
      requestedQty: Math.max(1, Math.floor(Number.isFinite(qty) ? qty : 1)),
    }
  })
}

/** Remove the line with `key`. */
export function removeCreateLine(
  lines: CreateLine[],
  key: string,
): CreateLine[] {
  return lines.filter((l) => l.key !== key)
}

/** Build the create payload; blank notes -> null. */
export function buildCreatePayload(
  lines: CreateLine[],
  projectId: string,
  adminNotes: string,
): ProjectPullCreate {
  return {
    project_id: projectId,
    admin_notes: adminNotes.trim() === "" ? null : adminNotes,
    lines: lines.map(
      (l): ProjectPullLineCreate =>
        l.lineKind === "UNIT"
          ? {
              line_kind: "UNIT",
              product_id: l.productId,
              unit_serial: l.unitSerial ?? null,
            }
          : {
              line_kind: "PART",
              product_id: l.productId,
              requested_qty: l.requestedQty,
            },
    ),
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && bunx playwright test tests/pull-create.spec.ts --reporter=line`
Expected: PASS (8 logic tests + 1 auth setup = green).

- [ ] **Step 5: Lint + commit**

```bash
cd frontend && bunx biome check src/lib/pull-create.ts tests/pull-create.spec.ts
cd /Users/waiphyoaung/Desktop/CastraNova-POS/CastraNova-pos
git add frontend/src/lib/pull-create.ts frontend/tests/pull-create.spec.ts
git commit -m "feat(pulls): pure create-cart logic (Task 5.3)"
```

---

## Task 3: Queue component — `components/pos/PullQueue.tsx`

Presentational list. Read `frontend/src/components/pos/ScanCart.tsx` for Table/Button conventions and `frontend/src/components/ui/badge.tsx` to confirm the `Badge` variants (`default | secondary | destructive | outline`).

**Files:**
- Create: `frontend/src/components/pos/PullQueue.tsx`

- [ ] **Step 1: Write the component**

Create `frontend/src/components/pos/PullQueue.tsx`:

```tsx
import type { ProjectPullPublic, ProjectPullState } from "@/client/types.gen"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
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

/** State filter value: a concrete state, or ALL for the unfiltered queue. */
export type PullStateFilter = ProjectPullState | "ALL"

export const PULL_STATE_FILTERS: PullStateFilter[] = [
  "PENDING",
  "SHORT",
  "FULFILLED",
  "CANCELLED",
  "ALL",
]

interface PullQueueProps {
  pulls: ProjectPullPublic[]
  /** project_id -> "Name (CODE)" label. */
  projectLabels: Map<string, string>
  /** customer_id -> name. */
  customerLabels: Map<string, string>
  stateFilter: PullStateFilter
  isAdmin: boolean
  onStateFilterChange: (value: PullStateFilter) => void
  onSelect: (pull: ProjectPullPublic) => void
  onCancel: (pullId: string) => void
  onNew: () => void
  /** Disables actions while a cancel is in flight. */
  isCancelling: boolean
}

const STATE_VARIANT: Record<
  ProjectPullState,
  "default" | "secondary" | "destructive" | "outline"
> = {
  PENDING: "secondary",
  FULFILLED: "default",
  SHORT: "destructive",
  CANCELLED: "outline",
}

export function PullQueue({
  pulls,
  projectLabels,
  customerLabels,
  stateFilter,
  isAdmin,
  onStateFilterChange,
  onSelect,
  onCancel,
  onNew,
  isCancelling,
}: PullQueueProps) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <Select
          value={stateFilter}
          onValueChange={(v) => onStateFilterChange(v as PullStateFilter)}
        >
          <SelectTrigger className="w-44" aria-label="Filter by state">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PULL_STATE_FILTERS.map((s) => (
              <SelectItem key={s} value={s}>
                {s}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {isAdmin ? (
          <Button type="button" onClick={onNew}>
            New pull
          </Button>
        ) : null}
      </div>

      {pulls.length === 0 ? (
        <p className="text-muted-foreground py-8 text-center text-sm">
          No pulls for this filter.
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Project</TableHead>
              <TableHead>Customer</TableHead>
              <TableHead>Created</TableHead>
              <TableHead className="text-center">Lines</TableHead>
              <TableHead>State</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {pulls.map((pull) => {
              const cancellable =
                isAdmin &&
                (pull.state === "PENDING" || pull.state === "SHORT")
              return (
                <TableRow key={pull.id}>
                  <TableCell className="font-medium">
                    {projectLabels.get(pull.project_id) ?? pull.project_id}
                  </TableCell>
                  <TableCell>
                    {customerLabels.get(pull.customer_id) ?? pull.customer_id}
                  </TableCell>
                  <TableCell className="num text-xs">
                    {new Date(pull.created_at).toLocaleDateString()}
                  </TableCell>
                  <TableCell className="num text-center">
                    {pull.lines.length}
                  </TableCell>
                  <TableCell>
                    <Badge variant={STATE_VARIANT[pull.state]}>
                      {pull.state}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => onSelect(pull)}
                      >
                        Open
                      </Button>
                      {cancellable ? (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="text-destructive"
                          disabled={isCancelling}
                          onClick={() => onCancel(pull.id)}
                        >
                          Cancel
                        </Button>
                      ) : null}
                    </div>
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Type-check + lint**

Run: `cd frontend && bunx tsc -p tsconfig.build.json --noEmit && bunx biome check src/components/pos/PullQueue.tsx`
Expected: PASS, no diagnostics. (If `badge.tsx` does not export a `destructive`/`secondary` variant, adjust `STATE_VARIANT` to the variants it actually exports and note it.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/pos/PullQueue.tsx
git commit -m "feat(pulls): queue list component (Task 5.3)"
```

---

## Task 4: Fulfill panel — `components/pos/PullFulfillPanel.tsx`

Scan-assisted line settler. Steppers (Minus/Plus) match `ScanCart.tsx`/`TicketPartsList.tsx`; UNIT cap is 1, PART cap is `requested_qty`.

**Files:**
- Create: `frontend/src/components/pos/PullFulfillPanel.tsx`

- [ ] **Step 1: Write the component**

Create `frontend/src/components/pos/PullFulfillPanel.tsx`:

```tsx
import { ArrowLeft, Minus, Plus } from "lucide-react"
import type { Ref } from "react"
import type { ProjectPullLinePublic, ProjectPullPublic } from "@/client/types.gen"
import { CameraScanFallback } from "@/components/CameraScanFallback"
import { ScanInput, type ScanInputHandle } from "@/components/ScanInput"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  type FulfillDraft,
  lineCap,
  projectedPullState,
} from "@/lib/pull-fulfill"

interface PullFulfillPanelProps {
  pull: ProjectPullPublic
  projectLabel: string
  customerLabel: string
  /** product_id -> model name, for PART line labels. */
  productNames: Map<string, string>
  draft: FulfillDraft
  scanRef: Ref<ScanInputHandle>
  onScan: (code: string) => void
  isSearching: boolean
  notFound: boolean
  isError: boolean
  scanNotice: string
  onQtyChange: (line: ProjectPullLinePublic, qty: number) => void
  onSubmit: () => void
  onBack: () => void
  isPending: boolean
}

function lineLabel(
  line: ProjectPullLinePublic,
  productNames: Map<string, string>,
): string {
  if (line.line_kind === "UNIT") return line.unit_serial ?? "(no serial)"
  return productNames.get(line.product_id) ?? line.product_id
}

export function PullFulfillPanel({
  pull,
  projectLabel,
  customerLabel,
  productNames,
  draft,
  scanRef,
  onScan,
  isSearching,
  notFound,
  isError,
  scanNotice,
  onQtyChange,
  onSubmit,
  onBack,
  isPending,
}: PullFulfillPanelProps) {
  const canFulfill = pull.state === "PENDING" && !isPending
  const projected = projectedPullState(pull.lines, draft)

  return (
    <div className="space-y-4">
      <Button type="button" variant="ghost" size="sm" onClick={onBack}>
        <ArrowLeft /> Back to queue
      </Button>

      <div>
        <h2 className="text-lg font-semibold">{projectLabel}</h2>
        <p className="text-muted-foreground text-sm">{customerLabel}</p>
      </div>

      {pull.state === "PENDING" ? (
        <div className="space-y-2">
          <p className="text-sm font-medium">Scan item</p>
          <ScanInput ref={scanRef} onScan={onScan} />
          <CameraScanFallback onScan={onScan} />
          <p aria-live="assertive" className="text-muted-foreground min-h-5 text-sm">
            {isError
              ? "Scan lookup failed. Try again."
              : notFound
                ? "No item found for that code."
                : scanNotice}
          </p>
          <p aria-live="polite" className="text-muted-foreground min-h-5 text-sm">
            {isSearching ? "Searching…" : ""}
          </p>
        </div>
      ) : (
        <Badge variant="outline">This pull is {pull.state}</Badge>
      )}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Line</TableHead>
            <TableHead className="text-muted-foreground">Type</TableHead>
            <TableHead className="text-center">Fulfilled / Requested</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {pull.lines.map((line) => {
            const cap = lineCap(line)
            const qty = draft[line.id] ?? 0
            return (
              <TableRow key={line.id}>
                <TableCell className="num font-medium">
                  {lineLabel(line, productNames)}
                </TableCell>
                <TableCell className="text-muted-foreground text-xs">
                  {line.line_kind}
                </TableCell>
                <TableCell>
                  <div className="flex items-center justify-center gap-1">
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      className="size-11"
                      disabled={!canFulfill || qty <= 0}
                      aria-label={`Decrease ${lineLabel(line, productNames)}`}
                      onClick={() => onQtyChange(line, qty - 1)}
                    >
                      <Minus />
                    </Button>
                    <span className="num w-16 text-center" aria-hidden="true">
                      {qty} / {cap}
                    </span>
                    <span className="sr-only" aria-live="polite">
                      {`${lineLabel(line, productNames)} ${qty} of ${cap}`}
                    </span>
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      className="size-11"
                      disabled={!canFulfill || qty >= cap}
                      aria-label={`Increase ${lineLabel(line, productNames)}`}
                      onClick={() => onQtyChange(line, qty + 1)}
                    >
                      <Plus />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>

      <div className="flex items-center justify-end gap-4">
        <span className="text-muted-foreground text-sm">Will settle as</span>
        <Badge variant={projected === "FULFILLED" ? "default" : "destructive"}>
          {projected}
        </Badge>
      </div>

      <button
        type="button"
        onClick={onSubmit}
        disabled={!canFulfill}
        className="bg-cta text-cta-foreground hover:bg-cta/90 focus-visible:ring-ring focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none flex h-11 w-full items-center justify-center rounded-md px-4 text-sm font-semibold disabled:pointer-events-none disabled:opacity-50"
      >
        {isPending ? "Fulfilling…" : "Fulfill pull"}
      </button>
    </div>
  )
}
```

- [ ] **Step 2: Type-check + lint**

Run: `cd frontend && bunx tsc -p tsconfig.build.json --noEmit && bunx biome check src/components/pos/PullFulfillPanel.tsx`
Expected: PASS, no diagnostics.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/pos/PullFulfillPanel.tsx
git commit -m "feat(pulls): fulfill panel component (Task 5.3)"
```

---

## Task 5: Create panel — `components/pos/PullCreatePanel.tsx`

Admin-only create form (rendered by the route only for admins). Project picker + scan cart.

**Files:**
- Create: `frontend/src/components/pos/PullCreatePanel.tsx`

- [ ] **Step 1: Write the component**

Create `frontend/src/components/pos/PullCreatePanel.tsx`:

```tsx
import { ArrowLeft, Minus, Plus, Trash2 } from "lucide-react"
import { type Ref, useId } from "react"
import type { ProjectPublic } from "@/client/types.gen"
import { CameraScanFallback } from "@/components/CameraScanFallback"
import { ScanInput, type ScanInputHandle } from "@/components/ScanInput"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
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

interface PullCreatePanelProps {
  projects: ProjectPublic[]
  projectId: string
  onProjectChange: (value: string) => void
  adminNotes: string
  onNotesChange: (value: string) => void
  lines: CreateLine[]
  scanRef: Ref<ScanInputHandle>
  onScan: (code: string) => void
  isSearching: boolean
  notFound: boolean
  isError: boolean
  scanNotice: string
  onQtyChange: (key: string, qty: number) => void
  onRemove: (key: string) => void
  onSubmit: () => void
  onBack: () => void
  isPending: boolean
}

export function PullCreatePanel({
  projects,
  projectId,
  onProjectChange,
  adminNotes,
  onNotesChange,
  lines,
  scanRef,
  onScan,
  isSearching,
  notFound,
  isError,
  scanNotice,
  onQtyChange,
  onRemove,
  onSubmit,
  onBack,
  isPending,
}: PullCreatePanelProps) {
  const projectSelectId = useId()
  const notesId = useId()
  const canCreate = projectId !== "" && lines.length > 0 && !isPending

  return (
    <div className="space-y-4">
      <Button type="button" variant="ghost" size="sm" onClick={onBack}>
        <ArrowLeft /> Back to queue
      </Button>

      <h2 className="text-lg font-semibold">New project pull</h2>

      <div className="space-y-2">
        <Label htmlFor={projectSelectId}>Project</Label>
        <Select value={projectId} onValueChange={onProjectChange}>
          <SelectTrigger id={projectSelectId} className="w-full">
            <SelectValue placeholder="Select a project" />
          </SelectTrigger>
          <SelectContent>
            {projects.map((p) => (
              <SelectItem key={p.id} value={p.id}>
                {p.name} ({p.code})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-2">
        <Label htmlFor={notesId}>Admin notes (optional)</Label>
        <Input
          id={notesId}
          value={adminNotes}
          onChange={(e) => onNotesChange(e.target.value)}
          maxLength={512}
        />
      </div>

      <div className="space-y-2">
        <p className="text-sm font-medium">Scan item to request</p>
        <ScanInput ref={scanRef} onScan={onScan} />
        <CameraScanFallback onScan={onScan} />
        <p aria-live="assertive" className="text-muted-foreground min-h-5 text-sm">
          {isError
            ? "Scan lookup failed. Try again."
            : notFound
              ? "No item found for that code."
              : scanNotice}
        </p>
        <p aria-live="polite" className="text-muted-foreground min-h-5 text-sm">
          {isSearching ? "Searching…" : ""}
        </p>
      </div>

      {lines.length === 0 ? (
        <p className="text-muted-foreground py-6 text-center text-sm">
          Scan items to build the pull request.
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Item</TableHead>
              <TableHead className="text-muted-foreground">Type</TableHead>
              <TableHead className="text-center">Qty</TableHead>
              <TableHead className="w-12" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {lines.map((line) => {
              const isUnit = line.lineKind === "UNIT"
              return (
                <TableRow key={line.key}>
                  <TableCell>
                    <div className="font-medium">{line.modelName}</div>
                    <div className="text-muted-foreground num text-xs">
                      {isUnit ? line.unitSerial : line.sku}
                    </div>
                  </TableCell>
                  <TableCell className="text-muted-foreground text-xs">
                    {line.lineKind}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-center gap-1">
                      <Button
                        type="button"
                        variant="outline"
                        size="icon"
                        className="size-11"
                        disabled={isUnit || line.requestedQty <= 1}
                        aria-label={`Decrease ${line.sku}`}
                        onClick={() =>
                          onQtyChange(line.key, line.requestedQty - 1)
                        }
                      >
                        <Minus />
                      </Button>
                      <span className="num w-8 text-center" aria-hidden="true">
                        {line.requestedQty}
                      </span>
                      <Button
                        type="button"
                        variant="outline"
                        size="icon"
                        className="size-11"
                        disabled={isUnit}
                        aria-label={`Increase ${line.sku}`}
                        onClick={() =>
                          onQtyChange(line.key, line.requestedQty + 1)
                        }
                      >
                        <Plus />
                      </Button>
                    </div>
                  </TableCell>
                  <TableCell>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="text-destructive size-11"
                      aria-label={`Remove ${line.sku}`}
                      onClick={() => onRemove(line.key)}
                    >
                      <Trash2 />
                    </Button>
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      )}

      <button
        type="button"
        onClick={onSubmit}
        disabled={!canCreate}
        className="bg-cta text-cta-foreground hover:bg-cta/90 focus-visible:ring-ring focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none flex h-11 w-full items-center justify-center rounded-md px-4 text-sm font-semibold disabled:pointer-events-none disabled:opacity-50"
      >
        {isPending ? "Creating…" : "Create pull"}
      </button>
    </div>
  )
}
```

- [ ] **Step 2: Type-check + lint**

Run: `cd frontend && bunx tsc -p tsconfig.build.json --noEmit && bunx biome check src/components/pos/PullCreatePanel.tsx`
Expected: PASS, no diagnostics.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/pos/PullCreatePanel.tsx
git commit -m "feat(pulls): create panel component (Task 5.3)"
```

---

## Task 6: Route — `routes/_layout/pulls.tsx`

Orchestrates queries, scan routing, the three mutations, and view switching. Read `frontend/src/routes/_layout/sale.tsx` and `tickets.tsx` first for the query/scan/toast conventions.

**Files:**
- Create: `frontend/src/routes/_layout/pulls.tsx`

- [ ] **Step 1: Write the route**

Create `frontend/src/routes/_layout/pulls.tsx`:

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import {
  CustomersService,
  type ProjectPullFulfill,
  type ProjectPullLinePublic,
  type ProjectPullPublic,
  ProjectPullsService,
  ProjectsService,
  ProductsService,
} from "@/client"
import {
  PullCreatePanel,
} from "@/components/pos/PullCreatePanel"
import { PullFulfillPanel } from "@/components/pos/PullFulfillPanel"
import { PullQueue, type PullStateFilter } from "@/components/pos/PullQueue"
import { type ScanInputHandle } from "@/components/ScanInput"
import useCustomToast from "@/hooks/useCustomToast"
import { useRole } from "@/hooks/useRole"
import { useScanLookup } from "@/hooks/useScanLookup"
import { requireAuth } from "@/lib/route-guards"
import {
  type CreateCatalogEntry,
  addScanToCreateCart,
  buildCreatePayload,
  type CreateLine,
  removeCreateLine,
  setCreateQty,
} from "@/lib/pull-create"
import {
  applyScanToFulfill,
  buildFulfillPayload,
  type FulfillDraft,
  seedFulfillDraft,
  setLineFulfilledQty,
} from "@/lib/pull-fulfill"

export const Route = createFileRoute("/_layout/pulls")({
  component: Pulls,
  beforeLoad: requireAuth,
  head: () => ({
    meta: [{ title: "Pulls - CastraNova POS" }],
  }),
})

function Pulls() {
  const { isAdmin } = useRole()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()

  const [mode, setMode] = useState<"queue" | "create">("queue")
  const [selectedPullId, setSelectedPullId] = useState<string | null>(null)
  const [stateFilter, setStateFilter] = useState<PullStateFilter>("PENDING")
  const [fulfillDraft, setFulfillDraft] = useState<FulfillDraft>({})
  const [createLines, setCreateLines] = useState<CreateLine[]>([])
  const [projectId, setProjectId] = useState<string>("")
  const [adminNotes, setAdminNotes] = useState<string>("")
  const [scanNotice, setScanNotice] = useState<string>("")
  const scanRef = useRef<ScanInputHandle>(null)

  const { data: pulls } = useQuery({
    queryKey: ["project-pulls", stateFilter],
    queryFn: () =>
      ProjectPullsService.readProjectPulls({
        state: stateFilter === "ALL" ? undefined : stateFilter,
      }),
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  })
  const { data: projects } = useQuery({
    queryKey: ["projects"],
    queryFn: () => ProjectsService.readProjects(),
    staleTime: 5 * 60 * 1000,
  })
  const { data: customers } = useQuery({
    queryKey: ["customers"],
    queryFn: () => CustomersService.readCustomers(),
    staleTime: 5 * 60 * 1000,
  })
  const { data: products } = useQuery({
    queryKey: ["products"],
    queryFn: () => ProductsService.readProducts(),
    staleTime: 5 * 60 * 1000,
  })

  const projectLabels = useMemo(
    () =>
      new Map(
        (projects ?? []).map((p) => [p.id, `${p.name} (${p.code})`]),
      ),
    [projects],
  )
  const customerLabels = useMemo(
    () => new Map((customers ?? []).map((c) => [c.id, c.name])),
    [customers],
  )
  const productNames = useMemo(
    () => new Map((products ?? []).map((p) => [p.id, p.model_name])),
    [products],
  )
  // sku -> {productId, modelName} for the create cart.
  const createCatalog = useMemo(() => {
    const map = new Map<string, CreateCatalogEntry>()
    for (const p of products ?? []) {
      map.set(p.sku, { productId: p.id, modelName: p.model_name })
    }
    return map
  }, [products])

  const selectedPull = useMemo(
    () => (pulls ?? []).find((p) => p.id === selectedPullId),
    [pulls, selectedPullId],
  )

  const { resolve, result, isSearching, notFound, isError, reset } =
    useScanLookup()

  // Route each scan to the active view. A scan that changes nothing (no matching
  // line / not in catalog) and isn't NOT_FOUND surfaces a context notice.
  useEffect(() => {
    if (!result) return
    if (mode === "create") {
      const next = addScanToCreateCart(createLines, result, createCatalog)
      if (next === createLines && result.kind !== "NOT_FOUND") {
        setScanNotice("That item can't be added as a pull line.")
      } else {
        setCreateLines(next)
        setScanNotice("")
      }
    } else if (selectedPull) {
      const next = applyScanToFulfill(fulfillDraft, selectedPull.lines, result)
      if (next === fulfillDraft && result.kind !== "NOT_FOUND") {
        setScanNotice("Scanned item isn't on this pull.")
      } else {
        setFulfillDraft(next)
        setScanNotice("")
      }
    }
    reset()
  }, [result, mode, selectedPull, createLines, fulfillDraft, createCatalog, reset])

  const fulfillMutation = useMutation<
    ProjectPullPublic,
    Error,
    { pullId: string; body: ProjectPullFulfill }
  >({
    mutationFn: ({ pullId, body }) =>
      ProjectPullsService.fulfillProjectPull({
        pullId,
        requestBody: body,
      }),
    onSuccess: (pull) => {
      queryClient.invalidateQueries({ queryKey: ["project-pulls"] })
      showSuccessToast(`Pull ${pull.state.toLowerCase()}.`)
      setSelectedPullId(null)
      setFulfillDraft({})
      setScanNotice("")
    },
    onError: () => showErrorToast("Could not fulfill the pull. Please try again."),
  })

  const createMutation = useMutation({
    mutationFn: () =>
      ProjectPullsService.createProjectPull({
        requestBody: buildCreatePayload(createLines, projectId, adminNotes),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-pulls"] })
      showSuccessToast("Pull created.")
      setMode("queue")
      setCreateLines([])
      setProjectId("")
      setAdminNotes("")
      setScanNotice("")
    },
    onError: () => showErrorToast("Could not create the pull. Please try again."),
  })

  const cancelMutation = useMutation({
    mutationFn: (pullId: string) =>
      ProjectPullsService.cancelProjectPull({ pullId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-pulls"] })
      showSuccessToast("Pull cancelled.")
    },
    onError: () => showErrorToast("Could not cancel the pull. Please try again."),
  })

  const handleSelect = useCallback((pull: ProjectPullPublic) => {
    setSelectedPullId(pull.id)
    setFulfillDraft(seedFulfillDraft(pull.lines))
    setScanNotice("")
  }, [])

  const handleBackToQueue = useCallback(() => {
    setMode("queue")
    setSelectedPullId(null)
    setFulfillDraft({})
    setScanNotice("")
  }, [])

  const handleNew = useCallback(() => {
    setMode("create")
    setCreateLines([])
    setProjectId("")
    setAdminNotes("")
    setScanNotice("")
  }, [])

  const handleFulfill = useCallback(() => {
    if (!selectedPull) return
    fulfillMutation.mutate({
      pullId: selectedPull.id,
      body: buildFulfillPayload(fulfillDraft),
    })
  }, [selectedPull, fulfillDraft, fulfillMutation])

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Project pulls</h1>
        <p className="text-muted-foreground">
          Fulfill pending pulls at the warehouse.
        </p>
      </div>

      {mode === "create" ? (
        <PullCreatePanel
          projects={projects ?? []}
          projectId={projectId}
          onProjectChange={setProjectId}
          adminNotes={adminNotes}
          onNotesChange={setAdminNotes}
          lines={createLines}
          scanRef={scanRef}
          onScan={resolve}
          isSearching={isSearching}
          notFound={notFound}
          isError={isError}
          scanNotice={scanNotice}
          onQtyChange={(key, qty) =>
            setCreateLines((prev) => setCreateQty(prev, key, qty))
          }
          onRemove={(key) =>
            setCreateLines((prev) => removeCreateLine(prev, key))
          }
          onSubmit={() => createMutation.mutate()}
          onBack={handleBackToQueue}
          isPending={createMutation.isPending}
        />
      ) : selectedPull ? (
        <PullFulfillPanel
          pull={selectedPull}
          projectLabel={
            projectLabels.get(selectedPull.project_id) ?? selectedPull.project_id
          }
          customerLabel={
            customerLabels.get(selectedPull.customer_id) ??
            selectedPull.customer_id
          }
          productNames={productNames}
          draft={fulfillDraft}
          scanRef={scanRef}
          onScan={resolve}
          isSearching={isSearching}
          notFound={notFound}
          isError={isError}
          scanNotice={scanNotice}
          onQtyChange={(line: ProjectPullLinePublic, qty: number) =>
            setFulfillDraft((prev) => setLineFulfilledQty(prev, line, qty))
          }
          onSubmit={handleFulfill}
          onBack={handleBackToQueue}
          isPending={fulfillMutation.isPending}
        />
      ) : (
        <PullQueue
          pulls={pulls ?? []}
          projectLabels={projectLabels}
          customerLabels={customerLabels}
          stateFilter={stateFilter}
          isAdmin={isAdmin}
          onStateFilterChange={setStateFilter}
          onSelect={handleSelect}
          onCancel={(pullId) => cancelMutation.mutate(pullId)}
          onNew={handleNew}
          isCancelling={cancelMutation.isPending}
        />
      )}
    </div>
  )
}
```

- [ ] **Step 2: Regenerate the route tree**

`routeTree.gen.ts` is produced by the `@tanstack/router-plugin` (Vite). If the dev stack is running (`docker compose watch` or `cd frontend && bun run dev`), it regenerates on save — confirm a `TicketsRoute`-style `PullsRoute` entry appears in `frontend/src/routeTree.gen.ts`. If no dev server is running, run `cd frontend && bun run build` once (generates + typechecks; makes Step 3 redundant).

- [ ] **Step 3: Type-check + lint**

Run: `cd frontend && bunx tsc -p tsconfig.build.json --noEmit && bunx biome check src/routes/_layout/pulls.tsx`
Expected: PASS, no diagnostics. (If `tsc` says `/pulls` is not a valid path, the route tree wasn't regenerated — redo Step 2. Use `--write` on biome for any fixable formatting, then re-check.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/_layout/pulls.tsx frontend/src/routeTree.gen.ts
git commit -m "feat(pulls): /pulls route with queue/fulfill/create orchestration (Task 5.3)"
```

---

## Task 7: Navigation entry — `components/Sidebar/AppSidebar.tsx`

**Files:**
- Modify: `frontend/src/components/Sidebar/AppSidebar.tsx`

- [ ] **Step 1: Add the `ClipboardList` icon to the lucide import**

The current import line is:

```tsx
import { Home, PackagePlus, ShoppingCart, Users, Wrench } from "lucide-react"
```

Change it to (alphabetical, matching the existing order):

```tsx
import {
  ClipboardList,
  Home,
  PackagePlus,
  ShoppingCart,
  Users,
  Wrench,
} from "lucide-react"
```

- [ ] **Step 2: Add the nav item to `baseItems`**

The current `baseItems` ends with:

```tsx
  // Tickets: staff + admin maintenance flow (FR-008). Online-only, no cost.
  { icon: Wrench, title: "Tickets", path: "/tickets" },
]
```

Change it to:

```tsx
  // Tickets: staff + admin maintenance flow (FR-008). Online-only, no cost.
  { icon: Wrench, title: "Tickets", path: "/tickets" },
  // Pulls: staff + admin fulfill; admin create/cancel (FR-009). Online-only, no cost.
  { icon: ClipboardList, title: "Pulls", path: "/pulls" },
]
```

- [ ] **Step 3: Type-check + lint**

Run: `cd frontend && bunx tsc -p tsconfig.build.json --noEmit && bunx biome check src/components/Sidebar/AppSidebar.tsx`
Expected: PASS, no diagnostics. The router accepts `"/pulls"` (generated in Task 6).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Sidebar/AppSidebar.tsx
git commit -m "feat(pulls): add Pulls to sidebar nav (Task 5.3)"
```

---

## Task 8: Verification gates

No new code — the verification loop.

- [ ] **Step 1: Lint/format (touched files)**

Run: `cd frontend && bunx biome check src/lib/pull-fulfill.ts src/lib/pull-create.ts src/components/pos/PullQueue.tsx src/components/pos/PullFulfillPanel.tsx src/components/pos/PullCreatePanel.tsx src/routes/_layout/pulls.tsx src/components/Sidebar/AppSidebar.tsx tests/pull-fulfill.spec.ts tests/pull-create.spec.ts`
Expected: no diagnostics. If fixable issues appear, re-run with `--write` and re-commit the touched files.

- [ ] **Step 2: Type-check (whole project)**

Run: `cd frontend && bunx tsc -p tsconfig.build.json --noEmit`
Expected: PASS, zero errors.

- [ ] **Step 3: New unit tests**

Run: `cd frontend && bunx playwright test tests/pull-fulfill.spec.ts tests/pull-create.spec.ts --reporter=line`
Expected: PASS (all green).

- [ ] **Step 4: Full E2E suite (no regression)**

Run: `cd frontend && bunx playwright test --workers=1 --reporter=line`
Expected: the suite stays green (prior count was 115 passed / 1 skipped; this adds ~18 new pure-logic tests). The `/pulls` browser flow has no E2E yet (Task 5.2, which this screen unblocks). If the dev stack isn't up, start it (`docker compose watch`) first; `reuseExistingServer` will use it.

- [ ] **Step 5: Manual smoke (recommended)**

With the app at http://localhost:5173:
- As **admin** (`admin@example.com` / `changethis`): Pulls nav appears; "New pull" → pick a project, scan a part + a serialized unit, Create → returns to queue with a new PENDING pull. Open it → fulfill some-but-not-all → "Will settle as SHORT" → Fulfill → toast "Pull short.". Cancel a PENDING pull from the queue.
- As **staff** (`staff@example.com` / `staffpass123`): Pulls nav appears; can Open + Fulfill; **no** "New pull" button and **no** Cancel action.

- [ ] **Step 6: Final commit (only if Step 1 produced uncommitted `--write` changes)**

```bash
git add -A && git commit -m "chore(pulls): biome formatting"
```

---

## Self-Review Notes (for the implementer)

- **Spec coverage:** §4.2 fulfill lib → Task 1; §4.3 create lib → Task 2; §4.4 PullQueue/FulfillPanel/CreatePanel → Tasks 3/4/5; §4.1 route + queries + scan routing + 3 mutations + draft seeding → Task 6; §4.5 nav → Task 7; §6 error handling → Task 6 (`onError` toasts, scanNotice, `canFulfill`/`canCreate` guards, cancel only on PENDING/SHORT via PullQueue); §3.C seed-all-lines contract → Task 1 (`seedFulfillDraft` + `buildFulfillPayload` test) and Task 6 (`handleSelect` seeds on open); §7 tests → Tasks 1/2/8. §8 out-of-scope items are simply not built.
- **Type consistency:** `FulfillDraft`, `lineCap`, `seedFulfillDraft`, `applyScanToFulfill`, `setLineFulfilledQty`, `buildFulfillPayload`, `projectedPullState` (Task 1) and `CreateLine`, `CreateCatalogEntry`, `addScanToCreateCart`, `setCreateQty`, `removeCreateLine`, `buildCreatePayload` (Task 2) are imported unchanged by the route (Task 6); `PullStateFilter` defined in Task 3, imported in Task 6; component prop names match the route's call sites exactly.
- **No `generate-client`:** SDK already exposes `ProjectPullsService`/`ProjectsService`; backend untouched.
- **Known accepted behavior:** SHORT pulls trigger backend admin notifications automatically on fulfill (no UI); a cancelled/settled pull opened for fulfill shows a read-only state badge with disabled steppers (`canFulfill` false).
```
