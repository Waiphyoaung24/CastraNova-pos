import { expect, test } from "@playwright/test"
import {
  channelMarginExport,
  currentMonth,
  formatThb,
  holdingPeriodExport,
  isValidMonth,
} from "../src/lib/reports"

// Pure-logic coverage of the admin report screens (FR-013 channel margin,
// FR-014 holding period). The full in-browser report E2E runs in the Part 5
// pass; this locks the money formatting, month handling, and export
// URL/filename builders the screens depend on.

// --- formatThb --------------------------------------------------------------

test("formatThb renders a decimal string as ฿ with thousands + 2dp", () => {
  expect(formatThb("1400.00")).toBe("฿1,400.00")
  expect(formatThb("3000")).toBe("฿3,000.00")
  expect(formatThb("3000.5")).toBe("฿3,000.50")
  expect(formatThb("0.00")).toBe("฿0.00")
})

// --- currentMonth -----------------------------------------------------------

test("currentMonth formats YYYY-MM zero-padded", () => {
  // Local-constructor dates keep getMonth() deterministic across timezones.
  expect(currentMonth(new Date(2026, 5, 10))).toBe("2026-06")
  expect(currentMonth(new Date(2026, 0, 5))).toBe("2026-01")
  expect(currentMonth(new Date(2026, 11, 31))).toBe("2026-12")
})

// --- isValidMonth -----------------------------------------------------------

test("isValidMonth accepts YYYY-MM and rejects anything else", () => {
  expect(isValidMonth("2026-06")).toBe(true)
  expect(isValidMonth("")).toBe(false)
  expect(isValidMonth("2026")).toBe(false)
  expect(isValidMonth("2026-6")).toBe(false)
  expect(isValidMonth("June 2026")).toBe(false)
})

// --- channelMarginExport ----------------------------------------------------

test("channelMarginExport builds the authed path + filename per format", () => {
  expect(channelMarginExport("2026-06", "pdf")).toEqual({
    path: "/api/v1/reports/channel-margin.pdf?month=2026-06",
    filename: "channel-margin-2026-06.pdf",
  })
  expect(channelMarginExport("2026-06", "xlsx")).toEqual({
    path: "/api/v1/reports/channel-margin.xlsx?month=2026-06",
    filename: "channel-margin-2026-06.xlsx",
  })
})

// --- holdingPeriodExport ----------------------------------------------------

test("holdingPeriodExport encodes the over-threshold flag per format", () => {
  expect(holdingPeriodExport(true, "pdf")).toEqual({
    path: "/api/v1/reports/holding-period.pdf?over_threshold_only=true",
    filename: "holding-period.pdf",
  })
  expect(holdingPeriodExport(false, "xlsx")).toEqual({
    path: "/api/v1/reports/holding-period.xlsx?over_threshold_only=false",
    filename: "holding-period.xlsx",
  })
})
