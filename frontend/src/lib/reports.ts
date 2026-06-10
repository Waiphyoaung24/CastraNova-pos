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
