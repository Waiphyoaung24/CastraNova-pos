import { describe, expect, it } from "vitest"

import { ApiError } from "@/client"
import type {
  ReturnablePullsPublic,
  ReturnableSalesPublic,
} from "@/client/types.gen"
import {
  buildPullReturnPayload,
  buildReturnPayload,
  canSubmitReturn,
  clampReturnQuantity,
  emptyReturnDraft,
  lookupErrorMessage,
  pickerOptions,
  type ReturnDraft,
} from "./sale-return"

function apiError(status: number, body: unknown): ApiError {
  return new ApiError(
    { method: "GET", url: "/api/v1/sales/returnable" },
    { url: "", ok: false, status, statusText: "", body },
    "boom",
  )
}

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

describe("lookupErrorMessage", () => {
  it("names an unknown SKU on a 404", () => {
    expect(
      lookupErrorMessage(apiError(404, { detail: "Product not found" })),
    ).toBe("No product with this SKU.")
  })

  it("surfaces the server reason on any other API error", () => {
    expect(
      lookupErrorMessage(
        apiError(422, {
          detail: "Provide exactly one of castranova_barcode or sku",
        }),
      ),
    ).toBe("Provide exactly one of castranova_barcode or sku")
  })

  it("does not render a validation array as [object Object]", () => {
    expect(
      lookupErrorMessage(
        apiError(422, { detail: [{ loc: ["query", "sku"], msg: "bad sku" }] }),
      ),
    ).toBe("bad sku")
  })

  it("falls back to a generic message for non-API failures", () => {
    expect(lookupErrorMessage(new Error("network down"))).toBe(
      "Could not look up returnable sales.",
    )
  })
})

const sales: ReturnableSalesPublic = {
  sales: [
    {
      sale_id: "s1",
      sold_at: "2026-09-20T10:00:00Z",
      customer_id: "c1",
      customer_name: "Thiri Trading",
      lines: [
        {
          sale_line_id: "sl1",
          line_kind: "PART",
          product_id: "p1",
          unit_id: null,
          label: "BAT — Battery",
          quantity_sold: 2,
          quantity_returned: 0,
          quantity_returnable: 2,
          unit_price_thb: "1900.00",
        },
      ],
    },
  ],
}
const pulls: ReturnablePullsPublic = {
  pulls: [
    {
      pull_id: "pu1",
      project_code: "PRJ-9",
      project_name: "Refit",
      customer_name: "Ko Min",
      created_at: "2026-09-21T10:00:00Z",
      lines: [
        {
          line_id: "pl1",
          line_kind: "PART",
          product_id: "p1",
          label: "BAT — Battery",
          quantity_out: 7,
          quantity_returnable: 5,
        },
      ],
    },
  ],
}

describe("returns picker with project pulls", () => {
  it("merges newest first across sales and pulls with prefixed values", () => {
    const opts = pickerOptions(sales, pulls)
    expect(opts.map((o) => o.value)).toEqual(["pull:pl1", "sale:sl1"])
    expect(opts[0].label).toContain("Refit (PRJ-9)")
    expect(opts[0].label).toContain("Ko Min")
    expect(opts[0].label).toContain("5 of 7 returnable")
    expect(opts[0]).toMatchObject({
      source: "pull",
      pullId: "pu1",
      lineId: "pl1",
      quantityReturnable: 5,
    })
    expect(opts[1]).toMatchObject({
      source: "sale",
      saleId: "s1",
      lineId: "sl1",
      quantityReturnable: 2,
    })
  })

  it("does not require a reason for a pull return", () => {
    const d = draft({
      source: "pull",
      pullId: "pu1",
      saleLineId: "pl1",
      quantity: "3",
      reason: "",
    })
    expect(canSubmitReturn(d, 5)).toBe(true)
    expect(
      canSubmitReturn(
        draft({ source: "sale", saleLineId: "sl1", quantity: "1", reason: "" }),
        2,
      ),
    ).toBe(false)
  })

  it("pull payload has no reason", () => {
    const d = draft({
      source: "pull",
      pullId: "pu1",
      saleLineId: "pl1",
      quantity: "3",
    })
    expect(buildPullReturnPayload(d, KEY)).toEqual({
      idempotency_key: KEY,
      lines: [{ line_id: "pl1", quantity: 3 }],
    })
  })
})
