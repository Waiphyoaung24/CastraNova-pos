import { expect, test } from "@playwright/test"
import type {
  SerialSearchResult,
  SkuSearchResult,
} from "../src/client/types.gen"
import type { ScanLookupResult } from "../src/hooks/useScanLookup"
import {
  addScanToCart,
  buildSaleRequest,
  type CartLine,
  cartSubtotalThb,
  removeLine,
  setLineQuantity,
} from "../src/lib/sale-cart"

// Pure-logic coverage of the Sale cart (Task 3.1).
// No browser / React / backend — mirrors useScanLookup.spec.ts / scanner.spec.ts.
// ScanCart.tsx is a thin renderer over these functions, so this covers it.

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const UNIT_SCAN: ScanLookupResult = {
  kind: "UNIT",
  data: {
    castranova_barcode: "CN-ABC123",
    product_id: "prod-1",
    sku: "SKU-001",
    supplier_serial: "SUP-001",
    current_state: "IN_STOCK",
    movements: [],
  } satisfies SerialSearchResult,
}

const PART_SCAN: ScanLookupResult = {
  kind: "PART",
  data: {
    sku: "SKU-PART-A",
    product_id: "prod-2",
    tracking_mode: "QUANTITY",
    total_on_hand: 5,
    batches: [],
  } satisfies SkuSearchResult,
}

const PART_SCAN_B: ScanLookupResult = {
  kind: "PART",
  data: {
    sku: "SKU-PART-B",
    product_id: "prod-3",
    tracking_mode: "QUANTITY",
    total_on_hand: 9,
    batches: [],
  } satisfies SkuSearchResult,
}

const NOT_FOUND_SCAN: ScanLookupResult = { kind: "NOT_FOUND" }

const priceMap = new Map<string, number>([
  ["prod-1", 1500],
  ["prod-2", 200],
  // prod-3 intentionally absent → price 0
])

// ---------------------------------------------------------------------------
// addScanToCart — UNIT
// ---------------------------------------------------------------------------

test("UNIT scan adds a line with quantity 1", () => {
  const lines = addScanToCart([], UNIT_SCAN, priceMap)
  expect(lines).toEqual([
    {
      key: "CN-ABC123",
      lineKind: "UNIT",
      barcode: "CN-ABC123",
      sku: "SKU-001",
      productId: "prod-1",
      quantity: 1,
      unitPriceThb: 1500,
    },
  ])
})

test("scanning the same UNIT barcode again keeps quantity 1 (no duplicate)", () => {
  const once = addScanToCart([], UNIT_SCAN, priceMap)
  const twice = addScanToCart(once, UNIT_SCAN, priceMap)
  expect(twice).toHaveLength(1)
  expect(twice[0].quantity).toBe(1)
  // Re-scan is a no-op: the array reference is returned unchanged.
  expect(twice).toBe(once)
})

// ---------------------------------------------------------------------------
// addScanToCart — PART
// ---------------------------------------------------------------------------

test("PART scan adds a line with quantity 1", () => {
  const lines = addScanToCart([], PART_SCAN, priceMap)
  expect(lines).toEqual([
    {
      key: "SKU-PART-A",
      lineKind: "PART",
      barcode: undefined,
      sku: "SKU-PART-A",
      productId: "prod-2",
      quantity: 1,
      unitPriceThb: 200,
    },
  ])
})

test("scanning the same PART sku again increments quantity to 2", () => {
  const once = addScanToCart([], PART_SCAN, priceMap)
  const twice = addScanToCart(once, PART_SCAN, priceMap)
  expect(twice).toHaveLength(1)
  expect(twice[0].quantity).toBe(2)
})

test("a different PART sku adds a second line", () => {
  const lines = addScanToCart(
    addScanToCart([], PART_SCAN, priceMap),
    PART_SCAN_B,
    priceMap,
  )
  expect(lines).toHaveLength(2)
  expect(lines.map((l) => l.key)).toEqual(["SKU-PART-A", "SKU-PART-B"])
  expect(lines[1].unitPriceThb).toBe(0) // prod-3 missing from priceMap
})

