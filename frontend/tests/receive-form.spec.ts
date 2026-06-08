import { expect, test } from "@playwright/test"
import {
  addPiece,
  buildReceiveQuantityRequest,
  buildReceiveSerializedRequest,
  canSubmitQuantity,
  canSubmitSerialized,
  type DraftPiece,
  type QuantityDraft,
  removePiece,
  updatePiece,
} from "../src/lib/receive-form"

// Pure-logic coverage of the Receive screen's form logic (Task 4.1).
// No browser / React / backend required — mirrors useScanLookup.spec.ts pattern.
// The tab UI (Tasks 4.2/4.3) composes these pure functions with react-hook-form;
// that integration is covered by the Part 5 E2E pass.

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function piece(
  key: string,
  supplierSerial: string,
  purchaseCostThb: string,
): DraftPiece {
  return { key, supplierSerial, purchaseCostThb }
}

function validQuantityDraft(): QuantityDraft {
  return {
    productId: "prod-1",
    supplierId: "sup-1",
    receivedQty: "10",
    purchaseCostThb: "12.50",
    supplierBatchRef: "",
    expectedQty: "",
    note: "",
  }
}

// ---------------------------------------------------------------------------
// addPiece / removePiece / updatePiece — immutability
// ---------------------------------------------------------------------------

test("addPiece appends without mutating the input", () => {
  const input = [piece("a", "S1", "10")]
  const next = addPiece(input, piece("b", "S2", "20"))
  expect(next).toEqual([piece("a", "S1", "10"), piece("b", "S2", "20")])
  expect(input).toEqual([piece("a", "S1", "10")])
  expect(next).not.toBe(input)
})

test("removePiece drops the matching key without mutating input", () => {
  const input = [piece("a", "S1", "10"), piece("b", "S2", "20")]
  const next = removePiece(input, "a")
  expect(next).toEqual([piece("b", "S2", "20")])
  expect(input).toHaveLength(2)
  expect(next).not.toBe(input)
})

test("updatePiece patches only the matching key, immutably", () => {
  const input = [piece("a", "S1", "10"), piece("b", "S2", "20")]
  const next = updatePiece(input, "b", { purchaseCostThb: "99" })
  expect(next).toEqual([piece("a", "S1", "10"), piece("b", "S2", "99")])
  expect(input).toEqual([piece("a", "S1", "10"), piece("b", "S2", "20")])
  expect(next).not.toBe(input)
})

// ---------------------------------------------------------------------------
// buildReceiveSerializedRequest
// ---------------------------------------------------------------------------

test("buildReceiveSerializedRequest maps a 2-piece draft to the SDK shape", () => {
  const pieces = [piece("a", "  SER-1  ", "10.00"), piece("b", "SER-2", "11.5")]
  const req = buildReceiveSerializedRequest(
    pieces,
    "prod-1",
    "sup-1",
    "idem-123",
  )
  expect(req).toEqual({
    product_id: "prod-1",
    supplier_id: "sup-1",
    pieces: [
      { supplier_serial: "SER-1", purchase_cost_thb: "10.00" },
      { supplier_serial: "SER-2", purchase_cost_thb: "11.5" },
    ],
    idempotency_key: "idem-123",
  })
})

// ---------------------------------------------------------------------------
// buildReceiveQuantityRequest
// ---------------------------------------------------------------------------

test("buildReceiveQuantityRequest maps required fields + nulls blank optionals", () => {
  const req = buildReceiveQuantityRequest(validQuantityDraft(), "idem-q")
  expect(req).toEqual({
    product_id: "prod-1",
    supplier_id: "sup-1",
    received_qty: 10,
    purchase_cost_thb: "12.50",
    supplier_batch_ref: null,
    expected_qty: null,
    note: null,
    idempotency_key: "idem-q",
  })
})

test("buildReceiveQuantityRequest carries filled optionals (trimmed + coerced)", () => {
  const draft: QuantityDraft = {
    ...validQuantityDraft(),
    supplierBatchRef: "  BATCH-9  ",
    expectedQty: "12",
    note: "  partial  ",
  }
  const req = buildReceiveQuantityRequest(draft, "idem-q")
  expect(req).toEqual({
    product_id: "prod-1",
    supplier_id: "sup-1",
    received_qty: 10,
    purchase_cost_thb: "12.50",
    supplier_batch_ref: "BATCH-9",
    expected_qty: 12,
    note: "partial",
    idempotency_key: "idem-q",
  })
})

// ---------------------------------------------------------------------------
// canSubmitSerialized
// ---------------------------------------------------------------------------

test("canSubmitSerialized true on a valid draft", () => {
  const pieces = [piece("a", "SER-1", "10"), piece("b", "SER-2", "0.5")]
  expect(canSubmitSerialized(pieces, "prod-1", "sup-1")).toBe(true)
})

test("canSubmitSerialized false when there are no pieces", () => {
  expect(canSubmitSerialized([], "prod-1", "sup-1")).toBe(false)
})

test("canSubmitSerialized false when product is missing", () => {
  const pieces = [piece("a", "SER-1", "10")]
  expect(canSubmitSerialized(pieces, "", "sup-1")).toBe(false)
})

test("canSubmitSerialized false when supplier is missing", () => {
  const pieces = [piece("a", "SER-1", "10")]
  expect(canSubmitSerialized(pieces, "prod-1", "")).toBe(false)
})

test("canSubmitSerialized false when a piece has a blank serial", () => {
  const pieces = [piece("a", "SER-1", "10"), piece("b", "   ", "10")]
  expect(canSubmitSerialized(pieces, "prod-1", "sup-1")).toBe(false)
})

test("canSubmitSerialized false when a piece cost is 0 or non-numeric", () => {
  expect(
    canSubmitSerialized([piece("a", "SER-1", "0")], "prod-1", "sup-1"),
  ).toBe(false)
  expect(
    canSubmitSerialized([piece("a", "SER-1", "abc")], "prod-1", "sup-1"),
  ).toBe(false)
})

// ---------------------------------------------------------------------------
// canSubmitQuantity
// ---------------------------------------------------------------------------

test("canSubmitQuantity true on a valid draft", () => {
  expect(canSubmitQuantity(validQuantityDraft())).toBe(true)
})

test("canSubmitQuantity false for qty 0", () => {
  expect(canSubmitQuantity({ ...validQuantityDraft(), receivedQty: "0" })).toBe(
    false,
  )
})

test("canSubmitQuantity false for non-numeric qty", () => {
  expect(
    canSubmitQuantity({ ...validQuantityDraft(), receivedQty: "abc" }),
  ).toBe(false)
})

test("canSubmitQuantity false for non-integer qty", () => {
  expect(
    canSubmitQuantity({ ...validQuantityDraft(), receivedQty: "1.5" }),
  ).toBe(false)
})

test("canSubmitQuantity false when cost is 0", () => {
  expect(
    canSubmitQuantity({ ...validQuantityDraft(), purchaseCostThb: "0" }),
  ).toBe(false)
})

test("canSubmitQuantity false when product or supplier is missing", () => {
  expect(canSubmitQuantity({ ...validQuantityDraft(), productId: "" })).toBe(
    false,
  )
  expect(canSubmitQuantity({ ...validQuantityDraft(), supplierId: "" })).toBe(
    false,
  )
})
