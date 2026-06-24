import { expect, test } from "@playwright/test"
import type {
  SerialSearchResult,
  SkuSearchResult,
} from "../src/client/types.gen"
import type { ScanLookupResult } from "../src/hooks/useScanLookup"
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
