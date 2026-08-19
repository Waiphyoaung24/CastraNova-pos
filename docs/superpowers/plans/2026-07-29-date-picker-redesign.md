# Date Picker Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all 8 native `<input type="date">` / `type="month"` controls with a hand-rolled, theme-matched `DatePicker` / `MonthPicker` pair so every date surface in the app looks like the rest of the design system.

**Architecture:** Four new frontend files. `lib/date-field.ts` holds every date calculation as pure functions (unit-tested with vitest, no browser). `components/ui/calendar.tsx` renders two presentational grids — `CalendarGrid` (days) and `MonthGrid` (12 months) — that know nothing about popovers. `components/ui/date-picker.tsx` composes those grids inside a Radix Popover and owns open/close and view state. Call sites swap `<Input type="date">` for `<DatePicker>` and `<Input type="month">` for `<MonthPicker>`.

**Tech Stack:** React 19 + TypeScript, Radix Popover (already installed), Tailwind v4 semantic tokens, lucide-react icons, vitest (unit), Playwright (E2E), biome (lint/format).

**Source design:** `docs/superpowers/specs/2026-07-25-date-picker-redesign-design.md` (approved).

## Global Constraints

- **Frontend only.** No backend change, no Alembic migration, no `bun run generate-client`. Never touch `src/client/` or `routeTree.gen.ts`.
- **No new dependencies.** Nothing gets added to `package.json`.
- **Timezone rule:** all date arithmetic uses local `YYYY-MM-DD` strings and `new Date(y, m, d)`. `toISOString()` is never used — it is UTC and reports tomorrow's date for anything keyed in late evening.
- **Wire format is unchanged:** ISO `YYYY-MM-DD` for dates, `YYYY-MM` for months. Only the *display* format changes (`25 Jul 2026` / `Jul 2026`).
- **No typed text entry.** The trigger is a `<button>`, not an `<input>`. Nothing anywhere may call `.fill()` on a date field after this change.
- **Colours are semantic tokens only** — `--primary`, `--accent`, `--muted-foreground`, `--ring`, `--popover`, `--radius`. No raw hex, no invented spacing.
- **Existing validation is untouched.** `isValidReceivedDate()` still guards the Receive submit; `isValidMonth()` still guards the reports.
- **Every E2E run uses `E2E_SKIP_DB_RESET=1`.** The Playwright global setup truncates and reseeds the shared dev database otherwise.
- **Commands** run from `frontend/`: `bun run test:unit` (vitest), `bun run lint` (biome), `bun run build` (tsc + vite), `bunx playwright test <spec>` (E2E).
- **Out of scope:** date ranges, multi-month views, presets, wiring the audit From/To bounds to each other, non-English month names, and the uncommitted `sync-review.tsx` / `EditProductDialog.tsx` / `products.tsx` work in the tree.

---

## File Structure

| File | Responsibility | Status |
|---|---|---|
| `frontend/src/lib/date-field.ts` | All date math, formatting, grid building, keyboard-nav targets. Pure. | Create (Task 1) |
| `frontend/src/lib/date-field.test.ts` | vitest coverage for the above | Create (Task 1) |
| `frontend/src/lib/receive-form.ts` | Loses `todayISO()`, re-exports it from `date-field` | Modify (Task 1) |
| `frontend/src/components/ui/input.tsx` | Exports its class string so the trigger can reuse it | Modify (Task 2) |
| `frontend/src/components/ui/calendar.tsx` | `CalendarGrid` + `MonthGrid`, presentational | Create (Task 2) |
| `frontend/src/components/ui/date-picker.tsx` | `DatePicker` + `MonthPicker`, popover + state | Create (Task 3, extended in Task 6) |
| `frontend/src/routes/_layout/receive.tsx` | 2 call sites | Modify (Task 3) |
| `frontend/tests/receive-date.spec.ts` | Rewritten — `.fill()` no longer works | Modify (Task 3) |
| `frontend/src/routes/_layout/audit.tsx` | 2 call sites | Modify (Task 4) |
| `frontend/tests/audit-date-filter.spec.ts` | New E2E | Create (Task 4) |
| `frontend/src/components/projects/ProjectEditDialog.tsx` | 2 call sites | Modify (Task 5) |
| `frontend/tests/project-date-dialog.spec.ts` | New E2E — popover-inside-dialog | Create (Task 5) |
| `frontend/src/routes/_layout/channel-margin.tsx` | 1 call site | Modify (Task 6) |
| `frontend/src/routes/_layout/override-exceptions.tsx` | 1 call site | Modify (Task 6) |
| `frontend/tests/month-picker.spec.ts` | New E2E | Create (Task 6) |

**Note on component tests:** this repo has no component-test harness — `vitest.config.ts` collects only `src/**/*.test.ts` (pure logic, node env, no jsdom, no Testing Library). Do **not** add one. Pure logic is proven by vitest in Task 1; component behaviour is proven by Playwright.

---

### Task 1: Pure date engine (`date-field.ts`)

**Files:**
- Create: `frontend/src/lib/date-field.ts`
- Create: `frontend/src/lib/date-field.test.ts`
- Modify: `frontend/src/lib/receive-form.ts:34-41` (remove `todayISO`, re-export it)

**Interfaces:**
- Consumes: nothing.
- Produces, for Tasks 2–6:
  ```ts
  type DayCell = { iso: string; day: number; outside: boolean; disabled: boolean; today: boolean }
  type MonthCell = { ym: string; label: string; disabled: boolean; current: boolean }
  type Bounds = { min?: string; max?: string }
  type NavKey = "ArrowLeft" | "ArrowRight" | "ArrowUp" | "ArrowDown" | "Home" | "End" | "PageUp" | "PageDown"
  const WEEKDAYS: string[]                                     // ["Mo",…,"Su"]
  todayISO(): string
  monthOf(iso: string): string
  addDays(iso: string, n: number): string
  addMonths(ym: string, n: number): string
  formatDisplay(iso: string): string
  formatMonthDisplay(ym: string): string
  buildMonthGrid(ym: string, bounds?: Bounds): DayCell[]       // always 42 cells
  buildYearGrid(year: number, bounds?: Bounds): MonthCell[]    // always 12 cells
  clampDate(iso: string, bounds: Bounds): string
  clampMonth(ym: string, bounds: Bounds): string
  nextFocusDate(iso: string, key: NavKey, bounds?: Bounds, shift?: boolean): string
  nextFocusMonth(ym: string, key: NavKey, bounds?: Bounds): string
  ```

`todayISO()` currently lives in `receive-form.ts:37`. A generic date module must not import from a receive-form module, so it moves and `receive-form.ts` re-exports it — `receive.tsx` and `receive-form.test.ts` keep working unchanged.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/date-field.test.ts`:

```ts
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
    expect(nextFocusDate("2026-07-25", "ArrowRight", { max: "2026-07-25" })).toBe(
      "2026-07-25",
    )
    expect(nextFocusDate("2026-07-25", "ArrowDown", { max: "2026-07-25" })).toBe(
      "2026-07-25",
    )
    expect(nextFocusDate("2026-07-10", "ArrowLeft", { min: "2026-07-10" })).toBe(
      "2026-07-10",
    )
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
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `cd frontend && bun run test:unit -- date-field`
Expected: FAIL — `Failed to resolve import "./date-field"`.

- [ ] **Step 3: Write the implementation**

Create `frontend/src/lib/date-field.ts`:

