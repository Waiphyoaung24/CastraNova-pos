import { describe, expect, it } from "vitest"

import type {
  SkuBatchAdminPublic,
  SkuBatchPublic,
  SkuSearchAdminResult,
  SkuSearchResult,
} from "@/client/types.gen"

import { latestCostBatch } from "./stock-adjustment"

function adminBatch(
  batchNo: string,
  receivedAt: string,
  cost: string,
): SkuBatchAdminPublic {
  return {
    batch_no: batchNo,
    received_at: receivedAt,
    received_qty: 10,
    remaining_qty: 10,
    is_adjustment: false,
    purchase_cost_thb: cost,
  }
}

function adminResult(batches: SkuBatchAdminPublic[]): SkuSearchAdminResult {
  return {
    sku: "HPEOK-D-48-O93D",
    product_id: "11111111-1111-1111-1111-111111111111",
    tracking_mode: "QUANTITY",
    total_on_hand: 20,
    batches,
    consumption: [],
  }
}

describe("latestCostBatch", () => {
  it("returns the last batch — the backend orders them oldest-first", () => {
    const res = adminResult([
      adminBatch("B-1", "2026-05-01T00:00:00Z", "50.00"),
      adminBatch("B-2", "2026-06-01T00:00:00Z", "55.00"),
      adminBatch("B-3", "2026-07-12T00:00:00Z", "58.00"),
    ])
    expect(latestCostBatch(res)?.purchase_cost_thb).toBe("58.00")
  })

  it("returns the only batch when there is one", () => {
    const res = adminResult([
      adminBatch("B-1", "2026-07-12T00:00:00Z", "58.00"),
    ])
    expect(latestCostBatch(res)?.batch_no).toBe("B-1")
  })

  it("returns null for a SKU with no batches (SERIALIZED, or never received)", () => {
    expect(latestCostBatch(adminResult([]))).toBeNull()
  })

  it("returns null for a staff-shaped result, which carries no cost", () => {
    const staffBatch: SkuBatchPublic = {
      batch_no: "B-1",
      received_at: "2026-07-12T00:00:00Z",
      received_qty: 10,
      remaining_qty: 10,
      is_adjustment: false,
    }
    const res: SkuSearchResult = {
      sku: "HPEOK-D-48-O93D",
      product_id: "11111111-1111-1111-1111-111111111111",
      tracking_mode: "QUANTITY",
      total_on_hand: 10,
      batches: [staffBatch],
    }
    expect(latestCostBatch(res)).toBeNull()
  })

  it("returns null while the query has not resolved", () => {
    expect(latestCostBatch(undefined)).toBeNull()
  })
})
