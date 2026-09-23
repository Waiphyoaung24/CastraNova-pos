import { describe, expect, it } from "vitest"

import type {
  ProjectPullLinePublic,
  ProjectPullPublic,
} from "@/client/types.gen"
import {
  buildPullReturnPayload,
  canReturnPull,
  returnDraftTotal,
  returnedQty,
  setReturnQty,
} from "./pull-return"

const KEY = "11111111-1111-1111-1111-111111111111"

function line(over: Partial<ProjectPullLinePublic>): ProjectPullLinePublic {
  return {
    id: "l1",
    line_kind: "PART",
    product_id: "p1",
    product_sku: "SKU",
    model_name: "Bolt",
    unit_serial: null,
    requested_qty: 5,
    fulfilled_qty: 5,
    line_state: "FULFILLED",
    returnable_qty: 3,
    ...over,
  }
}

describe("pull return draft", () => {
  it("clamps to [0, returnable] and floors", () => {
    const l = line({})
    expect(setReturnQty({}, l, 9)).toEqual({ l1: 3 })
    expect(setReturnQty({}, l, -1)).toEqual({ l1: 0 })
    expect(setReturnQty({}, l, 2.7)).toEqual({ l1: 2 })
    expect(setReturnQty({}, l, Number.NaN)).toEqual({ l1: 0 })
  })

  it("sends only lines with something to return", () => {
    expect(buildPullReturnPayload({ l1: 2, l2: 0 }, KEY)).toEqual({
      idempotency_key: KEY,
      lines: [{ line_id: "l1", quantity: 2 }],
    })
    expect(returnDraftTotal({ l1: 2, l2: 0, l3: 1 })).toBe(3)
  })

  it("offers Return only on a settled pull with stock still out", () => {
    const pull = (state: ProjectPullPublic["state"], qty: number) =>
      ({ state, lines: [line({ returnable_qty: qty })] }) as ProjectPullPublic
    expect(canReturnPull(pull("FULFILLED", 1))).toBe(true)
    expect(canReturnPull(pull("CANCELLED", 1))).toBe(true)
    expect(canReturnPull(pull("PENDING", 1))).toBe(false) // use Cancel
    expect(canReturnPull(pull("SHORT", 0))).toBe(false)
  })
})

describe("returnedQty", () => {
  const pull = (state: ProjectPullPublic["state"]) =>
    ({ state }) as ProjectPullPublic

  it("is given-out minus still-out on a settled pull", () => {
    expect(returnedQty(pull("FULFILLED"), line({}))).toBe(2)
    expect(returnedQty(pull("SHORT"), line({ returnable_qty: 5 }))).toBe(0)
  })

  it("is zero before settlement or after cancel", () => {
    // A waiting pull has stock out but nothing given — never a return.
    expect(returnedQty(pull("PENDING"), line({ fulfilled_qty: 0 }))).toBe(0)
    expect(returnedQty(pull("CANCELLED"), line({}))).toBe(0)
  })
})
