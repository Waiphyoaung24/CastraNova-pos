import { describe, expect, it } from "vitest"

import {
  buildReturnPayload,
  canSubmitReturn,
  clampReturnQuantity,
  emptyReturnDraft,
  type ReturnDraft,
} from "./sale-return"

const KEY = "11111111-1111-1111-1111-111111111111"

function draft(over: Partial<ReturnDraft>): ReturnDraft {
  return { ...emptyReturnDraft, ...over }
}

describe("sale return form logic", () => {
  it("requires a sale line, a reason, and a quantity", () => {
    expect(
      canSubmitReturn(draft({ saleLineId: "", reason: "x", quantity: "1" }), 5),
    ).toBe(false)
    expect(
      canSubmitReturn(draft({ saleLineId: "L", reason: "", quantity: "1" }), 5),
    ).toBe(false)
    expect(
      canSubmitReturn(draft({ saleLineId: "L", reason: "x", quantity: "" }), 5),
    ).toBe(false)
    expect(
      canSubmitReturn(
        draft({ saleLineId: "L", reason: "x", quantity: "1" }),
        5,
      ),
    ).toBe(true)
  })

  it("caps the quantity at what is still returnable", () => {
    expect(
      canSubmitReturn(
        draft({ saleLineId: "L", reason: "x", quantity: "5" }),
        5,
      ),
    ).toBe(true)
    expect(
      canSubmitReturn(
        draft({ saleLineId: "L", reason: "x", quantity: "6" }),
        5,
      ),
    ).toBe(false)
    expect(
      canSubmitReturn(
        draft({ saleLineId: "L", reason: "x", quantity: "0" }),
        5,
      ),
    ).toBe(false)
    expect(
      canSubmitReturn(
        draft({ saleLineId: "L", reason: "x", quantity: "-1" }),
        5,
      ),
    ).toBe(false)
  })

  it("rejects non-integer quantities", () => {
    expect(
      canSubmitReturn(
        draft({ saleLineId: "L", reason: "x", quantity: "1.5" }),
        5,
      ),
    ).toBe(false)
    expect(
      canSubmitReturn(
        draft({ saleLineId: "L", reason: "x", quantity: "abc" }),
        5,
      ),
    ).toBe(false)
  })

  it("nothing is returnable when the cap is zero", () => {
    expect(
      canSubmitReturn(
        draft({ saleLineId: "L", reason: "x", quantity: "1" }),
        0,
      ),
    ).toBe(false)
  })

  it("keeps typed quantities to digits only", () => {
    expect(clampReturnQuantity("3", 99)).toBe("3")
    expect(clampReturnQuantity("1.5", 99)).toBe("15")
    expect(clampReturnQuantity("-2", 99)).toBe("2")
    expect(clampReturnQuantity("abc", 99)).toBe("")
  })

  it("clamps a typed quantity to the returnable cap", () => {
    expect(clampReturnQuantity("5", 5)).toBe("5")
    expect(clampReturnQuantity("6", 5)).toBe("5")
    expect(clampReturnQuantity("99", 5)).toBe("5")
  })

  it("never leaves a zero or a leading zero in the field", () => {
    expect(clampReturnQuantity("0", 5)).toBe("")
    expect(clampReturnQuantity("03", 5)).toBe("3")
  })

  it("allows an empty field so the operator can retype", () => {
    expect(clampReturnQuantity("", 5)).toBe("")
  })

  it("builds a single-line payload with the trimmed reason", () => {
    expect(
      buildReturnPayload(
        draft({
          saleId: "S",
          saleLineId: "L",
          quantity: "3",
          reason: "  faulty  ",
        }),
        KEY,
      ),
    ).toEqual({
      idempotency_key: KEY,
      reason: "faulty",
      lines: [{ sale_line_id: "L", quantity: 3 }],
    })
  })
})
