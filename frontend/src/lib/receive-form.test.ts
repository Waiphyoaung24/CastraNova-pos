import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import {
  buildReceiveQuantityRequest,
  buildReceiveSerializedRequest,
  canSubmitQuantity,
  canSubmitSerialized,
  isValidReceivedDate,
  type QuantityDraft,
  todayISO,
} from "./receive-form"

const VALID_DRAFT: QuantityDraft = {
  productId: "p1",
  supplierId: "s1",
  receivedQty: "10",
  purchaseCostThb: "5.00",
  supplierBatchRef: "",
  expectedQty: "",
  note: "",
  receivedDate: "2026-07-10",
}

describe("todayISO", () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it("returns the LOCAL date as YYYY-MM-DD", () => {
    // 23:30 local on 25 Jul. toISOString() would report the 26th in any zone
    // west of UTC — we always want the operator's wall-clock date.
    vi.setSystemTime(new Date(2026, 6, 25, 23, 30))
    expect(todayISO()).toBe("2026-07-25")
  })

  it("zero-pads single-digit months and days", () => {
    vi.setSystemTime(new Date(2026, 0, 5, 12, 0))
    expect(todayISO()).toBe("2026-01-05")
  })
})

describe("isValidReceivedDate", () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 6, 25, 12, 0))
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it("accepts today", () => {
    expect(isValidReceivedDate("2026-07-25")).toBe(true)
  })

  it("accepts a past date", () => {
    expect(isValidReceivedDate("2026-07-10")).toBe(true)
  })

  it("rejects a future date", () => {
    expect(isValidReceivedDate("2026-07-26")).toBe(false)
  })

  it("rejects an empty or malformed value", () => {
    expect(isValidReceivedDate("")).toBe(false)
    expect(isValidReceivedDate("10/07/2026")).toBe(false)
  })
})

describe("buildReceiveQuantityRequest", () => {
  it("passes received_date through untouched", () => {
    const req = buildReceiveQuantityRequest(VALID_DRAFT, "idem-1")
    expect(req.received_date).toBe("2026-07-10")
  })
})

describe("buildReceiveSerializedRequest", () => {
  it("passes received_date through untouched", () => {
    const req = buildReceiveSerializedRequest(
      [{ key: "k1", supplierSerial: "SN-1", purchaseCostThb: "900" }],
      "p1",
      "s1",
      "idem-1",
      "2026-07-10",
    )
    expect(req.received_date).toBe("2026-07-10")
  })
})

describe("submit guards reject a bad date", () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 6, 25, 12, 0))
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it("canSubmitQuantity is false when the date is cleared", () => {
    expect(canSubmitQuantity(VALID_DRAFT)).toBe(true)
    expect(canSubmitQuantity({ ...VALID_DRAFT, receivedDate: "" })).toBe(false)
  })

  it("canSubmitQuantity is false when the date is in the future", () => {
    expect(
      canSubmitQuantity({ ...VALID_DRAFT, receivedDate: "2026-08-01" }),
    ).toBe(false)
  })

  it("canSubmitSerialized is false when the date is cleared", () => {
    const pieces = [
      { key: "k1", supplierSerial: "SN-1", purchaseCostThb: "900" },
    ]
    expect(canSubmitSerialized(pieces, "p1", "s1", "2026-07-10")).toBe(true)
    expect(canSubmitSerialized(pieces, "p1", "s1", "")).toBe(false)
  })
})
