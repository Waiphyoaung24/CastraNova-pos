import { expect, test } from "@playwright/test"
import type { StockOnHandRow } from "../src/client/types.gen"
import { deriveCategories, filterStockRows } from "../src/lib/stock-on-hand"

// Pure-logic coverage of the Stock-on-Hand client filters (FR-012). The full
// in-browser dashboard E2E (load, filter, drill batches) runs in the Part 5 E2E
// pass; this locks the filter/category derivation that the screen depends on.

function row(over: Partial<StockOnHandRow>): StockOnHandRow {
  return {
    product_id: "00000000-0000-0000-0000-000000000000",
    sku: "SKU",
    model_name: "Model",
    category: null,
    tracking_mode: "QUANTITY",
    quantity_on_hand: 1,
    ...over,
  }
}

const ROWS: StockOnHandRow[] = [
  row({ sku: "COMP-12", model_name: "Compressor", category: "Cooling" }),
  row({
    sku: "CABLE-USBC",
    model_name: "USB-C Cable",
    category: "Accessories",
  }),
  row({ sku: "FAN-09", model_name: "Axial Fan", category: "Cooling" }),
  row({ sku: "MISC-01", model_name: "Misc", category: null }),
]

test("deriveCategories returns sorted unique non-null categories", () => {
  expect(deriveCategories(ROWS)).toEqual(["Accessories", "Cooling"])
})

test("filter with no category and no query returns everything", () => {
  expect(filterStockRows(ROWS, { category: "", query: "" })).toHaveLength(4)
})

test("category filter keeps only exact matches", () => {
  const out = filterStockRows(ROWS, { category: "Cooling", query: "" })
  expect(out.map((r) => r.sku)).toEqual(["COMP-12", "FAN-09"])
})

test("query matches sku or model_name, case-insensitively", () => {
  expect(filterStockRows(ROWS, { category: "", query: "usb" })).toHaveLength(1)
  expect(filterStockRows(ROWS, { category: "", query: "fan" })[0].sku).toBe(
    "FAN-09",
  )
})

test("category and query combine (AND)", () => {
  const out = filterStockRows(ROWS, { category: "Cooling", query: "comp" })
  expect(out.map((r) => r.sku)).toEqual(["COMP-12"])
})