```ts
// Pure date helpers backing the app's DatePicker / MonthPicker. Framework-free
// so every calculation is unit-testable without a browser.
//
// TIMEZONE RULE: everything goes through local `YYYY-MM-DD` strings and
// `new Date(y, m, d)`. `toISOString()` is UTC and is never used here — it would
// report tomorrow's date for a receive keyed in at 11pm.
//
// ISO date and month strings compare correctly with `<` and `>`, so bounds
// checks need no parsing at all.

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
] as const

/** Monday-first weekday headers, matching the grid `buildMonthGrid` returns. */
export const WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"] as const

/** One cell of the 42-cell day grid. */
export type DayCell = {
  iso: string
  day: number
  /** Belongs to the previous or next month — rendered dimmed. */
  outside: boolean
  disabled: boolean
  today: boolean
}

/** One cell of the 12-cell month grid. */
export type MonthCell = {
  ym: string
  label: string
  disabled: boolean
  /** The real-world current month. */
  current: boolean
}

/** Inclusive bounds. ISO `YYYY-MM-DD` for dates, `YYYY-MM` for months. */
export type Bounds = { min?: string; max?: string }

export type NavKey =
  | "ArrowLeft"
  | "ArrowRight"
  | "ArrowUp"
  | "ArrowDown"
  | "Home"
  | "End"
  | "PageUp"
  | "PageDown"

const pad = (n: number) => String(n).padStart(2, "0")

const fromDate = (d: Date) =>
  `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`

const year = (s: string) => Number(s.slice(0, 4))
const month = (s: string) => Number(s.slice(5, 7))
const day = (s: string) => Number(s.slice(8, 10))

/** Today as `YYYY-MM-DD` in the operator's LOCAL timezone. */
export function todayISO(): string {
  return fromDate(new Date())
}

/** `"2026-07-25"` -> `"2026-07"` */
export function monthOf(iso: string): string {
  return iso.slice(0, 7)
}

export function addDays(iso: string, n: number): string {
  return fromDate(new Date(year(iso), month(iso) - 1, day(iso) + n))
}

export function addMonths(ym: string, n: number): string {
  const d = new Date(year(ym), month(ym) - 1 + n, 1)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}`
}

/** Step a full date by whole months, clamping the day into the target month so
 * 31 Mar minus one month lands on 28 Feb rather than overflowing into March. */
function shiftMonth(iso: string, n: number): string {
  const target = new Date(year(iso), month(iso) - 1 + n, 1)
  const lastDay = new Date(
    target.getFullYear(),
    target.getMonth() + 1,
    0,
  ).getDate()
  return `${target.getFullYear()}-${pad(target.getMonth() + 1)}-${pad(
    Math.min(day(iso), lastDay),
  )}`
}

/** `"2026-07-25"` -> `"25 Jul 2026"` */
export function formatDisplay(iso: string): string {
  return `${day(iso)} ${MONTHS[month(iso) - 1]} ${year(iso)}`
}

/** `"2026-07"` -> `"Jul 2026"` */
export function formatMonthDisplay(ym: string): string {
  return `${MONTHS[month(ym) - 1]} ${year(ym)}`
}

function outOfBounds(value: string, { min, max }: Bounds): boolean {
  return Boolean((min && value < min) || (max && value > max))
}

/** Monday-first index of a date's weekday: 0 = Monday, 6 = Sunday. */
function weekdayIndex(iso: string): number {
  return (new Date(year(iso), month(iso) - 1, day(iso)).getDay() + 6) % 7
}

/** 42 cells (6 weeks x 7 days), Monday-first, covering `ym` plus the leading
 * and trailing days needed to fill the grid. Always 42 so the popover never
 * changes height between months. */
export function buildMonthGrid(ym: string, bounds: Bounds = {}): DayCell[] {
  const y = year(ym)
  const m = month(ym)
  const lead = (new Date(y, m - 1, 1).getDay() + 6) % 7
  const today = todayISO()
  return Array.from({ length: 42 }, (_, i) => {
    const date = new Date(y, m - 1, 1 - lead + i)
    const iso = fromDate(date)
    return {
      iso,
      day: date.getDate(),
      outside: monthOf(iso) !== ym,
      disabled: outOfBounds(iso, bounds),
      today: iso === today,
    }
  })
}

/** The 12 months of `year`. Bounds are `YYYY-MM`. */
export function buildYearGrid(y: number, bounds: Bounds = {}): MonthCell[] {
  const current = monthOf(todayISO())
  return MONTHS.map((label, i) => {
    const ym = `${y}-${pad(i + 1)}`
    return {
      ym,
      label,
      disabled: outOfBounds(ym, bounds),
      current: ym === current,
    }
  })
}

export function clampDate(iso: string, { min, max }: Bounds): string {
  if (min && iso < min) return min
  if (max && iso > max) return max
  return iso
}

export function clampMonth(ym: string, { min, max }: Bounds): string {
  if (min && ym < min) return min
  if (max && ym > max) return max
  return ym
}

/** Where roving focus moves for `key`. Returns `iso` unchanged when the move
 * would land outside the bounds — arrow keys skip disabled days rather than
 * landing on them, which is what stops a backdated receive from ever focusing
 * a future date. */
export function nextFocusDate(
  iso: string,
  key: NavKey,
  bounds: Bounds = {},
  shift = false,
): string {
  let next = iso
  switch (key) {
    case "ArrowLeft":
      next = addDays(iso, -1)
      break
    case "ArrowRight":
      next = addDays(iso, 1)
      break
    case "ArrowUp":
      next = addDays(iso, -7)
      break
    case "ArrowDown":
      next = addDays(iso, 7)
      break
    case "Home":
      next = addDays(iso, -weekdayIndex(iso))
      break
    case "End":
      next = addDays(iso, 6 - weekdayIndex(iso))
      break
    case "PageUp":
      next = shiftMonth(iso, shift ? -12 : -1)
      break
    case "PageDown":
      next = shiftMonth(iso, shift ? 12 : 1)
      break
  }
  return outOfBounds(next, bounds) ? iso : next
}

/** The month-grid equivalent. The grid is 3 columns wide, so up/down step 3. */
export function nextFocusMonth(
  ym: string,
  key: NavKey,
  bounds: Bounds = {},
): string {
  let next = ym
  switch (key) {
    case "ArrowLeft":
      next = addMonths(ym, -1)
      break
    case "ArrowRight":
      next = addMonths(ym, 1)
      break
    case "ArrowUp":
      next = addMonths(ym, -3)
      break
    case "ArrowDown":
      next = addMonths(ym, 3)
      break
    case "Home":
      next = `${ym.slice(0, 4)}-01`
      break
    case "End":
      next = `${ym.slice(0, 4)}-12`
      break
    case "PageUp":
      next = addMonths(ym, -12)
      break
    case "PageDown":
      next = addMonths(ym, 12)
      break
  }
  return outOfBounds(next, bounds) ? ym : next
}
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `cd frontend && bun run test:unit -- date-field`
Expected: PASS, all describe blocks green.

- [ ] **Step 5: Move `todayISO` out of `receive-form.ts`**

In `frontend/src/lib/receive-form.ts`, delete the whole `todayISO` block (the comment at lines 34-36 and the function at 37-41) and the `// Receive date` divider stays. Add the import at the top of the file, directly under the existing `import type {...} from "../client/types.gen"` block:

```ts
import { todayISO } from "./date-field"
```

Then, where the function used to be, put the re-export so existing importers keep working:

```ts
// ---------------------------------------------------------------------------
// Receive date
// ---------------------------------------------------------------------------

// `todayISO` lives in `date-field.ts` now — a generic date module must not
// depend on a receive-form module. Re-exported so `receive.tsx` and
// `receive-form.test.ts` keep importing it from here.
export { todayISO }
```

