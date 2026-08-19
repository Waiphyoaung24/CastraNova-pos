/**
 * Staff-facing display labels.
 *
 * Maps internal enum values to plain words for non-technical staff. DISPLAY
 * ONLY — the database, API, and SDK keep their real values (SERIALIZED, FIFO,
 * the UnitState enum, …). These pure functions are unit-tested without React;
 * every staff screen imports from here so the wording stays consistent.
 */

/** Title-case a raw enum value as a readable fallback: FOO_BAR → "Foo bar". */
function humanize(value: string): string {
  const lower = value.replace(/_/g, " ").toLowerCase()
  return lower.charAt(0).toUpperCase() + lower.slice(1)
}

/** Product tracking mode → plain word. */
export function trackingModeLabel(mode: string): string {
  switch (mode) {
    case "SERIALIZED":
      return "Serialized"
    case "QUANTITY":
      return "Quantity"
    default:
      return mode
  }
}

/** A serialized unit's state → plain status word. */
export function unitStatusLabel(state: string): string {
  switch (state) {
    case "RECEIVED":
      return "Just received"
    case "IN_STOCK":
      return "In stock"
    case "SOLD":
      return "Sold"
    case "MAINTENANCE_OUT":
      return "In repair"
    case "PROJECT_OUT":
      return "Used on project"
    case "ADJUSTED_OUT":
      return "Removed"
    default:
      return humanize(state)
  }
}

/** Notification channel → friendly app name. */
export function channelLabel(channel: string): string {
  switch (channel) {
    case "LINE":
      return "LINE"
    case "TELEGRAM":
      return "Telegram"
    default:
      return channel
  }
}
