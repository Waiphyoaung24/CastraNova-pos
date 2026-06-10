import { expect, test } from "@playwright/test"
import { buildAuditQuery } from "../src/lib/audit"

// Pure-logic coverage for the admin audit ledger filters (FR-019). Blank
// filters are dropped so the request only constrains what the admin set.

test("buildAuditQuery drops blank filters", () => {
  expect(buildAuditQuery({ eventType: "", fromDate: "", toDate: "" })).toEqual(
    {},
  )
})

test("buildAuditQuery includes set filters", () => {
  expect(
    buildAuditQuery({
      eventType: "SOLD",
      fromDate: "2026-06-01",
      toDate: "2026-07-01",
    }),
  ).toEqual({
    eventType: "SOLD",
    fromDate: "2026-06-01",
    toDate: "2026-07-01",
  })
})
