import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import {
  addDays,
  addMonths,
  buildMonthGrid,
  buildYearGrid,
  clampDate,
  clampMonth,
  formatDisplay,
  formatMonthDisplay,
  monthOf,
  nextFocusDate,
  nextFocusMonth,
  todayISO,
} from "./date-field"

describe("todayISO", () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it("returns the LOCAL calendar date, not the UTC one", () => {
    // 23:30 local. toISOString() would report the 26th anywhere west of UTC.
    vi.setSystemTime(new Date(2026, 6, 25, 23, 30))
    expect(todayISO()).toBe("2026-07-25")
  })

  it("zero-pads single-digit months and days", () => {
    vi.setSystemTime(new Date(2026, 0, 5, 12, 0))
    expect(todayISO()).toBe("2026-01-05")
  })
})

describe("formatting", () => {
  it("formats a date for display", () => {
    expect(formatDisplay("2026-07-25")).toBe("25 Jul 2026")
    expect(formatDisplay("2026-01-05")).toBe("5 Jan 2026")
  })

  it("formats a month for display", () => {
    expect(formatMonthDisplay("2026-07")).toBe("Jul 2026")
    expect(formatMonthDisplay("2026-12")).toBe("Dec 2026")
  })

  it("extracts the month from a date", () => {
    expect(monthOf("2026-07-25")).toBe("2026-07")
  })
})

describe("addDays / addMonths", () => {
  it("crosses month and year boundaries in both directions", () => {
    expect(addDays("2026-07-31", 1)).toBe("2026-08-01")
    expect(addDays("2026-01-01", -1)).toBe("2025-12-31")
    expect(addDays("2028-02-28", 1)).toBe("2028-02-29") // leap year
  })

  it("rolls the year in both directions", () => {
    expect(addMonths("2026-12", 1)).toBe("2027-01")
    expect(addMonths("2026-01", -1)).toBe("2025-12")
    expect(addMonths("2026-07", 12)).toBe("2027-07")
    expect(addMonths("2026-07", -12)).toBe("2025-07")
  })
})

describe("buildMonthGrid", () => {
  it("returns 42 Monday-first cells with correct leading and trailing days", () => {
    // 1 Jul 2026 is a Wednesday, so the grid leads with Mon 29 + Tue 30 Jun.
    const cells = buildMonthGrid("2026-07")
    expect(cells).toHaveLength(42)
    expect(cells[0].iso).toBe("2026-06-29")
    expect(cells[0].outside).toBe(true)
    expect(cells[2].iso).toBe("2026-07-01")
    expect(cells[2].outside).toBe(false)
    expect(cells[41].iso).toBe("2026-08-09")
    expect(cells[41].outside).toBe(true)
  })

  it("handles a leap February", () => {
    const cells = buildMonthGrid("2028-02")
    const inMonth = cells.filter((c) => !c.outside)
    expect(inMonth).toHaveLength(29)
    expect(inMonth[28].iso).toBe("2028-02-29")
  })

  it("is unaffected by a DST transition", () => {
    // Northern-hemisphere DST months are the classic place a UTC-based
    // implementation drops or duplicates a day.
    const march = buildMonthGrid("2026-03").filter((c) => !c.outside)
    expect(march).toHaveLength(31)
    expect(march[30].iso).toBe("2026-03-31")
    const october = buildMonthGrid("2026-10").filter((c) => !c.outside)
    expect(october).toHaveLength(31)
    expect(october[30].iso).toBe("2026-10-31")
  })

  it("marks cells outside min/max disabled", () => {
    const cells = buildMonthGrid("2026-07", { max: "2026-07-15" })
    const byIso = (iso: string) => cells.find((c) => c.iso === iso)
    expect(byIso("2026-07-15")?.disabled).toBe(false)
    expect(byIso("2026-07-16")?.disabled).toBe(true)
    const bounded = buildMonthGrid("2026-07", { min: "2026-07-10" })
    expect(bounded.find((c) => c.iso === "2026-07-09")?.disabled).toBe(true)
    expect(bounded.find((c) => c.iso === "2026-07-10")?.disabled).toBe(false)
  })

  it("flags today", () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 6, 25, 9, 0))
    const cells = buildMonthGrid("2026-07")
    expect(cells.filter((c) => c.today).map((c) => c.iso)).toEqual([
      "2026-07-25",
    ])
    vi.useRealTimers()
  })
})

