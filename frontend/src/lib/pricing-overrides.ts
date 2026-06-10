import type { OverrideState } from "@/client/types.gen"

// ---------------------------------------------------------------------------
// Pure helpers for the pricing-override approval queue (FR-010).
// ---------------------------------------------------------------------------

/** Render the stored deviation percent (e.g. "3.0000") as "3.00%". */
export function formatDeviationPct(value: string): string {
  return `${Number(value).toFixed(2)}%`
}

/** Only PENDING requests can be approved/rejected (mirrors the backend). */
export function isPending(state: OverrideState): boolean {
  return state === "PENDING"
}
