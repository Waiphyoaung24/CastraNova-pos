import { describe, expect, it } from "vitest"

import { ApiError } from "@/client/core/ApiError"
import type { SkuSearchResult, TrackingMode } from "@/client/types.gen"
import { resolveScanResult } from "./useScanLookup"

function apiError(status: number): ApiError {
  return new ApiError(
    { method: "GET", url: "/api/v1/search/serial/{barcode}" },
    { url: "", ok: false, status, statusText: "", body: undefined },
    "boom",
  )
}

function skuHit(trackingMode: TrackingMode): SkuSearchResult {
  return {
    sku: "WIDGET-Q3XZ",
    product_id: "11111111-1111-1111-1111-111111111111",
    tracking_mode: trackingMode,
    total_on_hand: 3,
    batches: [],
    consumption: [],
  }
}

describe("scan lookup classification", () => {
  it("classifies a SERIALIZED sku hit as SERIALIZED_SKU, not PART", () => {
    const result = resolveScanResult(apiError(404), skuHit("SERIALIZED"))

    expect(result.kind).toBe("SERIALIZED_SKU")
  })

  it("still classifies a QUANTITY sku hit as PART", () => {
    const result = resolveScanResult(apiError(404), skuHit("QUANTITY"))

    expect(result.kind).toBe("PART")
  })

  it("still classifies a serial hit as UNIT without consulting the sku", () => {
    const serial = {
      castranova_barcode: "CN-0001",
      product_id: "11111111-1111-1111-1111-111111111111",
      sku: "WIDGET-Q3XZ",
      supplier_serial: "SN-1",
      current_state: "IN_STOCK" as const,
      movements: [],
    }

    expect(resolveScanResult(serial, null).kind).toBe("UNIT")
  })
})
