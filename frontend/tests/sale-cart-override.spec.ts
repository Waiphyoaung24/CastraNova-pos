import { expect, test } from "@playwright/test"
import type { OverrideState } from "../src/client/types.gen"
import { canSubmitOverride, deviationPct } from "../src/lib/pricing-overrides"
import {
  applyOverride,
  buildSaleRequest,
  type CartLine,
  cartHasPendingOverride,
  cartSubtotalThb,
  clearOverride,
  type LineOverride,
  lineUnitPriceThb,
  removeLine,
  setLineQuantity,
} from "../src/lib/sale-cart"

// Pure-logic coverage of the FR-010 staff override in the sale cart.
// No browser / React / backend required — mirrors receive-form.spec.ts.

function partLine(key: string, price: number, quantity = 1): CartLine {
  return {
    key,
    lineKind: "PART",
    sku: key,
    productId: `prod-${key}`,
    quantity,
    unitPriceThb: price,
  }
}

function unitLine(key: string, price: number): CartLine {
  return {
    key,
    lineKind: "UNIT",
    barcode: key,
    sku: `sku-${key}`,
    productId: `prod-${key}`,
    quantity: 1,
    unitPriceThb: price,
  }
}

function override(
  state: OverrideState,
  requestedPriceThb = 1750,
): LineOverride {
  return { id: `ovr-${state}`, state, requestedPriceThb }
}

// --- applyOverride / clearOverride -----------------------------------------

test("applyOverride sets the override on the matching line without mutating input", () => {
  const input = [partLine("a", 1800), partLine("b", 500)]
  const next = applyOverride(input, "a", override("AUTO_APPROVED"))
  expect(next[0].override).toEqual(override("AUTO_APPROVED"))
  expect(next[1].override).toBeUndefined()
  expect(input[0].override).toBeUndefined()
  expect(next).not.toBe(input)
})

test("applyOverride with an unknown key returns the same reference", () => {
  const input = [partLine("a", 1800)]
  expect(applyOverride(input, "missing", override("AUTO_APPROVED"))).toBe(input)
})

test("applyOverride replaces an existing override (re-edit)", () => {
  const withPending = applyOverride(
    [partLine("a", 1800)],
    "a",
    override("PENDING", 900),
  )
  const next = applyOverride(withPending, "a", override("APPROVED", 900))
  expect(next[0].override?.state).toBe("APPROVED")
})

test("clearOverride removes the override and restores the retail price", () => {
  const withOverride = applyOverride(
    [partLine("a", 1800)],
    "a",
    override("PENDING", 900),
  )
  const next = clearOverride(withOverride, "a")
  expect(next[0].override).toBeUndefined()
  expect(lineUnitPriceThb(next[0])).toBe(1800)
})

// --- lineUnitPriceThb -------------------------------------------------------

test("lineUnitPriceThb: no override -> retail", () => {
  expect(lineUnitPriceThb(partLine("a", 1800))).toBe(1800)
})

test("lineUnitPriceThb: AUTO_APPROVED and APPROVED -> requested price", () => {
  for (const state of ["AUTO_APPROVED", "APPROVED"] as OverrideState[]) {
    const [line] = applyOverride([partLine("a", 1800)], "a", override(state))
    expect(lineUnitPriceThb(line)).toBe(1750)
  }
})

test("lineUnitPriceThb: PENDING and REJECTED -> retail", () => {
  for (const state of ["PENDING", "REJECTED"] as OverrideState[]) {
    const [line] = applyOverride([partLine("a", 1800)], "a", override(state))
    expect(lineUnitPriceThb(line)).toBe(1800)
  }
})

// --- subtotal / pending gate (S3.5 numbers) ---------------------------------

test("cartSubtotalThb uses approved override prices (2 x 1750 = 3500)", () => {
  const lines = applyOverride(
    [partLine("GAS-R404A", 1800, 2)],
    "GAS-R404A",
    override("AUTO_APPROVED", 1750),
  )
  expect(cartSubtotalThb(lines)).toBe(3500)
})

test("cartSubtotalThb ignores a pending override", () => {
  const lines = applyOverride(
    [partLine("GAS-R404A", 1800, 2)],
    "GAS-R404A",
    override("PENDING", 1750),
  )
  expect(cartSubtotalThb(lines)).toBe(3600)
})

test("cartHasPendingOverride is true only while a PENDING override exists", () => {
  const base = [partLine("a", 1800), unitLine("b", 12000)]
  expect(cartHasPendingOverride(base)).toBe(false)
  const pending = applyOverride(base, "b", override("PENDING", 10000))
  expect(cartHasPendingOverride(pending)).toBe(true)
  for (const state of [
    "AUTO_APPROVED",
    "APPROVED",
    "REJECTED",
  ] as OverrideState[]) {
    expect(
      cartHasPendingOverride(applyOverride(base, "b", override(state))),
    ).toBe(false)
  }
})

