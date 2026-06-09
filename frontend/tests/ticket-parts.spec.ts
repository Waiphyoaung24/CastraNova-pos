import { expect, test } from "@playwright/test"
import type {
  SerialSearchResult,
  SkuSearchResult,
} from "../src/client/types.gen"
import type { ScanLookupResult } from "../src/hooks/useScanLookup"
import {
  addScanToTicketParts,
  buildTicketSubmission,
  type PartCatalogEntry,
  removePart,
  setPartQuantity,
  type TicketPartLine,
  ticketPartsSubtotalThb,
} from "../src/lib/ticket-parts"

// Pure-logic coverage of the ticket parts cart (Task 5.3 / tickets screen).
// No browser / React / backend — mirrors sale-cart.spec.ts. TicketPartsList.tsx
// is a thin renderer over these functions, so this covers it.

// --- Fixtures --------------------------------------------------------------

const PART_LOOKUP = new Map<string, PartCatalogEntry>([
  [
    "SKU-CABLE",
    { productId: "prod-cable", modelName: "HDMI Cable", repairPriceThb: 150 },
  ],
  [
    "SKU-FAN",
    { productId: "prod-fan", modelName: "Cooling Fan", repairPriceThb: 400 },
  ],
])

const partScan = (sku: string): ScanLookupResult => ({
  kind: "PART",
  data: {
    sku,
    product_id: PART_LOOKUP.get(sku)?.productId ?? "prod-unknown",
    tracking_mode: "QUANTITY",
    total_on_hand: 10,
    batches: [],
  } as SkuSearchResult,
})

const UNIT_SCAN: ScanLookupResult = {
  kind: "UNIT",
  data: {
    castranova_barcode: "CN-XYZ",
    product_id: "prod-fan",
    sku: "SKU-FAN",
    supplier_serial: "SUP-1",
  } as SerialSearchResult,
}

const NOT_FOUND_SCAN: ScanLookupResult = { kind: "NOT_FOUND" }

// --- addScanToTicketParts --------------------------------------------------

test("PART scan appends a new line using catalog name + price", () => {
  const next = addScanToTicketParts([], partScan("SKU-CABLE"), PART_LOOKUP)
  expect(next).toEqual([
    {
      key: "SKU-CABLE",
      sku: "SKU-CABLE",
      productId: "prod-cable",
      modelName: "HDMI Cable",
      quantity: 1,
      unitPriceThb: 150,
    },
  ])
})

test("re-scanning the same PART sku increments quantity", () => {
  let lines: TicketPartLine[] = []
  lines = addScanToTicketParts(lines, partScan("SKU-CABLE"), PART_LOOKUP)
  lines = addScanToTicketParts(lines, partScan("SKU-CABLE"), PART_LOOKUP)
  expect(lines).toHaveLength(1)
  expect(lines[0].quantity).toBe(2)
})

test("UNIT scan leaves the cart unchanged (same reference)", () => {
  const lines: TicketPartLine[] = []
  expect(addScanToTicketParts(lines, UNIT_SCAN, PART_LOOKUP)).toBe(lines)
})

test("NOT_FOUND scan leaves the cart unchanged (same reference)", () => {
  const lines: TicketPartLine[] = []
  expect(addScanToTicketParts(lines, NOT_FOUND_SCAN, PART_LOOKUP)).toBe(lines)
})

test("PART sku missing from the catalog leaves the cart unchanged", () => {
  const lines: TicketPartLine[] = []
  expect(addScanToTicketParts(lines, partScan("SKU-GONE"), PART_LOOKUP)).toBe(
    lines,
  )
})

// --- setPartQuantity / removePart -----------------------------------------

test("setPartQuantity floors at 1 and floors fractional input", () => {
  const lines = addScanToTicketParts([], partScan("SKU-FAN"), PART_LOOKUP)
  expect(setPartQuantity(lines, "SKU-FAN", 0)[0].quantity).toBe(1)
  expect(setPartQuantity(lines, "SKU-FAN", 3.9)[0].quantity).toBe(3)
})

test("removePart drops the matching line", () => {
  let lines = addScanToTicketParts([], partScan("SKU-CABLE"), PART_LOOKUP)
  lines = addScanToTicketParts(lines, partScan("SKU-FAN"), PART_LOOKUP)
  expect(removePart(lines, "SKU-CABLE")).toEqual([
    expect.objectContaining({ sku: "SKU-FAN" }),
  ])
})

// --- subtotal --------------------------------------------------------------

test("ticketPartsSubtotalThb sums price × quantity", () => {
  let lines = addScanToTicketParts([], partScan("SKU-CABLE"), PART_LOOKUP) // 150 × 1
  lines = setPartQuantity(lines, "SKU-CABLE", 2) // 150 × 2 = 300
  lines = addScanToTicketParts(lines, partScan("SKU-FAN"), PART_LOOKUP) // 400 × 1
  expect(ticketPartsSubtotalThb(lines)).toBe(700)
})

// --- buildTicketSubmission -------------------------------------------------

test("buildTicketSubmission shapes open/parts/close payloads", () => {
  let lines = addScanToTicketParts([], partScan("SKU-CABLE"), PART_LOOKUP)
  lines = setPartQuantity(lines, "SKU-CABLE", 3)
  const out = buildTicketSubmission(
    lines,
    "cust-1",
    "Won't power on",
    "  ",
    "Replaced cable",
    "idem-123",
  )
  expect(out).toEqual({
    open: {
      customer_id: "cust-1",
      issue: "Won't power on",
      notes: null,
      idempotency_key: "idem-123",
    },
    parts: [{ sku: "SKU-CABLE", quantity: 3 }],
    close: { resolution: "Replaced cable" },
  })
})

test("buildTicketSubmission nullifies blank resolution, keeps notes", () => {
  const out = buildTicketSubmission(
    [],
    "cust-1",
    "Issue",
    "Dropped off",
    "",
    "k",
  )
  expect(out.parts).toEqual([])
  expect(out.open.notes).toBe("Dropped off")
  expect(out.close.resolution).toBeNull()
})
