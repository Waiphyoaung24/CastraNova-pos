import { describe, expect, it } from "vitest"

import {
  isSensitiveStockQueryKey,
  stockDrillQueryKey,
} from "./stock-query-cache"

describe("stock drill query cache", () => {
  it("partitions drill data by authorization tier", () => {
    expect(stockDrillQueryKey("batches", "product-1", true)).not.toEqual(
      stockDrillQueryKey("batches", "product-1", false),
    )
    expect(stockDrillQueryKey("units", "product-1", true)).not.toEqual(
      stockDrillQueryKey("units", "product-1", false),
    )
  })

  it("identifies both legacy and tiered drill keys as sensitive", () => {
    expect(isSensitiveStockQueryKey(["stock-batches", "product-1"])).toBe(true)
    expect(
      isSensitiveStockQueryKey(["stock-units", "product-1", "admin"]),
    ).toBe(true)
    expect(isSensitiveStockQueryKey(["stock-on-hand", { page: 1 }])).toBe(false)
  })
})
