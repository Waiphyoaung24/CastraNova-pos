import { describe, expect, it } from "vitest"

import type { SkuSearchResult, TrackingMode } from "@/client/types.gen"
import type { ScanLookupResult } from "@/hooks/useScanLookup"
import { addScanToCart, type CartLine } from "./sale-cart"

const PRODUCT_ID = "11111111-1111-1111-1111-111111111111"

function skuHit(trackingMode: TrackingMode): SkuSearchResult {
  return {
    sku: "WIDGET-Q3XZ",
    product_id: PRODUCT_ID,
    tracking_mode: trackingMode,
    total_on_hand: 3,
    batches: [],
    consumption: [],
  }
}

const priceMap = new Map<string, number>([[PRODUCT_ID, 100]])

describe("sale cart scan handling", () => {
  it("refuses a serialized sku scan instead of adding a PART line", () => {
    const scan: ScanLookupResult = {
      kind: "SERIALIZED_SKU",
      data: skuHit("SERIALIZED"),
    }
    const lines: CartLine[] = []

    expect(addScanToCart(lines, scan, priceMap)).toBe(lines)
  })

  it("still adds a quantity sku scan as a PART line", () => {
    const scan: ScanLookupResult = { kind: "PART", data: skuHit("QUANTITY") }

    const next = addScanToCart([], scan, priceMap)

    expect(next).toHaveLength(1)
    expect(next[0]).toMatchObject({
      lineKind: "PART",
      sku: "WIDGET-Q3XZ",
      quantity: 1,
      unitPriceThb: 100,
    })
  })
})