// --- buildSaleRequest -------------------------------------------------------

test("buildSaleRequest sends pricing_override_request_id only for AUTO_APPROVED/APPROVED", () => {
  for (const state of ["AUTO_APPROVED", "APPROVED"] as OverrideState[]) {
    const lines = applyOverride([partLine("a", 1800)], "a", override(state))
    const req = buildSaleRequest(lines, "cust-1", "idem-1")
    expect(req.lines[0].pricing_override_request_id).toBe(`ovr-${state}`)
  }
  for (const state of ["PENDING", "REJECTED"] as OverrideState[]) {
    const lines = applyOverride([partLine("a", 1800)], "a", override(state))
    const req = buildSaleRequest(lines, "cust-1", "idem-1")
    expect(req.lines[0].pricing_override_request_id).toBeUndefined()
  }
  const noOverride = buildSaleRequest([partLine("a", 1800)], "cust-1", "idem-1")
  expect(noOverride.lines[0].pricing_override_request_id).toBeUndefined()
})

test("buildSaleRequest still sends no price fields (backend authoritative)", () => {
  const lines = applyOverride(
    [unitLine("BC-1", 12000)],
    "BC-1",
    override("APPROVED", 10000),
  )
  const req = buildSaleRequest(lines, "cust-1", "idem-1")
  expect(req.lines[0]).toEqual({
    line_kind: "UNIT",
    castranova_barcode: "BC-1",
    quantity: 1,
    pricing_override_request_id: "ovr-APPROVED",
  })
})

test("buildSaleRequest maps mixed override states per line in one call", () => {
  let lines = [
    partLine("a", 1800),
    partLine("b", 500),
    unitLine("c", 12000),
    partLine("d", 900),
    partLine("e", 700),
  ]
  lines = applyOverride(lines, "a", override("AUTO_APPROVED", 1750))
  lines = applyOverride(lines, "b", override("PENDING", 450))
  lines = applyOverride(lines, "c", override("APPROVED", 10000))
  lines = applyOverride(lines, "d", override("REJECTED", 100))
  const req = buildSaleRequest(lines, "cust-1", "idem-1")
  expect(req.lines.map((l) => l.pricing_override_request_id)).toEqual([
    "ovr-AUTO_APPROVED",
    undefined,
    "ovr-APPROVED",
    undefined,
    undefined,
  ])
})

// --- quantity / removal preserve the override --------------------------------

test("setLineQuantity preserves the override; quantity edits keep the approved unit price", () => {
  const lines = applyOverride(
    [partLine("a", 1800)],
    "a",
    override("AUTO_APPROVED", 1750),
  )
  const next = setLineQuantity(lines, "a", 3)
  expect(next[0].override).toEqual(override("AUTO_APPROVED", 1750))
  expect(cartSubtotalThb(next)).toBe(5250)
})

test("removeLine drops the line together with its override", () => {
  const lines = applyOverride(
    [partLine("a", 1800)],
    "a",
    override("PENDING", 900),
  )
  expect(removeLine(lines, "a")).toEqual([])
})

// --- dialog helpers (S3.5 / S3.6 numbers) ------------------------------------

test("deviationPct is signed: (1800 -> 1750) ~ -2.8, (12000 -> 10000) ~ -16.7", () => {
  expect(deviationPct(1800, 1750)).toBeCloseTo(-2.78, 1)
  expect(deviationPct(12000, 10000)).toBeCloseTo(-16.67, 1)
  expect(deviationPct(1000, 1100)).toBeCloseTo(10, 5)
  expect(deviationPct(0, 500)).toBe(0)
})

test("canSubmitOverride requires a positive price and a non-blank reason", () => {
  expect(canSubmitOverride({ priceThb: "1750", reason: "matched quote" })).toBe(
    true,
  )
  expect(canSubmitOverride({ priceThb: "", reason: "matched quote" })).toBe(
    false,
  )
  expect(canSubmitOverride({ priceThb: "0", reason: "matched quote" })).toBe(
    false,
  )
  expect(canSubmitOverride({ priceThb: "-5", reason: "matched quote" })).toBe(
    false,
  )
  expect(canSubmitOverride({ priceThb: "abc", reason: "matched quote" })).toBe(
    false,
  )
  expect(canSubmitOverride({ priceThb: "1750", reason: "" })).toBe(false)
  expect(canSubmitOverride({ priceThb: "1750", reason: "   " })).toBe(false)
})
