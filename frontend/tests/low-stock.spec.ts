import { expect, test } from "@playwright/test"
import { buildBulkMinStockUpdate } from "../src/lib/low-stock"

// Pure-logic coverage for the low-stock dashboard's bulk min-level save
// (FR-016). Only rows the admin actually changed to a valid non-negative
// integer are sent; blanks, invalid, and unchanged rows are dropped. The
// in-browser dashboard E2E runs in the Part 5 pass.

test("includes only changed, valid, non-negative integer levels", () => {
  const out = buildBulkMinStockUpdate([
    { productId: "a", value: "5", original: 3 }, // changed → in
    { productId: "b", value: "3", original: 3 }, // unchanged → out
    { productId: "c", value: "", original: 2 }, // blank → out
    { productId: "d", value: "-1", original: 2 }, // negative → out
    { productId: "e", value: "2.5", original: 2 }, // non-integer → out
    { productId: "f", value: "0", original: 4 }, // zero is valid + changed → in
  ])
  expect(out).toEqual([
    { product_id: "a", min_stock_level: 5 },
    { product_id: "f", min_stock_level: 0 },
  ])
})

test("returns empty when nothing changed", () => {
  expect(
    buildBulkMinStockUpdate([{ productId: "a", value: "3", original: 3 }]),
  ).toEqual([])
})
