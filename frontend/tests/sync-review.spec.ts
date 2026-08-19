import { expect, test } from "@playwright/test"
import type { SyncReviewState } from "../src/client/types.gen"
import { isResolvable } from "../src/lib/sync-review"

// Pure-logic coverage for the admin sync-review queue (§6.7). Only PENDING
// items can be resolved/discarded (mirrors the backend) — this gates the
// Discard action.

test("isResolvable is true only for PENDING", () => {
  expect(isResolvable("PENDING")).toBe(true)
  for (const s of ["RESOLVED", "DISCARDED"] as SyncReviewState[]) {
    expect(isResolvable(s)).toBe(false)
  }
})
