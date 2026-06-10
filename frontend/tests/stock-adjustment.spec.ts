import { expect, test } from "@playwright/test"
import {
  type AdjustmentDraft,
  buildAdjustmentPayload,
  canSubmitAdjustment,
  emptyAdjustmentDraft,
} from "../src/lib/stock-adjustment"

// Pure-logic coverage of the Stock Adjustment form (FR-011 / Flow E). Mirrors
// the backend StockAdjustmentCreate validator so the UI never POSTs a body the
// server will 422. Full browser E2E runs in the Part 5 pass.

const KEY = "11111111-1111-1111-1111-111111111111"

function draft(over: Partial<AdjustmentDraft>): AdjustmentDraft {
  return { ...emptyAdjustmentDraft, ...over }
}

// --- canSubmit: shared ------------------------------------------------------

test("reason is always required", () => {
  expect(
    canSubmitAdjustment(
      draft({ targetKind: "UNIT", barcode: "CN-1", reason: "" }),
    ),
  ).toBe(false)
})

// --- canSubmit: UNIT --------------------------------------------------------

test("UNIT needs a barcode", () => {
  expect(
    canSubmitAdjustment(draft({ targetKind: "UNIT", reason: "lost" })),
  ).toBe(false)
  expect(
    canSubmitAdjustment(
      draft({ targetKind: "UNIT", barcode: "CN-1", reason: "lost" }),
    ),
  ).toBe(true)
})

// --- canSubmit: QUANTITY ----------------------------------------------------

test("QUANTITY needs a sku and a non-zero delta", () => {
  expect(
    canSubmitAdjustment(
      draft({ targetKind: "QUANTITY", qtyDelta: "-3", reason: "recount" }),
    ),
  ).toBe(false) // no sku
  expect(
    canSubmitAdjustment(
      draft({
        targetKind: "QUANTITY",
        sku: "CABLE",
        qtyDelta: "0",
        reason: "recount",
      }),
    ),
  ).toBe(false) // zero delta
  expect(
    canSubmitAdjustment(
      draft({
        targetKind: "QUANTITY",
        sku: "CABLE",
        qtyDelta: "-3",
        reason: "recount",
      }),
    ),
  ).toBe(true)
})

test("positive QUANTITY delta also requires a purchase cost", () => {
  expect(
    canSubmitAdjustment(
      draft({
        targetKind: "QUANTITY",
        sku: "CABLE",
        qtyDelta: "5",
        reason: "found",
      }),
    ),
  ).toBe(false)
  expect(
    canSubmitAdjustment(
      draft({
        targetKind: "QUANTITY",
        sku: "CABLE",
        qtyDelta: "5",
        purchaseCost: "12.50",
        reason: "found",
      }),
    ),
  ).toBe(true)
})

// --- buildAdjustmentPayload -------------------------------------------------

test("UNIT payload carries only barcode + reason", () => {
  const body = buildAdjustmentPayload(
    draft({ targetKind: "UNIT", barcode: "CN-1", reason: "lost" }),
    KEY,
  )
  expect(body).toEqual({
    target_kind: "UNIT",
    castranova_barcode: "CN-1",
    reason: "lost",
    idempotency_key: KEY,
  })
})

test("negative QUANTITY payload omits purchase cost", () => {
  const body = buildAdjustmentPayload(
    draft({
      targetKind: "QUANTITY",
      sku: "CABLE",
      qtyDelta: "-3",
      reason: "recount",
    }),
    KEY,
  )
  expect(body).toEqual({
    target_kind: "QUANTITY",
    sku: "CABLE",
    quantity_delta: -3,
    reason: "recount",
    idempotency_key: KEY,
  })
})

test("positive QUANTITY payload includes purchase cost", () => {
  const body = buildAdjustmentPayload(
    draft({
      targetKind: "QUANTITY",
      sku: "CABLE",
      qtyDelta: "5",
      purchaseCost: "12.50",
      reason: "found",
    }),
    KEY,
  )
  expect(body).toEqual({
    target_kind: "QUANTITY",
    sku: "CABLE",
    quantity_delta: 5,
    purchase_cost_thb: "12.50",
    reason: "found",
    idempotency_key: KEY,
  })
})