`isValidReceivedDate` below it already calls `todayISO()` and now resolves it through the import — no change needed there.

- [ ] **Step 6: Run the full unit suite and the linter**

Run: `cd frontend && bun run test:unit && bun run lint && bun run build`
Expected: vitest all-pass (including the untouched `receive-form.test.ts` `todayISO` cases), biome clean, build succeeds.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/date-field.ts frontend/src/lib/date-field.test.ts frontend/src/lib/receive-form.ts
git commit -m "feat(ui): pure date engine behind the new date pickers"
```

---

### Task 2: Field chrome + presentational grids (`calendar.tsx`)

**Files:**
- Modify: `frontend/src/components/ui/input.tsx:5-21`
- Create: `frontend/src/components/ui/calendar.tsx`

**Interfaces:**
- Consumes from Task 1: `WEEKDAYS`, `Bounds`, `NavKey`, `buildMonthGrid`, `buildYearGrid`, `formatDisplay`, `formatMonthDisplay`, `nextFocusDate`, `nextFocusMonth`.
- Produces, for Tasks 3 and 6:
  ```ts
  // components/ui/input.tsx
  const inputClassName: string

  // components/ui/calendar.tsx
  function CalendarGrid(props: {
    month: string; selected: string; focused: string; bounds?: Bounds
    onSelect: (iso: string) => void; onFocusedChange: (iso: string) => void
  }): JSX.Element

  function MonthGrid(props: {
    year: number; selected: string; focused: string; bounds?: Bounds
    onSelect: (ym: string) => void; onFocusedChange: (ym: string) => void
  }): JSX.Element
  ```

These two grids are pure presentation — they own no open/close state and know nothing about popovers. They *do* own roving focus (an effect that focuses whichever cell matches `focused`) and keyboard handling, delegating the actual target calculation to Task 1's pure functions.

This task has no behavioural test of its own — nothing consumes the grids yet. It is gated on typecheck and lint; Task 3 supplies the first E2E proof.

- [ ] **Step 1: Export the field class string from `input.tsx`**

Replace the whole body of `frontend/src/components/ui/input.tsx` with:

```tsx
import * as React from "react"

import { cn } from "@/lib/utils"

/** The full field chrome — border, height, radius, focus ring, invalid state.
 * Exported so controls that are not `<input>` but must be visually identical
 * (the DatePicker trigger) share one source of truth instead of drifting. */
export const inputClassName = cn(
  "file:text-foreground placeholder:text-muted-foreground selection:bg-primary selection:text-primary-foreground dark:bg-input/30 border-input h-9 w-full min-w-0 rounded-md border bg-transparent px-3 py-1 text-base shadow-xs transition-[color,box-shadow] outline-none file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm",
  "focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]",
  "aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive",
)

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(inputClassName, className)}
      {...props}
    />
  )
}

export { Input }
```

Behaviour is unchanged — the same three strings, merged the same way, just hoisted so they can be shared.

- [ ] **Step 2: Write the grids**

Create `frontend/src/components/ui/calendar.tsx`:

```tsx
import { type KeyboardEvent, useEffect, useRef } from "react"

import {
  type Bounds,
  buildMonthGrid,
  buildYearGrid,
  formatDisplay,
  formatMonthDisplay,
  type NavKey,
  nextFocusDate,
  nextFocusMonth,
  WEEKDAYS,
} from "@/lib/date-field"
import { cn } from "@/lib/utils"

// Presentational calendar grids. They own roving focus and key handling but no
// open/close state — `date-picker.tsx` composes them into a popover. Keeping
// the split means the grid can be restyled without touching trigger behaviour.

const NAV_KEYS = new Set<string>([
  "ArrowLeft",
  "ArrowRight",
  "ArrowUp",
  "ArrowDown",
  "Home",
  "End",
  "PageUp",
  "PageDown",
])

// size-11 on touch, size-9 from `sm` up — WCAG target size where it matters.
const CELL =
  "inline-flex items-center justify-center rounded-md text-sm outline-none " +
  "transition-colors hover:bg-accent hover:text-accent-foreground " +
  "focus-visible:ring-ring/50 focus-visible:ring-[3px] " +
  "disabled:pointer-events-none disabled:text-muted-foreground/40"

/** Focus whichever cell the parent says is focused, whenever that changes.
 * The ref is attached conditionally to that one cell, so it always points at
 * the right element by the time the effect runs. */
function useRovingFocus(focused: string) {
  const ref = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    ref.current?.focus()
  }, [focused])
  return ref
}

type CalendarGridProps = {
  /** The visible month, `YYYY-MM`. */
  month: string
  /** The selected date, `YYYY-MM-DD`, or `""` when the field is empty. */
  selected: string
  /** The date holding `tabIndex={0}`. */
  focused: string
  bounds?: Bounds
  onSelect: (iso: string) => void
  onFocusedChange: (iso: string) => void
}

export function CalendarGrid({
  month,
  selected,
  focused,
  bounds = {},
  onSelect,
  onFocusedChange,
}: CalendarGridProps) {
  const cells = buildMonthGrid(month, bounds)
  const weeks = Array.from({ length: 6 }, (_, w) => cells.slice(w * 7, w * 7 + 7))
  const focusRef = useRovingFocus(focused)

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!NAV_KEYS.has(event.key)) return
    event.preventDefault()
    onFocusedChange(
      nextFocusDate(focused, event.key as NavKey, bounds, event.shiftKey),
    )
  }

  return (
    // biome-ignore lint/a11y/useSemanticElements: APG date-picker-dialog uses
    // an explicit grid/row/gridcell structure with roving tabindex.
    <div role="grid" aria-label="Calendar" onKeyDown={handleKeyDown}>
      <div role="row" className="flex">
        {WEEKDAYS.map((weekday) => (
          <div
            key={weekday}
            role="columnheader"
            className="inline-flex size-11 items-center justify-center text-xs text-muted-foreground sm:size-9"
          >
            {weekday}
          </div>
        ))}
      </div>
      {weeks.map((week) => (
        <div key={week[0].iso} role="row" className="flex">
          {week.map((cell) => (
            <button
              key={cell.iso}
              ref={cell.iso === focused ? focusRef : undefined}
              type="button"
              role="gridcell"
              aria-label={formatDisplay(cell.iso)}
              aria-selected={cell.iso === selected}
              aria-disabled={cell.disabled}
              disabled={cell.disabled}
              tabIndex={cell.iso === focused ? 0 : -1}
              onClick={() => onSelect(cell.iso)}
              className={cn(
                CELL,
                "size-11 sm:size-9",
                cell.outside && "text-muted-foreground/50",
                cell.today && cell.iso !== selected && "ring-1 ring-ring",
                cell.iso === selected &&
                  "bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground",
              )}
            >
              {cell.day}
            </button>
          ))}
        </div>
      ))}
    </div>
  )
}

type MonthGridProps = {
  year: number
  /** The selected month, `YYYY-MM`, or `""`. */
  selected: string
  /** The month holding `tabIndex={0}`, `YYYY-MM`. */
  focused: string
  bounds?: Bounds
  onSelect: (ym: string) => void
  onFocusedChange: (ym: string) => void
}

