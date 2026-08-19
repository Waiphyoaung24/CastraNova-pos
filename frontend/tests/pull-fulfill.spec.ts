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
  fulfilledLineCount,
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
  product_sku: "SKU-LAPTOP",
  model_name: "Laptop",
  unit_serial: "CN-UNIT-1",
  requested_qty: null,
  fulfilled_qty: 0,
  line_state: "PENDING",
}

const PART_LINE: ProjectPullLinePublic = {
  id: "line-part",
  line_kind: "PART",
  product_id: "prod-cable",
  product_sku: "SKU-CABLE",
  model_name: "Cable",
  unit_serial: null,
  requested_qty: 3,
  fulfilled_qty: 0,
  line_state: "PENDING",
}

const LINES = [UNIT_LINE, PART_LINE]

// A settled (SHORT) pull as the server returns it: the UNIT line went out, the
// PART line went out 2 of 3. Staff reopening this pull must see these numbers.
const SETTLED_LINES: ProjectPullLinePublic[] = [
  { ...UNIT_LINE, fulfilled_qty: 1, line_state: "FULFILLED" },
  { ...PART_LINE, fulfilled_qty: 2, line_state: "SHORT" },
]

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

test("seedFulfillDraft sets every line to 0 for a PENDING pull", () => {
  expect(seedFulfillDraft(LINES, "PENDING")).toEqual({
    "line-unit": 0,
    "line-part": 0,
  })
})

test("seedFulfillDraft mirrors fulfilled_qty for a settled pull", () => {
  // Regression: a settled pull used to seed all-zero, so reopening it showed
  // "0 / 3" on every line instead of what was actually given out.
  expect(seedFulfillDraft(SETTLED_LINES, "SHORT")).toEqual({
    "line-unit": 1,
    "line-part": 2,
  })
  expect(seedFulfillDraft(SETTLED_LINES, "FULFILLED")).toEqual({
    "line-unit": 1,
    "line-part": 2,
  })
  expect(seedFulfillDraft(SETTLED_LINES, "CANCELLED")).toEqual({
    "line-unit": 1,
    "line-part": 2,
  })
})

test("seedFulfillDraft still zeroes a PENDING pull even if lines carry qty", () => {
  // Guards the submit contract (see pull-fulfill.ts header): the backend
  // FULL-fills any line omitted from the payload, so a PENDING draft must start
  // at 0 regardless of what the line rows say.
  expect(seedFulfillDraft(SETTLED_LINES, "PENDING")).toEqual({
    "line-unit": 0,
    "line-part": 0,
  })
})

test("a settled seed drives a truthful given-out count", () => {
  // UNIT line reached its cap of 1; PART line stopped at 2 of 3.
  const draft = seedFulfillDraft(SETTLED_LINES, "SHORT")
  expect(fulfilledLineCount(SETTLED_LINES, draft)).toBe(1)
})

// --- applyScanToFulfill ----------------------------------------------------

test("UNIT scan matching unit_serial sets that line to 1", () => {
  const draft = seedFulfillDraft(LINES, "PENDING")
  expect(applyScanToFulfill(draft, LINES, unitScan("CN-UNIT-1"))).toEqual({
    "line-unit": 1,
    "line-part": 0,
  })
})

test("UNIT scan with no matching serial leaves draft unchanged (same ref)", () => {
  const draft = seedFulfillDraft(LINES, "PENDING")
  expect(applyScanToFulfill(draft, LINES, unitScan("CN-NOPE"))).toBe(draft)
})

test("PART scan matching product_id increments, clamped to cap", () => {
  let draft: FulfillDraft = seedFulfillDraft(LINES, "PENDING")
  draft = applyScanToFulfill(draft, LINES, partScan("prod-cable")) // 1
  draft = applyScanToFulfill(draft, LINES, partScan("prod-cable")) // 2
  draft = applyScanToFulfill(draft, LINES, partScan("prod-cable")) // 3
  draft = applyScanToFulfill(draft, LINES, partScan("prod-cable")) // capped at 3
  expect(draft["line-part"]).toBe(3)
})

test("PART scan with no matching product leaves draft unchanged (same ref)", () => {
  const draft = seedFulfillDraft(LINES, "PENDING")
  expect(applyScanToFulfill(draft, LINES, partScan("prod-gone"))).toBe(draft)
})

test("NOT_FOUND scan leaves draft unchanged (same ref)", () => {
  const draft = seedFulfillDraft(LINES, "PENDING")
  expect(applyScanToFulfill(draft, LINES, NOT_FOUND)).toBe(draft)
})

// --- setLineFulfilledQty ---------------------------------------------------

test("setLineFulfilledQty clamps to [0, cap] and floors", () => {
  const draft = seedFulfillDraft(LINES, "PENDING")
  expect(setLineFulfilledQty(draft, PART_LINE, 9)["line-part"]).toBe(3)
  expect(setLineFulfilledQty(draft, PART_LINE, -1)["line-part"]).toBe(0)
  expect(setLineFulfilledQty(draft, PART_LINE, 2.9)["line-part"]).toBe(2)
  expect(setLineFulfilledQty(draft, UNIT_LINE, 5)["line-unit"]).toBe(1)
})

// --- buildFulfillPayload (the contract guard) ------------------------------

test("buildFulfillPayload emits an explicit entry for EVERY line", () => {
  const draft = seedFulfillDraft(LINES, "PENDING") // all zero
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
  let draft = seedFulfillDraft(LINES, "PENDING")
  expect(projectedPullState(LINES, draft)).toBe("SHORT")
  draft = setLineFulfilledQty(draft, UNIT_LINE, 1)
  draft = setLineFulfilledQty(draft, PART_LINE, 3)
  expect(projectedPullState(LINES, draft)).toBe("FULFILLED")
})

// --- fulfilledLineCount --------------------------------------------------

test("fulfilledLineCount counts only lines drafted to their full cap", () => {
  const draft = seedFulfillDraft(LINES, "PENDING") // { "line-unit": 0, "line-part": 0 }
  expect(fulfilledLineCount(LINES, draft)).toBe(0)

  const partFull = setLineFulfilledQty(draft, PART_LINE, 3) // cap 3
  expect(fulfilledLineCount(LINES, partFull)).toBe(1)

  const both = { ...partFull, "line-unit": 1 } // UNIT cap 1
  expect(fulfilledLineCount(LINES, both)).toBe(2)
})