describe("buildYearGrid", () => {
  it("returns the 12 months of the year with labels", () => {
    const cells = buildYearGrid(2026)
    expect(cells).toHaveLength(12)
    expect(cells[0]).toMatchObject({ ym: "2026-01", label: "Jan" })
    expect(cells[11]).toMatchObject({ ym: "2026-12", label: "Dec" })
  })

  it("disables months outside the bounds", () => {
    const cells = buildYearGrid(2026, { max: "2026-07" })
    expect(cells[6].disabled).toBe(false) // Jul
    expect(cells[7].disabled).toBe(true) // Aug
  })
})

describe("clamping", () => {
  it("pulls a date into range", () => {
    expect(clampDate("2026-09-01", { max: "2026-07-25" })).toBe("2026-07-25")
    expect(clampDate("2026-01-01", { min: "2026-07-25" })).toBe("2026-07-25")
    expect(clampDate("2026-07-10", { min: "2026-01-01" })).toBe("2026-07-10")
  })

  it("pulls a month into range", () => {
    expect(clampMonth("2026-09", { max: "2026-07" })).toBe("2026-07")
    expect(clampMonth("2026-01", { min: "2026-07" })).toBe("2026-07")
  })
})

describe("nextFocusDate", () => {
  it("moves by day and by week", () => {
    expect(nextFocusDate("2026-07-15", "ArrowLeft")).toBe("2026-07-14")
    expect(nextFocusDate("2026-07-15", "ArrowRight")).toBe("2026-07-16")
    expect(nextFocusDate("2026-07-15", "ArrowUp")).toBe("2026-07-08")
    expect(nextFocusDate("2026-07-15", "ArrowDown")).toBe("2026-07-22")
  })

  it("crosses month boundaries", () => {
    expect(nextFocusDate("2026-08-01", "ArrowLeft")).toBe("2026-07-31")
    expect(nextFocusDate("2026-07-31", "ArrowDown")).toBe("2026-08-07")
  })

  it("moves to the first and last day of the week", () => {
    // 15 Jul 2026 is a Wednesday; the week runs Mon 13 -> Sun 19.
    expect(nextFocusDate("2026-07-15", "Home")).toBe("2026-07-13")
    expect(nextFocusDate("2026-07-15", "End")).toBe("2026-07-19")
  })

  it("pages by month, and by year with shift", () => {
    expect(nextFocusDate("2026-07-15", "PageUp")).toBe("2026-06-15")
    expect(nextFocusDate("2026-07-15", "PageDown")).toBe("2026-08-15")
    expect(nextFocusDate("2026-07-15", "PageUp", {}, true)).toBe("2025-07-15")
    expect(nextFocusDate("2026-07-15", "PageDown", {}, true)).toBe("2027-07-15")
  })

  it("clamps the day when the target month is shorter", () => {
    expect(nextFocusDate("2026-03-31", "PageUp")).toBe("2026-02-28")
  })

  it("refuses to land on a disabled day", () => {
    // This is what stops a backdated receive from focusing a future date.
    expect(
      nextFocusDate("2026-07-25", "ArrowRight", { max: "2026-07-25" }),
    ).toBe("2026-07-25")
    expect(
      nextFocusDate("2026-07-25", "ArrowDown", { max: "2026-07-25" }),
    ).toBe("2026-07-25")
    expect(
      nextFocusDate("2026-07-10", "ArrowLeft", { min: "2026-07-10" }),
    ).toBe("2026-07-10")
  })
})

describe("nextFocusMonth", () => {
  it("moves across the 3-column month grid", () => {
    expect(nextFocusMonth("2026-07", "ArrowLeft")).toBe("2026-06")
    expect(nextFocusMonth("2026-07", "ArrowRight")).toBe("2026-08")
    expect(nextFocusMonth("2026-07", "ArrowUp")).toBe("2026-04")
    expect(nextFocusMonth("2026-07", "ArrowDown")).toBe("2026-10")
  })

  it("jumps to January, December, and across years", () => {
    expect(nextFocusMonth("2026-07", "Home")).toBe("2026-01")
    expect(nextFocusMonth("2026-07", "End")).toBe("2026-12")
    expect(nextFocusMonth("2026-07", "PageUp")).toBe("2025-07")
    expect(nextFocusMonth("2026-07", "PageDown")).toBe("2027-07")
  })

  it("refuses to land on a disabled month", () => {
    expect(nextFocusMonth("2026-07", "ArrowRight", { max: "2026-07" })).toBe(
      "2026-07",
    )
  })
})
