import { expect, test } from "@playwright/test"
import { ApiError } from "../src/client/core/ApiError"
import type {
  SerialSearchResult,
  SkuSearchResult,
} from "../src/client/types.gen"
import { resolveScanResult } from "../src/hooks/useScanLookup"

// Pure-logic coverage of resolveScanResult (Task 2.4).
// No browser / React / backend required — mirrors scanner.spec.ts pattern.
// The hook itself (useScanLookup) composes this resolver with TanStack Query;
// that integration is covered by the Part 5 E2E pass.

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeApiError(status: number): ApiError {
  const request = { method: "GET" as const, url: "/api/v1/search/test" }
  const response = {
    body: { detail: "Not found" },
    ok: false,
    status,
    statusText: status === 404 ? "Not Found" : "Internal Server Error",
    url: "/api/v1/search/test",
  }
  return new ApiError(request, response, `HTTP error ${status}`)
}

const UNIT_RESULT: SerialSearchResult = {
  castranova_barcode: "CN-ABC123",
  product_id: "prod-uuid-1",
  sku: "SKU-001",
  supplier_serial: "SUP-SER-001",
  current_state: "IN_STOCK",
  movements: [],
}

const PART_RESULT: SkuSearchResult = {
  sku: "SKU-001",
  product_id: "prod-uuid-1",
  tracking_mode: "QUANTITY",
  total_on_hand: 5,
  batches: [],
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test("serial hit → UNIT result with the serial data", () => {
  const result = resolveScanResult(UNIT_RESULT, null)
  expect(result).toEqual({ kind: "UNIT", data: UNIT_RESULT })
})

test("serial 404 + sku hit → PART result with the sku data", () => {
  const result = resolveScanResult(makeApiError(404), PART_RESULT)
  expect(result).toEqual({ kind: "PART", data: PART_RESULT })
})

test("serial 404 + sku 404 → NOT_FOUND", () => {
  const result = resolveScanResult(makeApiError(404), makeApiError(404))
  expect(result).toEqual({ kind: "NOT_FOUND" })
})

test("serial 404 + null sku (defensive) → NOT_FOUND", () => {
  // Should not happen in normal flow but the function must be safe
  const result = resolveScanResult(makeApiError(404), null)
  expect(result).toEqual({ kind: "NOT_FOUND" })
})

test("serial non-404 error is re-thrown", () => {
  const err = makeApiError(500)
  expect(() => resolveScanResult(err, null)).toThrow(err)
})

test("sku non-404 error is re-thrown", () => {
  const err = makeApiError(503)
  expect(() => resolveScanResult(makeApiError(404), err)).toThrow(err)
})
