import { describe, expect, it } from "vitest"

import type { ProductPublic } from "@/client/types.gen"
import {
  buildProductUpdate,
  canSaveProduct,
  productToDraft,
} from "./product-edit"

const baseProduct: ProductPublic = {
  id: "p1",
  sku: "WIDGET-Q3XZ",
  model_name: "Widget",
  brand: "Acme",
  category: "gadget",
  tracking_mode: "QUANTITY",
  retail_price_thb: "100.00",
  repair_price_thb: "20.00",
  default_min_stock_level: 5,
  is_active: true,
  is_fresh: true,
}

describe("productToDraft", () => {
  it("carries the SKU into the draft", () => {
    expect(productToDraft(baseProduct).sku).toBe("WIDGET-Q3XZ")
  })
})

describe("canSaveProduct", () => {
  it("requires a non-empty SKU", () => {
    const draft = productToDraft(baseProduct)
    expect(canSaveProduct(draft)).toBe(true)
    expect(canSaveProduct({ ...draft, sku: "   " })).toBe(false)
  })
})

describe("buildProductUpdate", () => {
  it("includes the trimmed SKU", () => {
    const draft = { ...productToDraft(baseProduct), sku: "  NEW-SKU  " }
    expect(buildProductUpdate(draft).sku).toBe("NEW-SKU")
  })
})
