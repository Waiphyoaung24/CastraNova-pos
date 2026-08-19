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
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
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

/** The 12 months of `y`. Bounds are `YYYY-MM`. */
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
