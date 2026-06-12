import { expect, test } from "@playwright/test"
import type { OverrideState } from "../src/client/types.gen"
import { formatDeviationPct, isPending } from "../src/lib/pricing-overrides"

// Pure-logic coverage for the pricing-override approval queue (FR-010).
// `isPending` gates the Approve/Reject actions (only PENDING rows are
// decidable — mirrors the backend); `formatDeviationPct` renders the stored
// percent value. The in-browser queue E2E runs in the Part 5 E2E pass.

test("formatDeviationPct renders the stored percent to 2dp with a % sign", () => {
  expect(formatDeviationPct("3.0000")).toBe("3.00%")
  expect(formatDeviationPct("10.5")).toBe("10.50%")
})

test("isPending is true only for PENDING", () => {
  expect(isPending("PENDING")).toBe(true)
  for (const s of [
    "AUTO_APPROVED",
    "APPROVED",
    "REJECTED",
  ] as OverrideState[]) {
    expect(isPending(s)).toBe(false)
  }
})
