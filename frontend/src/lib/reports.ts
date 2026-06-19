// Pure helpers for the admin report screens (FR-013 channel margin, FR-014
// holding period). Kept framework-free so the screens stay thin and the logic
// is unit-testable without a browser (mirrors lib/stock-on-hand.ts).

/** Format a decimal-string THB amount for display, e.g. "1400.00" -> "฿1,400.00". */
export function formatThb(value: string): string {
  return `฿${new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(value))}`
}

/**
 * Current month as YYYY-MM — the shape an <input type="month"> emits and the
 * channel-margin endpoint expects. `now` is injectable for deterministic tests.
 */
export function currentMonth(now: Date = new Date()): string {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`
}

/** True when `month` is a well-formed YYYY-MM string. */
export function isValidMonth(month: string): boolean {
  return /^\d{4}-\d{2}$/.test(month)
}

/** The calendar month before `month` (YYYY-MM), rolling the year at January. */
export function previousMonth(month: string): string {
  const year = Number(month.slice(0, 4))
  const mon = Number(month.slice(5, 7))
  const prev = mon === 1 ? 12 : mon - 1
  const prevYear = mon === 1 ? year - 1 : year
  return `${prevYear}-${String(prev).padStart(2, "0")}`
}

export type ReportFormat = "pdf" | "xlsx"

interface ReportExport {
  path: string
  filename: string
}

/** Authed-download path + filename for the channel-margin export. */
export function channelMarginExport(
  month: string,
  fmt: ReportFormat,
): ReportExport {
  return {
    path: `/api/v1/reports/channel-margin.${fmt}?month=${month}`,
    filename: `channel-margin-${month}.${fmt}`,
  }
}

/** Authed-download path + filename for the override-exceptions export. */
export function overrideExceptionsExport(
  month: string,
  fmt: ReportFormat,
): ReportExport {
  return {
    path: `/api/v1/reports/override-exceptions.${fmt}?month=${month}`,
    filename: `override-exceptions-${month}.${fmt}`,
  }
}

/** Authed-download path + filename for the holding-period export. */
export function holdingPeriodExport(
  overThresholdOnly: boolean,
  fmt: ReportFormat,
): ReportExport {
  return {
    path: `/api/v1/reports/holding-period.${fmt}?over_threshold_only=${overThresholdOnly}`,
    filename: `holding-period.${fmt}`,
  }
}

// --- CFO metric helpers ------------------------------------------------------
// Pure, display-boundary derivations layered on the existing report endpoints
// (no extra API surface). Money values arrive as decimal strings (Postgres
// NUMERIC) and are parsed here at the edge with Number(...).

/** Format a numeric percentage, e.g. `formatPct(42.5)` -> "42.5%". */
export function formatPct(value: number, digits = 1): string {
  return `${value.toFixed(digits)}%`
}

/**
 * Margin as a percentage of revenue. Returns null when revenue is zero (the
 * ratio is undefined) so the caller can render "—" instead of NaN/∞.
 */
export function marginPct(
  marginThb: string,
  revenueThb: string,
): number | null {
  const revenue = Number(revenueThb)
  if (revenue === 0) return null
  return (Number(marginThb) / revenue) * 100
}

/** A part's share of a total, as a percentage. 0 when the total is zero. */
export function sharePct(part: string, total: string): number {
  const t = Number(total)
  if (t === 0) return 0
  return (Number(part) / t) * 100
}

/**
 * A month-over-month change shown on a KPI: magnitude + direction + whether
 * the move is "good" (for colour). Direction is the caller's concern only for
 * the arrow; `good` flips via `invert` for cost-like metrics where up is bad.
 */
export interface MetricDelta {
  /** Magnitude only, preformatted (e.g. "12.3%" or "4.0 pp"). */
  value: string
  direction: "up" | "down" | "flat"
  good: boolean
}

// Treat sub-epsilon moves as flat so rounding noise doesn't show a spurious arrow.
const FLAT_EPSILON = 0.05

function classify(
  signedChange: number,
  invert: boolean,
): Pick<MetricDelta, "direction" | "good"> {
  const direction =
    signedChange > FLAT_EPSILON
      ? "up"
      : signedChange < -FLAT_EPSILON
        ? "down"
        : "flat"
  const good = invert ? direction === "down" : direction === "up"
  return { direction, good }
}

/**
 * Percentage change of a money value vs. the prior period. Returns null when
 * there is no comparable prior value (missing, or zero — % change undefined).
 */
export function momChange(
  current: string,
  previous: string | undefined,
  opts: { invert?: boolean } = {},
): MetricDelta | null {
  if (previous == null || previous === "") return null
  const prev = Number(previous)
  if (prev === 0) return null
  const change = ((Number(current) - prev) / prev) * 100
  return {
    value: formatPct(Math.abs(change)),
    ...classify(change, !!opts.invert),
  }
}

/**
 * Difference of two already-percentage values, in percentage points (e.g.
 * blended margin % this month vs. last). Null when there is no prior value.
 */
export function pointChange(
  current: number,
  previous: number | null | undefined,
  opts: { invert?: boolean } = {},
): MetricDelta | null {
  if (previous == null) return null
  const diff = current - previous
  return {
    value: `${Math.abs(diff).toFixed(1)} pp`,
    ...classify(diff, !!opts.invert),
  }
}

// --- Holding-period ageing ---------------------------------------------------

/** One row's worth of the ageing inputs we summarise (subset of the API row). */
export interface HoldingRowLike {
  holding_days: number
  quantity: number
  over_threshold: boolean
}

export interface AgeingBucket {
  label: string
  /** Inclusive lower / upper day bound; upper is null for the open 90+ bucket. */
  min: number
  max: number | null
  count: number
  qty: number
}

export interface HoldingSummary {
  lineCount: number
  totalQty: number
  overThresholdCount: number
  maxDays: number
  avgDays: number
  buckets: AgeingBucket[]
}

/** The bucket a holding period falls in: 0–30, 31–60, 61–90, 90+. */
export function holdingBucketLabel(days: number): string {
  if (days <= 30) return "0–30"
  if (days <= 60) return "31–60"
  if (days <= 90) return "61–90"
  return "90+"
}

/**
 * Roll holding-period rows into count/qty ageing buckets plus headline figures
 * (oldest, average, over-threshold count). Value/cost is intentionally absent —
 * the holding-period API carries no cost field, so we never infer a THB figure.
 */
export function summarizeHolding(rows: HoldingRowLike[]): HoldingSummary {
  const buckets: AgeingBucket[] = [
    { label: "0–30", min: 0, max: 30, count: 0, qty: 0 },
    { label: "31–60", min: 31, max: 60, count: 0, qty: 0 },
    { label: "61–90", min: 61, max: 90, count: 0, qty: 0 },
    { label: "90+", min: 91, max: null, count: 0, qty: 0 },
  ]

  let totalQty = 0
  let overThresholdCount = 0
  let maxDays = 0
  let daysSum = 0

  for (const r of rows) {
    totalQty += r.quantity
    if (r.over_threshold) overThresholdCount += 1
    if (r.holding_days > maxDays) maxDays = r.holding_days
    daysSum += r.holding_days
    const label = holdingBucketLabel(r.holding_days)
    const bucket = buckets.find((b) => b.label === label)
    if (bucket) {
      bucket.count += 1
      bucket.qty += r.quantity
    }
  }

  return {
    lineCount: rows.length,
    totalQty,
    overThresholdCount,
    maxDays,
    avgDays: rows.length === 0 ? 0 : Math.round(daysSum / rows.length),
    buckets,
  }
}
