import { expect, test } from "@playwright/test"
import {
  buildProductPayload,
  canCreateProduct,
} from "../src/lib/product-create"

// Pure form logic for the admin Products create form (FR-001). sku + model +
// both prices are required and prices must be valid non-negative numbers;
// blank optionals (brand/category/min-level) are dropped.

const base = {
  sku: "COMP-12",
  modelName: "Compressor",
  brand: "",
  category: "",
  trackingMode: "QUANTITY" as const,
  retailPrice: "1200",
  repairPrice: "300",
  minStock: "",
}

test("canCreateProduct requires sku, model, and valid non-negative prices", () => {
  expect(canCreateProduct(base)).toBe(true)
  expect(canCreateProduct({ ...base, sku: " " })).toBe(false)
  expect(canCreateProduct({ ...base, modelName: "" })).toBe(false)
  expect(canCreateProduct({ ...base, retailPrice: "" })).toBe(false)
  expect(canCreateProduct({ ...base, repairPrice: "abc" })).toBe(false)
  expect(canCreateProduct({ ...base, retailPrice: "-5" })).toBe(false)
})

test("buildProductPayload trims, sends prices as strings, drops blank optionals", () => {
  expect(
    buildProductPayload({
      ...base,
      brand: " Bosch ",
      category: "",
      minStock: "4",
    }),
  ).toEqual({
    sku: "COMP-12",
    model_name: "Compressor",
    tracking_mode: "QUANTITY",
    retail_price_thb: "1200",
    repair_price_thb: "300",
    brand: "Bosch",
    default_min_stock_level: 4,
  })
})