test("NOT_FOUND scan leaves the cart unchanged", () => {
  const start = addScanToCart([], PART_SCAN, priceMap)
  const after = addScanToCart(start, NOT_FOUND_SCAN, priceMap)
  expect(after).toBe(start)
})

// ---------------------------------------------------------------------------
// setLineQuantity / removeLine
// ---------------------------------------------------------------------------

test("setLineQuantity updates a PART line quantity", () => {
  const lines = addScanToCart([], PART_SCAN, priceMap)
  const updated = setLineQuantity(lines, "SKU-PART-A", 4)
  expect(updated[0].quantity).toBe(4)
})

test("setLineQuantity clamps PART quantity to a minimum of 1", () => {
  const lines = addScanToCart([], PART_SCAN, priceMap)
  const updated = setLineQuantity(lines, "SKU-PART-A", 0)
  expect(updated[0].quantity).toBe(1)
})

test("setLineQuantity coerces a non-finite quantity (NaN) to 1", () => {
  const lines = addScanToCart([], PART_SCAN, priceMap)
  const updated = setLineQuantity(lines, "SKU-PART-A", Number.NaN)
  expect(updated[0].quantity).toBe(1)
})

test("setLineQuantity floors a fractional quantity (2.9 → 2)", () => {
  const lines = addScanToCart([], PART_SCAN, priceMap)
  const updated = setLineQuantity(lines, "SKU-PART-A", 2.9)
  expect(updated[0].quantity).toBe(2)
})

test("setLineQuantity never changes a UNIT line off quantity 1", () => {
  const lines = addScanToCart([], UNIT_SCAN, priceMap)
  const updated = setLineQuantity(lines, "CN-ABC123", 5)
  expect(updated[0].quantity).toBe(1)
})

test("removeLine drops the matching line", () => {
  const lines = addScanToCart(
    addScanToCart([], PART_SCAN, priceMap),
    PART_SCAN_B,
    priceMap,
  )
  const after = removeLine(lines, "SKU-PART-A")
  expect(after.map((l) => l.key)).toEqual(["SKU-PART-B"])
})

// ---------------------------------------------------------------------------
// cartSubtotalThb
// ---------------------------------------------------------------------------

test("cartSubtotalThb sums unitPriceThb × quantity, treating missing prices as 0", () => {
  const unit = addScanToCart([], UNIT_SCAN, priceMap) // 1 × 1500
  const withPartA = addScanToCart(unit, PART_SCAN, priceMap) // 1 × 200
  const withPartAx3 = setLineQuantity(withPartA, "SKU-PART-A", 3) // 3 × 200
  const full = addScanToCart(withPartAx3, PART_SCAN_B, priceMap) // 1 × 0
  // 1500 + 600 + 0
  expect(cartSubtotalThb(full)).toBe(2100)
})

test("cartSubtotalThb of an empty cart is 0", () => {
  expect(cartSubtotalThb([])).toBe(0)
})

// ---------------------------------------------------------------------------
// buildSaleRequest
// ---------------------------------------------------------------------------

test("buildSaleRequest maps a mixed UNIT+PART cart to the API payload", () => {
  const lines: CartLine[] = [
    {
      key: "CN-ABC123",
      lineKind: "UNIT",
      barcode: "CN-ABC123",
      sku: "SKU-001",
      productId: "prod-1",
      quantity: 1,
      unitPriceThb: 1500,
    },
    {
      key: "SKU-PART-A",
      lineKind: "PART",
      sku: "SKU-PART-A",
      productId: "prod-2",
      quantity: 3,
      unitPriceThb: 200,
    },
  ]
  const req = buildSaleRequest(lines, "cust-99", "idem-key-xyz")
  expect(req).toEqual({
    customer_id: "cust-99",
    idempotency_key: "idem-key-xyz",
    lines: [
      { line_kind: "UNIT", castranova_barcode: "CN-ABC123", quantity: 1 },
      { line_kind: "PART", sku: "SKU-PART-A", quantity: 3 },
    ],
  })
})
