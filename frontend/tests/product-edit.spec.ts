import { expect, test } from "@playwright/test"
import type { ProductPublic } from "../src/client/types.gen"
import {
  buildProductUpdate,
  canSaveProduct,
  type ProductEditDraft,
  productToDraft,
} from "../src/lib/product-edit"

const baseProduct: ProductPublic = {
  id: "p1",
  sku: "S001",
  model_name: "Compressor",
  brand: "Hitec",
  category: "Machine",
  tracking_mode: "QUANTITY",
  retail_price_thb: "1800.00",
  repair_price_thb: "300.00",
  default_min_stock_level: 5,
}

const draft = (over: Partial<ProductEditDraft> = {}): ProductEditDraft => ({
  modelName: "Compressor",
  brand: "Hitec",
  category: "Machine",
  minStock: "5",
  retailPrice: "1800",
  repairPrice: "300",
  ...over,
})

test("productToDraft maps a product to editable strings", () => {
  expect(productToDraft(baseProduct)).toEqual({
    modelName: "Compressor",
    brand: "Hitec",
    category: "Machine",
    minStock: "5",
    retailPrice: "1800.00",
    repairPrice: "300.00",
  })
})

test("productToDraft blanks null brand/category/min-stock", () => {
  const d = productToDraft({
    ...baseProduct,
    brand: null,
    category: null,
    default_min_stock_level: null,
  })
  expect(d.brand).toBe("")
  expect(d.category).toBe("")
  expect(d.minStock).toBe("")
})

test("canSaveProduct requires model name and valid prices", () => {
  expect(canSaveProduct(draft())).toBe(true)
  expect(canSaveProduct(draft({ modelName: "   " }))).toBe(false)
  expect(canSaveProduct(draft({ retailPrice: "" }))).toBe(false)
  expect(canSaveProduct(draft({ retailPrice: "-1" }))).toBe(false)
  expect(canSaveProduct(draft({ repairPrice: "abc" }))).toBe(false)
})

test("buildProductUpdate trims and sends prices as strings", () => {
  expect(
    buildProductUpdate(draft({ retailPrice: " 1999 ", repairPrice: "350" })),
  ).toEqual({
    model_name: "Compressor",
    brand: "Hitec",
    category: "Machine",
    retail_price_thb: "1999",
    repair_price_thb: "350",
    default_min_stock_level: 5,
  })
})

test("buildProductUpdate sends null for cleared brand/category/min-stock", () => {
  expect(
    buildProductUpdate(draft({ brand: "  ", category: "", minStock: "" })),
  ).toEqual({
    model_name: "Compressor",
    brand: null,
    category: null,
    retail_price_thb: "1800",
    repair_price_thb: "300",
    default_min_stock_level: null,
  })
})

test("buildProductUpdate drops an invalid min-stock to null", () => {
  expect(
    buildProductUpdate(draft({ minStock: "-3" })).default_min_stock_level,
  ).toBe(null)
})

test("buildProductUpdate preserves a zero min-stock", () => {
  expect(
    buildProductUpdate(draft({ minStock: "0" })).default_min_stock_level,
  ).toBe(0)
})
