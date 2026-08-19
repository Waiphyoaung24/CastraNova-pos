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

/** Signed % deviation of `requested` from `retail`; 0 when retail is not positive. */
export function deviationPct(retailThb: number, requestedThb: number): number {
  if (retailThb <= 0) return 0
  return ((requestedThb - retailThb) / retailThb) * 100
}

/** Override-dialog submit gate: a positive price and a non-blank reason. */
export function canSubmitOverride(input: {
  priceThb: string
  reason: string
}): boolean {
  const price = Number(input.priceThb)
  return (
    input.priceThb.trim() !== "" &&
    Number.isFinite(price) &&
    price > 0 &&
    input.reason.trim() !== ""
  )
}