export function MonthGrid({
  year,
  selected,
  focused,
  bounds = {},
  onSelect,
  onFocusedChange,
}: MonthGridProps) {
  const cells = buildYearGrid(year, bounds)
  const rows = Array.from({ length: 4 }, (_, r) => cells.slice(r * 3, r * 3 + 3))
  const focusRef = useRovingFocus(focused)

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!NAV_KEYS.has(event.key)) return
    event.preventDefault()
    onFocusedChange(nextFocusMonth(focused, event.key as NavKey, bounds))
  }

  return (
    // biome-ignore lint/a11y/useSemanticElements: see CalendarGrid.
    <div
      role="grid"
      aria-label="Months"
      onKeyDown={handleKeyDown}
      className="grid w-63 grid-cols-3 gap-1"
    >
      {rows.map((row) => (
        // `contents` keeps the CSS grid flat while preserving the row role.
        <div key={row[0].ym} role="row" className="contents">
          {row.map((cell) => (
            <button
              key={cell.ym}
              ref={cell.ym === focused ? focusRef : undefined}
              type="button"
              role="gridcell"
              aria-label={formatMonthDisplay(cell.ym)}
              aria-selected={cell.ym === selected}
              aria-disabled={cell.disabled}
              disabled={cell.disabled}
              tabIndex={cell.ym === focused ? 0 : -1}
              onClick={() => onSelect(cell.ym)}
              className={cn(
                CELL,
                "h-11 w-full sm:h-9",
                cell.current && cell.ym !== selected && "ring-1 ring-ring",
                cell.ym === selected &&
                  "bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground",
              )}
            >
              {cell.label}
            </button>
          ))}
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 3: Typecheck and lint**

Run: `cd frontend && bun run lint && bun run build`
Expected: biome clean, `tsc` clean, vite build succeeds.

If biome does not actually flag `lint/a11y/useSemanticElements` on these `role` attributes, it will instead flag the unused suppression comments — delete the two `biome-ignore` lines in that case and re-run.

- [ ] **Step 4: Confirm nothing regressed**

Run: `cd frontend && bun run test:unit`
Expected: PASS. (`input.tsx` changed; nothing else consumes the grids yet.)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ui/input.tsx frontend/src/components/ui/calendar.tsx
git commit -m "feat(ui): shared field chrome and presentational calendar grids"
```

---

### Task 3: `DatePicker` + both Receive tabs

**Files:**
- Create: `frontend/src/components/ui/date-picker.tsx`
- Modify: `frontend/src/routes/_layout/receive.tsx:280-289` and `:607-616`
- Modify: `frontend/tests/receive-date.spec.ts` (full rewrite)

**Interfaces:**
- Consumes from Task 1: `addMonths`, `clampDate`, `clampMonth`, `formatDisplay`, `formatMonthDisplay`, `monthOf`, `todayISO`. From Task 2: `inputClassName`, `CalendarGrid`, `MonthGrid`.
- Produces, for Tasks 4–6:
  ```ts
  function DatePicker(props: {
    id?: string
    labelledBy?: string              // id of the visible <Label>
    value: string                    // "" when unset
    onChange: (iso: string) => void  // emits the ISO string, not an event
    min?: string
    max?: string
    disabled?: boolean
    required?: boolean               // hides the Clear button
    placeholder?: string             // default "Pick a date"
    className?: string
  }): JSX.Element
  ```

**Accessible name:** a `<button>` takes its name from its own contents, so a bare `<Label htmlFor>` is ignored by the name computation. Every call site therefore gives its `<Label>` an `id` and passes it as `labelledBy`; the trigger then renders `aria-labelledby="<labelId> <triggerId>"`, naming itself "Receive date 25 Jul 2026". This is what makes `page.getByLabel("Receive date")` resolve in Playwright as well.
  `MonthPicker` is added to the same file in Task 6.

- [ ] **Step 1: Write the picker**

Create `frontend/src/components/ui/date-picker.tsx`:

```tsx
import { CalendarIcon, ChevronLeft, ChevronRight } from "lucide-react"
import { type ReactNode, useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { CalendarGrid, MonthGrid } from "@/components/ui/calendar"
import { inputClassName } from "@/components/ui/input"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import {
  addMonths,
  clampDate,
  clampMonth,
  formatDisplay,
  formatMonthDisplay,
  monthOf,
  todayISO,
} from "@/lib/date-field"
import { cn } from "@/lib/utils"

// Click-to-open date and month pickers. There is deliberately no typed text
// entry: parsing free-form dates forces a dd/mm-vs-mm/dd and a two-digit-year
// assumption, both of which are silent-wrong-date hazards on a screen that
// backdates inventory receipts. Radix Popover supplies focus containment,
// Escape, outside-click dismissal and focus return to the trigger.

type FieldTriggerProps = {
  id?: string
  /** id of the visible `<Label>`. The trigger names itself from that label AND
   * its own text, so a screen reader announces "Receive date 25 Jul 2026"
   * rather than a bare date. A `<button>` takes its accessible name from its
   * contents, so a plain `<Label htmlFor>` would otherwise be ignored. */
  labelledBy?: string
  /** Rendered field text — either the formatted value or the placeholder. */
  label: string
  isPlaceholder: boolean
  disabled?: boolean
  required?: boolean
  className?: string
  onOpen: () => void
}

/** The trigger reuses `inputClassName` so it is pixel-identical to every other
 * field. Radix adds `aria-haspopup="dialog"` and `aria-expanded` itself. */
function FieldTrigger({
  id,
  labelledBy,
  label,
  isPlaceholder,
  disabled,
  required,
  className,
  onOpen,
}: FieldTriggerProps) {
  return (
    <PopoverTrigger asChild>
      <button
        id={id}
        type="button"
        disabled={disabled}
        aria-required={required || undefined}
        aria-labelledby={labelledBy && id ? `${labelledBy} ${id}` : undefined}
        onKeyDown={(event) => {
          // APG: Down (and Alt+Down) opens the dialog. Enter and Space already
          // activate the button natively.
          if (event.key === "ArrowDown") {
            event.preventDefault()
            onOpen()
          }
        }}
        className={cn(
          inputClassName,
          "flex items-center justify-between gap-2 text-left font-normal",
          className,
        )}
      >
        <span className={cn(isPlaceholder && "text-muted-foreground")}>
          {label}
        </span>
        <CalendarIcon aria-hidden="true" className="size-4 shrink-0 opacity-60" />
      </button>
    </PopoverTrigger>
  )
}

type StepperProps = {
  onPrev: () => void
  prevLabel: string
  onNext: () => void
  nextLabel: string
  children: ReactNode
}

/** `‹ caption ›` header shared by the day view, the year view and MonthPicker. */
function Stepper({ onPrev, prevLabel, onNext, nextLabel, children }: StepperProps) {
  return (
    <div className="flex items-center justify-between pb-2">
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label={prevLabel}
        onClick={onPrev}
      >
        <ChevronLeft className="size-4" />
      </Button>
      {children}
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label={nextLabel}
        onClick={onNext}
      >
        <ChevronRight className="size-4" />
      </Button>
    </div>
  )
}

export type DatePickerProps = {
  id?: string
  /** id of the visible `<Label>` — see `FieldTriggerProps.labelledBy`. */
  labelledBy?: string
  /** ISO `YYYY-MM-DD`, or `""` when unset. */
  value: string
  /** Receives the ISO string — not a change event. `""` when cleared. */
  onChange: (iso: string) => void
  min?: string
  max?: string
  disabled?: boolean
  /** Hides the Clear button. */
  required?: boolean
  placeholder?: string
  className?: string
}

export function DatePicker({
  id,
  labelledBy,
  value,
  onChange,
  min,
  max,
  disabled,
  required,
  placeholder = "Pick a date",
  className,
}: DatePickerProps) {
  const bounds = { min, max }
  const monthBounds = {
    min: min ? monthOf(min) : undefined,
    max: max ? monthOf(max) : undefined,
  }

  const [open, setOpen] = useState(false)
  const [view, setView] = useState<"days" | "months">("days")
  const [visibleMonth, setVisibleMonth] = useState(() =>
    value ? monthOf(value) : clampMonth(monthOf(todayISO()), monthBounds),
  )
  const [focused, setFocused] = useState(
    () => value || clampDate(todayISO(), bounds),
  )

  // Every opening starts from the current value (or today, clamped into range)
  // so a half-finished browse from last time is never resurrected.
  useEffect(() => {
    if (!open) return
    const start = value || clampDate(todayISO(), { min, max })
    setFocused(start)
    setVisibleMonth(monthOf(start))
    setView("days")
  }, [open, value, min, max])

  function moveFocus(iso: string) {
    setFocused(iso)
    setVisibleMonth(monthOf(iso))
  }

  function select(iso: string) {
    onChange(iso)
    setOpen(false)
  }

  const today = todayISO()
  const todayOutOfRange = clampDate(today, bounds) !== today

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <FieldTrigger
        id={id}
        labelledBy={labelledBy}
        label={value ? formatDisplay(value) : placeholder}
        isPlaceholder={!value}
        disabled={disabled}
        required={required}
        className={className}
        onOpen={() => setOpen(true)}
      />
      <PopoverContent
        align="start"
        aria-label="Choose date"
        className="w-auto rounded-lg p-3"
        onOpenAutoFocus={(event) => {
          // The grid focuses its own roving cell; let it, so the popover opens
          // on the selected day rather than on the container.
          event.preventDefault()
        }}
      >
        {view === "days" ? (
          <>
            <Stepper
              prevLabel="Previous month"
              onPrev={() => setVisibleMonth(addMonths(visibleMonth, -1))}
              nextLabel="Next month"
              onNext={() => setVisibleMonth(addMonths(visibleMonth, 1))}
            >
              <button
                type="button"
                aria-live="polite"
                onClick={() => setView("months")}
                className="rounded-md px-2 py-1 text-sm font-medium hover:bg-accent hover:text-accent-foreground"
              >
                {formatMonthDisplay(visibleMonth)}
              </button>
            </Stepper>
            <CalendarGrid
              month={visibleMonth}
              selected={value}
              focused={focused}
              bounds={bounds}
              onSelect={select}
              onFocusedChange={moveFocus}
            />
            <div className="mt-2 flex items-center justify-between border-t pt-2">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={todayOutOfRange}
                onClick={() => select(today)}
              >
                Today
              </Button>
              {!required && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    onChange("")
                    setOpen(false)
                  }}
                >
                  Clear
                </Button>
              )}
            </div>
          </>
        ) : (
          <>
            <Stepper
              prevLabel="Previous year"
              onPrev={() => setVisibleMonth(addMonths(visibleMonth, -12))}
              nextLabel="Next year"
              onNext={() => setVisibleMonth(addMonths(visibleMonth, 12))}
            >
              <span aria-live="polite" className="text-sm font-medium">
                {visibleMonth.slice(0, 4)}
              </span>
            </Stepper>
            <MonthGrid
              year={Number(visibleMonth.slice(0, 4))}
              selected={value ? monthOf(value) : ""}
              focused={visibleMonth}
              bounds={monthBounds}
              onSelect={(ym) => {
                setVisibleMonth(ym)
                setFocused(clampDate(`${ym}-01`, bounds))
                setView("days")
              }}
              onFocusedChange={setVisibleMonth}
            />
          </>
        )}
      </PopoverContent>
    </Popover>
  )
}
```

- [ ] **Step 2: Swap both Receive call sites**

In `frontend/src/routes/_layout/receive.tsx`, add the import alongside the other UI imports (keep them alphabetical — it goes just before the `Input` import on line 24):

```tsx
import { DatePicker } from "@/components/ui/date-picker"
```

Replace the serialized-tab block at lines 272-290 — the `<Label>` gains an `id` so the trigger can name itself from it:

```tsx
        <div className="flex flex-col gap-2">
          <Label id="receive-date-label" htmlFor="receive-date">
            Receive date
            <span aria-hidden="true" className="text-destructive">
              {" "}
              *
            </span>
          </Label>
          <DatePicker
            id="receive-date"
            labelledBy="receive-date-label"
            className="h-11"
            max={todayISO()}
            required
            disabled={mutation.isPending}
            value={receivedDate}
            onChange={setReceivedDate}
          />
        </div>
```

Replace the quantity-tab block at lines 599-617:

```tsx
        <div className="flex flex-col gap-2">
          <Label
            id={`${fieldId}-received-date-label`}
            htmlFor={`${fieldId}-received-date`}
          >
            Receive date
            <span aria-hidden="true" className="text-destructive">
              {" "}
              *
            </span>
          </Label>
          <DatePicker
            id={`${fieldId}-received-date`}
            labelledBy={`${fieldId}-received-date-label`}
            className="h-11"
            max={todayISO()}
            required
            disabled={mutation.isPending}
            value={draft.receivedDate}
            onChange={(iso) => patch("receivedDate", iso)}
          />
        </div>
```

The asterisk span is `aria-hidden`, so it stays out of the computed name. `Input` stays imported — `receive.tsx` has seven other `<Input>` uses.

- [ ] **Step 3: Rewrite the E2E spec**

Replace the whole of `frontend/tests/receive-date.spec.ts`:

```ts
import { expect, type Page, test } from "@playwright/test"

// Browser E2E for the Receive date picker (designs 2026-07-25 receive-date-picker
// and 2026-07-25 date-picker-redesign). The picker exists because holding period
// is computed from received_at, so a delivery keyed in late used to report the
// wrong age. Since the redesign the control is a button + popover grid, never an
// `<input type="date">` — no spec may call `.fill()` on a date field.
// Runs authed as the seeded superuser via storageState (global.setup).

/** Local date as YYYY-MM-DD — must mirror todayISO() in lib/date-field.ts.
 * Deliberately not toISOString(), which is UTC and would flake either side of
 * UTC midnight. */
function localISO(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

/** Mirrors formatDisplay() in lib/date-field.ts: "2026-07-25" -> "25 Jul 2026". */
function display(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number)
  return `${d} ${MONTHS[m - 1]} ${y}`
}

function daysAgo(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return localISO(d)
}

const today = localISO(new Date())

/** Open the picker and click the given day, paging back a month first when the
 * target is not in the month the picker opens on. */
async function pickDate(page: Page, trigger: ReturnType<Page["getByLabel"]>, iso: string) {
  await trigger.click()
  const dialog = page.getByRole("dialog", { name: "Choose date" })
  if (iso.slice(0, 7) !== today.slice(0, 7)) {
    await dialog.getByRole("button", { name: "Previous month" }).click()
  }
  await dialog.getByRole("gridcell", { name: display(iso), exact: true }).click()
}

test("both Receive tabs default the date to today", async ({ page }) => {
  await page.goto("/receive")

  // Serialized is the default tab; its trigger carries a static id.
  await expect(page.locator("#receive-date")).toHaveText(display(today))

  await page.getByRole("tab", { name: "Quantity" }).click()
  const quantityPanel = page.getByRole("tabpanel")
  await expect(quantityPanel.getByLabel("Receive date")).toHaveText(
    display(today),
  )
})

test("a future date cannot be selected on either tab", async ({ page }) => {
  const tomorrow = localISO(new Date(Date.now() + 24 * 60 * 60 * 1000))

  await page.goto("/receive")

  // The 42-cell grid always renders the day after the last of the month, so
  // tomorrow is present regardless of where in the month today falls.
  await page.locator("#receive-date").click()
  const serializedDialog = page.getByRole("dialog", { name: "Choose date" })
  await expect(
    serializedDialog.getByRole("gridcell", { name: display(tomorrow), exact: true }),
  ).toBeDisabled()
  await page.keyboard.press("Escape")

  await page.getByRole("tab", { name: "Quantity" }).click()
  await page.getByRole("tabpanel").getByLabel("Receive date").click()
  const quantityDialog = page.getByRole("dialog", { name: "Choose date" })
  await expect(
    quantityDialog.getByRole("gridcell", { name: display(tomorrow), exact: true }),
  ).toBeDisabled()
})

test("a date can be reached and selected with the keyboard alone", async ({
  page,
}) => {
  await page.goto("/receive")

  const trigger = page.locator("#receive-date")
  await trigger.focus()
  await page.keyboard.press("Enter")

  // The popover opens focused on today. Three left arrows walk back three days.
  await page.keyboard.press("ArrowLeft")
  await page.keyboard.press("ArrowLeft")
  await page.keyboard.press("ArrowLeft")
  // Right arrow past the max is refused, so this pair nets a single day back.
  await page.keyboard.press("ArrowRight")
  await page.keyboard.press("Enter")

  await expect(trigger).toHaveText(display(daysAgo(2)))
})

test("arrow keys refuse to move past today", async ({ page }) => {
  await page.goto("/receive")

  const trigger = page.locator("#receive-date")
  await trigger.focus()
  await page.keyboard.press("Enter")
  // Focus starts on today, which is also `max` — every forward move is a no-op.
  await page.keyboard.press("ArrowRight")
  await page.keyboard.press("ArrowDown")
  await page.keyboard.press("Enter")

  await expect(trigger).toHaveText(display(today))
})

test("a backdated Quantity receive mints a batch_no with the backdated prefix", async ({
  page,
}) => {
  const backdated = daysAgo(10)
  const expectedPrefix = backdated.replaceAll("-", "")

  await page.goto("/receive")
  await page.getByRole("tab", { name: "Quantity" }).click()
  const panel = page.getByRole("tabpanel")

  // Pick the first available QUANTITY product and any supplier via the
  // EntityCombobox triggers (options are portalled to the body).
  await panel.getByRole("combobox", { name: "Product" }).click()
  await page.getByRole("option").first().click()
  await panel.getByRole("combobox", { name: "Supplier" }).click()
  await page.getByRole("option").first().click()

  await panel.getByLabel("Received qty").fill("4")
  await panel.getByLabel("Unit cost (THB)").fill("7.50")
  await pickDate(page, panel.getByLabel("Receive date"), backdated)

  await panel.getByRole("button", { name: "Receive" }).click()

  // The success toast carries the minted batch number; its date prefix must be
  // the BACKDATED day, not today.
  await expect(
    page.getByText(new RegExp(`Received batch ${expectedPrefix}-`)),
  ).toBeVisible()
})
```

- [ ] **Step 4: Typecheck, lint, unit**

Run: `cd frontend && bun run lint && bun run build && bun run test:unit`
Expected: all clean.

- [ ] **Step 5: Run the E2E spec**

Run: `cd frontend && E2E_SKIP_DB_RESET=1 bunx playwright test tests/receive-date.spec.ts`
Expected: 5 passed.

If the keyboard tests fail because focus did not land in the grid, check that `onOpenAutoFocus` is preventing default and that `useRovingFocus` is attached to the cell whose `iso === focused`. Do not paper over it with `waitForTimeout`.

- [ ] **Step 6: Run the neighbouring Receive specs for regressions**

Run: `cd frontend && E2E_SKIP_DB_RESET=1 bunx playwright test tests/receive.spec.ts tests/receive-form.spec.ts`
Expected: all pass, unchanged.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/ui/date-picker.tsx frontend/src/routes/_layout/receive.tsx frontend/tests/receive-date.spec.ts
git commit -m "feat(receive): themed DatePicker on both Receive tabs"
```

---

### Task 4: Audit From / To filters

**Files:**
- Modify: `frontend/src/routes/_layout/audit.tsx:19` (drop the now-unused `Input` import), `:190-215`
- Create: `frontend/tests/audit-date-filter.spec.ts`

**Interfaces:**
- Consumes from Task 3: `DatePicker`.
- Produces: nothing for later tasks.

These are the app's only *optional* date fields, so they are the ones that exercise the Clear button. `resetPage()` must still fire on change — the existing `onChange` body is preserved, only its argument changes from `e.target.value` to the ISO string.

- [ ] **Step 1: Swap both filters**

In `frontend/src/routes/_layout/audit.tsx`, delete line 19 (`import { Input } from "@/components/ui/input"`) — both of the file's `<Input>` uses are the two date filters being replaced. Add in its place:

```tsx
import { DatePicker } from "@/components/ui/date-picker"
```

(Keep the import block sorted; `@/components/ui/date-picker` sorts before `@/components/ui/label`.)

Replace lines 190-215:

```tsx
        <div className="flex flex-col gap-1.5">
          <Label id={`${fromId}-label`} htmlFor={fromId}>
            From
          </Label>
          <DatePicker
            id={fromId}
            labelledBy={`${fromId}-label`}
            value={filter.fromDate}
            onChange={(iso) => {
              setFilter((f) => ({ ...f, fromDate: iso }))
              resetPage()
            }}
            placeholder="Any date"
            className="w-full sm:w-44"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label id={`${toId}-label`} htmlFor={toId}>
            To
          </Label>
          <DatePicker
            id={toId}
            labelledBy={`${toId}-label`}
            value={filter.toDate}
            onChange={(iso) => {
              setFilter((f) => ({ ...f, toDate: iso }))
              resetPage()
            }}
            placeholder="Any date"
            className="w-full sm:w-44"
          />
        </div>
```

Neither gets `required`, so both show Clear. Deliberately no `min`/`max` wiring between them — that is listed out of scope in the design.

- [ ] **Step 2: Write the E2E spec**

Create `frontend/tests/audit-date-filter.spec.ts`:

```ts
import { expect, test } from "@playwright/test"

// The audit ledger's From/To filters are the app's only OPTIONAL date fields,
// so they are where the Clear affordance gets proven. Runs authed as the seeded
// superuser via storageState (global.setup).

function localISO(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

function display(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number)
  return `${d} ${MONTHS[m - 1]} ${y}`
}

const today = localISO(new Date())

test("From and To are set from the grid and cleared again", async ({ page }) => {
  await page.goto("/audit")

  const from = page.getByLabel("From")
  const to = page.getByLabel("To")

  // Unset fields show the placeholder, not a date.
  await expect(from).toHaveText("Any date")

  // Today's cell is reachable in both pickers without paging.
  await from.click()
  await page
    .getByRole("dialog", { name: "Choose date" })
    .getByRole("gridcell", { name: display(today), exact: true })
    .click()
  await expect(from).toHaveText(display(today))

  await to.click()
  await page
    .getByRole("dialog", { name: "Choose date" })
    .getByRole("button", { name: "Today" })
    .click()
  await expect(to).toHaveText(display(today))

  // The ledger keeps rendering under the filter rather than erroring out.
  await expect(page.getByRole("heading", { name: "Audit ledger" })).toBeVisible()

  // Clear is offered because these fields are optional.
  await from.click()
  await page
    .getByRole("dialog", { name: "Choose date" })
    .getByRole("button", { name: "Clear" })
    .click()
  await expect(from).toHaveText("Any date")
})

test("Escape closes the picker and returns focus to the trigger", async ({
  page,
}) => {
  await page.goto("/audit")

  const from = page.getByLabel("From")
  await from.click()
  await expect(page.getByRole("dialog", { name: "Choose date" })).toBeVisible()

  await page.keyboard.press("Escape")
  await expect(page.getByRole("dialog", { name: "Choose date" })).toBeHidden()
  await expect(from).toBeFocused()
})
```

- [ ] **Step 3: Typecheck and lint**

Run: `cd frontend && bun run lint && bun run build`
Expected: clean — in particular no "unused import" error for `Input` in `audit.tsx`.

- [ ] **Step 4: Run the E2E specs**

Run: `cd frontend && E2E_SKIP_DB_RESET=1 bunx playwright test tests/audit-date-filter.spec.ts tests/audit.spec.ts`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/_layout/audit.tsx frontend/tests/audit-date-filter.spec.ts
git commit -m "feat(audit): themed DatePicker on the From/To filters"
```

---

### Task 5: Project edit dialog (popover inside a dialog)

**Files:**
- Modify: `frontend/src/components/projects/ProjectEditDialog.tsx:145-164`
- Create: `frontend/tests/project-date-dialog.spec.ts`

**Interfaces:**
- Consumes from Task 3: `DatePicker`.
- Produces: nothing for later tasks.

This is the design's named risk: a Radix Popover nested inside a Radix Dialog. Focus return and stacking are the usual failure mode for that combination, so it gets an explicit test rather than an assumption.

- [ ] **Step 1: Swap both fields**

In `frontend/src/components/projects/ProjectEditDialog.tsx`, add next to the existing UI imports (before the `Input` import on line 19):

```tsx
import { DatePicker } from "@/components/ui/date-picker"
```

`Input` stays — the file has three other `<Input>` uses.

Replace lines 145-164:

```tsx
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label id={`${startId}-label`} htmlFor={startId}>
                Start date
              </Label>
              <DatePicker
                id={startId}
                labelledBy={`${startId}-label`}
                value={draft.startDate}
                onChange={(iso) => patch({ startDate: iso })}
                placeholder="No start date"
              />
            </div>
            <div className="space-y-2">
              <Label id={`${endId}-label`} htmlFor={endId}>
                End date
              </Label>
              <DatePicker
                id={endId}
                labelledBy={`${endId}-label`}
                value={draft.endDate}
                onChange={(iso) => patch({ endDate: iso })}
                placeholder="No end date"
              />
            </div>
          </div>
```

- [ ] **Step 2: Write the E2E spec**

Create `frontend/tests/project-date-dialog.spec.ts`:

```ts
import { expect, test } from "@playwright/test"

// A Radix Popover nested inside a Radix Dialog is the classic place focus return
// and stacking break, and the project edit dialog is the only screen where the
// date picker sits inside one. Runs authed as the seeded superuser.

function localISO(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

function display(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number)
  return `${d} ${MONTHS[m - 1]} ${y}`
}

const today = localISO(new Date())

/** Create a customer and a project, then open that project's edit dialog.
 * Mirrors tests/project-edit-flow.spec.ts — the seeded database is not
 * guaranteed to contain a project, so each test makes its own. */
async function openEditDialog(page: import("@playwright/test").Page) {
  const customer = `E2E-Cust-${Date.now()}`
  await page.goto("/customers")
  await page.getByLabel("Name").first().fill(customer)
  await page.getByRole("button", { name: "Create customer" }).click()
  await expect(page.getByText(customer)).toBeVisible()

  const code = `E2E-${Date.now()}`
  await page.goto("/projects")
  await page.getByRole("button", { name: "New project" }).click()
  await page.getByLabel("Code").fill(code)
  await page.getByLabel("Name").fill("E2E Project")
  await page.getByRole("combobox").click()
  await page.getByRole("option", { name: customer }).click()
  await page.getByRole("button", { name: "Create project" }).click()

  const row = page.getByRole("row", { name: new RegExp(code) })
  await row.getByRole("button", { name: "Edit" }).click()
  const dialog = page.getByRole("dialog", { name: /Edit project/ })
  await expect(dialog).toBeVisible()
  return dialog
}

test("the date picker opens, selects and returns focus inside the dialog", async ({
  page,
}) => {
  const dialog = await openEditDialog(page)

  const start = dialog.getByLabel("Start date")
  await start.click()

  // The popover stacks above the dialog rather than behind it.
  const picker = page.getByRole("dialog", { name: "Choose date" })
  await expect(picker).toBeVisible()

  await picker.getByRole("gridcell", { name: display(today), exact: true }).click()
  await expect(picker).toBeHidden()
  await expect(start).toHaveText(display(today))

  // Focus came back to the trigger, and the parent dialog is still open —
  // selecting a date must not dismiss the form underneath it.
  await expect(start).toBeFocused()
  await expect(dialog).toBeVisible()
})

test("Escape closes only the picker, not the dialog underneath it", async ({
  page,
}) => {
  const dialog = await openEditDialog(page)
  const end = dialog.getByLabel("End date")

  await end.click()
  await expect(page.getByRole("dialog", { name: "Choose date" })).toBeVisible()

  await page.keyboard.press("Escape")
  await expect(page.getByRole("dialog", { name: "Choose date" })).toBeHidden()
  await expect(dialog).toBeVisible()
  await expect(end).toBeFocused()
})
```

`openEditDialog` is copied verbatim from the setup in `frontend/tests/project-edit-flow.spec.ts`, so the selectors are already known-good. If that spec has since changed, re-copy from it rather than inventing new selectors.

- [ ] **Step 3: Typecheck and lint**

Run: `cd frontend && bun run lint && bun run build`
Expected: clean.

- [ ] **Step 4: Run the E2E specs**

Run: `cd frontend && E2E_SKIP_DB_RESET=1 bunx playwright test tests/project-date-dialog.spec.ts tests/project-edit.spec.ts tests/project-edit-flow.spec.ts`
Expected: all pass.

If Escape closes both layers, the fix is `onEscapeKeyDown` stopping propagation on the popover content — but confirm the failure first rather than adding the handler pre-emptively.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/projects/ProjectEditDialog.tsx frontend/tests/project-date-dialog.spec.ts
git commit -m "feat(projects): themed DatePicker in the project edit dialog"
```

---

### Task 6: `MonthPicker` + both report pages

**Files:**
- Modify: `frontend/src/components/ui/date-picker.tsx` (append `MonthPicker`)
- Modify: `frontend/src/routes/_layout/channel-margin.tsx:13` (drop `Input`), `:141-151`
- Modify: `frontend/src/routes/_layout/override-exceptions.tsx:13` (drop `Input`), `:96-106`
- Create: `frontend/tests/month-picker.spec.ts`

**Interfaces:**
- Consumes from Task 1: `clampMonth`, `formatMonthDisplay`, `monthOf`, `todayISO`. From Task 2: `MonthGrid`. From Task 3: `FieldTrigger`, `Stepper` (module-private, already in the file).
- Produces:
  ```ts
  function MonthPicker(props: {
    id?: string
    labelledBy?: string             // id of the visible <Label>
    value: string                   // "YYYY-MM", "" when unset
    onChange: (ym: string) => void
    min?: string                    // "YYYY-MM"
    max?: string
    disabled?: boolean
    placeholder?: string            // default "Pick a month"
    className?: string
  }): JSX.Element
  ```

`MonthPicker` opens straight into the year view — the same `MonthGrid` the `DatePicker` caption drops to, which is what makes the report pages match the date pickers for free. It has no Today/Clear footer: both report screens always hold a month (`currentMonth()` is the initial value) and `isValidMonth()` rejects `""`.

- [ ] **Step 1: Append `MonthPicker` to `date-picker.tsx`**

Add at the end of `frontend/src/components/ui/date-picker.tsx`:

```tsx
export type MonthPickerProps = {
  id?: string
  /** id of the visible `<Label>` — see `FieldTriggerProps.labelledBy`. */
  labelledBy?: string
  /** ISO `YYYY-MM`, or `""` when unset. */
  value: string
  /** Receives the `YYYY-MM` string — not a change event. */
  onChange: (ym: string) => void
  min?: string
  max?: string
  disabled?: boolean
  placeholder?: string
  className?: string
}

export function MonthPicker({
  id,
  labelledBy,
  value,
  onChange,
  min,
  max,
  disabled,
  placeholder = "Pick a month",
  className,
}: MonthPickerProps) {
  const bounds = { min, max }
  const [open, setOpen] = useState(false)
  const [focused, setFocused] = useState(
    () => value || clampMonth(monthOf(todayISO()), bounds),
  )
  const [visibleYear, setVisibleYear] = useState(() =>
    Number((value || todayISO()).slice(0, 4)),
  )

  useEffect(() => {
    if (!open) return
    const start = value || clampMonth(monthOf(todayISO()), { min, max })
    setFocused(start)
    setVisibleYear(Number(start.slice(0, 4)))
  }, [open, value, min, max])

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <FieldTrigger
        id={id}
        labelledBy={labelledBy}
        label={value ? formatMonthDisplay(value) : placeholder}
        isPlaceholder={!value}
        disabled={disabled}
        className={className}
        onOpen={() => setOpen(true)}
      />
      <PopoverContent
        align="start"
        aria-label="Choose month"
        className="w-auto rounded-lg p-3"
        onOpenAutoFocus={(event) => {
          event.preventDefault()
        }}
      >
        <Stepper
          prevLabel="Previous year"
          onPrev={() => setVisibleYear((y) => y - 1)}
          nextLabel="Next year"
          onNext={() => setVisibleYear((y) => y + 1)}
        >
          <span aria-live="polite" className="text-sm font-medium">
            {visibleYear}
          </span>
        </Stepper>
        <MonthGrid
          year={visibleYear}
          selected={value}
          focused={focused}
          bounds={bounds}
          onSelect={(ym) => {
            onChange(ym)
            setOpen(false)
          }}
          onFocusedChange={(ym) => {
            setFocused(ym)
            setVisibleYear(Number(ym.slice(0, 4)))
          }}
        />
      </PopoverContent>
    </Popover>
  )
}
```

- [ ] **Step 2: Swap the channel-margin month**

In `frontend/src/routes/_layout/channel-margin.tsx`, delete line 13 (`import { Input } from "@/components/ui/input"` — the month is the file's only `<Input>` use) and add:

```tsx
import { MonthPicker } from "@/components/ui/date-picker"
```

Replace lines 142-151:

```tsx
        <div className="flex flex-col gap-1.5">
          <Label id="month-label" htmlFor="month">
            Month
          </Label>
          <MonthPicker
            id="month"
            labelledBy="month-label"
            value={month}
            onChange={setMonth}
            className="w-full sm:w-48"
          />
        </div>
```

- [ ] **Step 3: Swap the override-exceptions month**

In `frontend/src/routes/_layout/override-exceptions.tsx`, delete line 13 (`import { Input } from "@/components/ui/input"` — again the file's only `<Input>` use) and add:

```tsx
import { MonthPicker } from "@/components/ui/date-picker"
```

Replace lines 97-106:

```tsx
        <div className="flex flex-col gap-1.5">
          <Label id="month-label" htmlFor="month">
            Month
          </Label>
          <MonthPicker
            id="month"
            labelledBy="month-label"
            value={month}
            onChange={setMonth}
            className="w-full sm:w-48"
          />
        </div>
```

- [ ] **Step 4: Write the E2E spec**

Create `frontend/tests/month-picker.spec.ts`:

```ts
import { expect, test } from "@playwright/test"

// The two monthly report screens share the MonthPicker, which is the same
// MonthGrid the DatePicker caption drops to. Runs authed as the seeded
// superuser via storageState (global.setup).

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

const now = new Date()
const thisMonth = `${MONTHS[now.getMonth()]} ${now.getFullYear()}`
const lastYearSameMonth = `${MONTHS[now.getMonth()]} ${now.getFullYear() - 1}`

test("channel margin defaults to this month and picks another one", async ({
  page,
}) => {
  await page.goto("/channel-margin")

  const trigger = page.getByLabel("Month")
  await expect(trigger).toHaveText(thisMonth)

  // Step back a year, then pick the same month in it.
  await trigger.click()
  const picker = page.getByRole("dialog", { name: "Choose month" })
  await picker.getByRole("button", { name: "Previous year" }).click()
  await picker
    .getByRole("gridcell", { name: lastYearSameMonth, exact: true })
    .click()

  await expect(picker).toBeHidden()
  await expect(trigger).toHaveText(lastYearSameMonth)
  // The report re-queries rather than erroring on the new month.
  await expect(page.getByRole("heading", { name: "Channel margin" })).toBeVisible()
})

test("override exceptions picks a month with the keyboard", async ({ page }) => {
  await page.goto("/override-exceptions")

  const trigger = page.getByLabel("Month")
  await expect(trigger).toHaveText(thisMonth)

  await trigger.focus()
  await page.keyboard.press("Enter")
  // Focus opens on the current month; Home jumps to January of that year.
  await page.keyboard.press("Home")
  await page.keyboard.press("Enter")

  await expect(trigger).toHaveText(`Jan ${now.getFullYear()}`)
})
```

- [ ] **Step 5: Typecheck, lint, unit**

Run: `cd frontend && bun run lint && bun run build && bun run test:unit`
Expected: clean, no unused-import errors on either report page.

- [ ] **Step 6: Run the E2E specs**

Run: `cd frontend && E2E_SKIP_DB_RESET=1 bunx playwright test tests/month-picker.spec.ts tests/reports.spec.ts tests/channel-margin-drilldown.spec.ts`
Expected: all pass.

- [ ] **Step 7: Confirm no native date control survives anywhere**

Run: `cd frontend && grep -rn 'type="date"\|type="month"' src/ tests/`
Expected: no output. Any hit is an unmigrated call site.

Run: `cd frontend && grep -rn 'input\[type="date"\]\|\.fill("20' tests/`
Expected: no output. No spec may drive a date field by typing.

- [ ] **Step 8: Full-suite verification**

Run: `cd frontend && bun run test:unit && E2E_SKIP_DB_RESET=1 bunx playwright test`
Expected: vitest all-pass; Playwright all-pass. Report the actual counts — do not claim green without the output.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/ui/date-picker.tsx frontend/src/routes/_layout/channel-margin.tsx frontend/src/routes/_layout/override-exceptions.tsx frontend/tests/month-picker.spec.ts
git commit -m "feat(reports): themed MonthPicker on both monthly report screens"
```

---

## Review and ship

After Task 6, before opening a PR:

1. Run `superpowers:requesting-code-review`.
2. This change touches no stock movement, ledger, or money path, so the mandatory `ecc:database-reviewer` / `ecc:security-reviewer` pass for high-risk changes does not apply. It **is** a broad UI + accessibility change, so dispatch `ecc:react-reviewer`, `ecc:typescript-reviewer`, and `ecc:a11y-architect` (the APG conformance is hand-written and is the main correctness risk).
3. Ship with `create-pr` into `dev`. One PR for the whole redesign — the tasks are not independently shippable, since Task 2 leaves unused components and Tasks 3–6 each leave the app mid-migration.
4. Leave the uncommitted `sync-review.tsx` / `EditProductDialog.tsx` / `products.tsx` changes out of this branch and PR.
