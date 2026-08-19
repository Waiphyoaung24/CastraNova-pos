import { expect, test } from "@playwright/test"
import {
  channelMarginExport,
  currentMonth,
  formatPct,
  formatThb,
  holdingBucketLabel,
  holdingPeriodExport,
  isValidMonth,
  marginPct,
  momChange,
  overrideExceptionsExport,
  pointChange,
  previousMonth,
  sharePct,
  summarizeHolding,
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

// --- previousMonth ----------------------------------------------------------

test("previousMonth steps back one month, rolling the year in January", () => {
  expect(previousMonth("2026-06")).toBe("2026-05")
  expect(previousMonth("2026-01")).toBe("2025-12")
  expect(previousMonth("2026-10")).toBe("2026-09")
})

// --- channelMarginExport ----------------------------------------------------

test("channelMarginExport encodes group_by and optional channel", () => {
  expect(channelMarginExport("2026-03", "pdf", "channel")).toEqual({
    path: "/api/v1/reports/channel-margin.pdf?month=2026-03&group_by=channel",
    filename: "channel-margin-2026-03-by-channel.pdf",
  })
  expect(channelMarginExport("2026-03", "xlsx", "product", "SALE")).toEqual({
    path: "/api/v1/reports/channel-margin.xlsx?month=2026-03&group_by=product&channel=SALE",
    filename: "channel-margin-2026-03-by-product-SALE.xlsx",
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

// --- overrideExceptionsExport -----------------------------------------------

test("overrideExceptionsExport builds the authed path + filename per format", () => {
  expect(overrideExceptionsExport("2026-06", "pdf")).toEqual({
    path: "/api/v1/reports/override-exceptions.pdf?month=2026-06",
    filename: "override-exceptions-2026-06.pdf",
  })
  expect(overrideExceptionsExport("2026-06", "xlsx")).toEqual({
    path: "/api/v1/reports/override-exceptions.xlsx?month=2026-06",
    filename: "override-exceptions-2026-06.xlsx",
  })
})

// --- formatPct --------------------------------------------------------------

test("formatPct renders a number with a % suffix and 1dp by default", () => {
  expect(formatPct(42.5)).toBe("42.5%")
  expect(formatPct(0)).toBe("0.0%")
  expect(formatPct(33.333)).toBe("33.3%")
  expect(formatPct(50, 0)).toBe("50%")
})

// --- marginPct --------------------------------------------------------------

test("marginPct divides margin by revenue, null when revenue is zero", () => {
  expect(marginPct("400", "1000")).toBe(40)
  expect(marginPct("0", "1000")).toBe(0)
  expect(marginPct("400", "0")).toBeNull()
})

// --- sharePct ---------------------------------------------------------------

test("sharePct returns the part's share of the total, 0 when total is zero", () => {
  expect(sharePct("250", "1000")).toBe(25)
  expect(sharePct("1000", "1000")).toBe(100)
  expect(sharePct("5", "0")).toBe(0)
})

// --- momChange --------------------------------------------------------------

test("momChange computes magnitude + direction + good, inverting for costs", () => {
  expect(momChange("1100", "1000")).toEqual({
    value: "10.0%",
    direction: "up",
    good: true,
  })
  expect(momChange("900", "1000")).toEqual({
    value: "10.0%",
    direction: "down",
    good: false,
  })
  // Cost-like metric: an increase is bad.
  expect(momChange("1100", "1000", { invert: true })).toEqual({
    value: "10.0%",
    direction: "up",
    good: false,
  })
  // No comparable prior value -> null (missing or zero).
  expect(momChange("1100", undefined)).toBeNull()
  expect(momChange("1100", "0")).toBeNull()
  // Sub-epsilon move reads as flat.
  expect(momChange("1000", "1000")).toEqual({
    value: "0.0%",
    direction: "flat",
    good: false,
  })
})

// --- pointChange ------------------------------------------------------------

test("pointChange reports a percentage-point difference, null without prior", () => {
  expect(pointChange(42, 38)).toEqual({
    value: "4.0 pp",
    direction: "up",
    good: true,
  })
  expect(pointChange(38, 42)).toEqual({
    value: "4.0 pp",
    direction: "down",
    good: false,
  })
  expect(pointChange(42, null)).toBeNull()
})

// --- holdingBucketLabel -----------------------------------------------------

test("holdingBucketLabel maps days to ageing buckets", () => {
  expect(holdingBucketLabel(0)).toBe("0–30")
  expect(holdingBucketLabel(30)).toBe("0–30")
  expect(holdingBucketLabel(31)).toBe("31–60")
  expect(holdingBucketLabel(60)).toBe("31–60")
  expect(holdingBucketLabel(90)).toBe("61–90")
  expect(holdingBucketLabel(91)).toBe("90+")
  expect(holdingBucketLabel(400)).toBe("90+")
})

// --- summarizeHolding -------------------------------------------------------

test("summarizeHolding rolls rows into buckets and headline figures", () => {
  const summary = summarizeHolding([
    { holding_days: 10, quantity: 2, over_threshold: false },
    { holding_days: 45, quantity: 1, over_threshold: false },
    { holding_days: 120, quantity: 5, over_threshold: true },
    { holding_days: 200, quantity: 3, over_threshold: true },
  ])
  expect(summary.lineCount).toBe(4)
  expect(summary.totalQty).toBe(11)
  expect(summary.overThresholdCount).toBe(2)
  expect(summary.maxDays).toBe(200)
  expect(summary.avgDays).toBe(94) // round((10+45+120+200)/4) = round(93.75)
  expect(
    summary.buckets.map((b) => ({
      label: b.label,
      count: b.count,
      qty: b.qty,
    })),
  ).toEqual([
    { label: "0–30", count: 1, qty: 2 },
    { label: "31–60", count: 1, qty: 1 },
    { label: "61–90", count: 0, qty: 0 },
    { label: "90+", count: 2, qty: 8 },
  ])
})

test("summarizeHolding handles the empty case without dividing by zero", () => {
  const summary = summarizeHolding([])
  expect(summary.lineCount).toBe(0)
  expect(summary.totalQty).toBe(0)
  expect(summary.maxDays).toBe(0)
  expect(summary.avgDays).toBe(0)
  expect(summary.buckets.every((b) => b.count === 0 && b.qty === 0)).toBe(true)
})
