import type {
  ProjectPullFulfill,
  ProjectPullLinePublic,
} from "@/client/types.gen"
import type { ScanLookupResult } from "@/hooks/useScanLookup"

// ---------------------------------------------------------------------------
// Pure fulfill-draft logic for the project-pull screen.
//
// The draft maps line_id -> fulfilled_qty and ALWAYS holds every line on the
// pull (seeded to 0). This is mandatory: crud.fulfill_project_pull FULL-fills a
// line that is OMITTED from the payload, so an unscanned line must be sent as an
// explicit 0 to settle SHORT. Nothing here references cost (pulls are cost-only).
// ---------------------------------------------------------------------------

export type FulfillDraft = Record<string, number>

/** Max fulfillable qty for a line: 1 for UNIT, requested_qty (or 0) for PART. */
export function lineCap(line: ProjectPullLinePublic): number {
  return line.line_kind === "UNIT" ? 1 : (line.requested_qty ?? 0)
}

/** Seed a draft with every line at 0 (required — see file header). */
export function seedFulfillDraft(lines: ProjectPullLinePublic[]): FulfillDraft {
  const draft: FulfillDraft = {}
  for (const line of lines) draft[line.id] = 0
  return draft
}

/**
 * Apply a scan to the draft.
 * UNIT: match the line whose unit_serial === scanned barcode → set qty 1.
 * PART: match the PART line whose product_id === scanned product → increment,
 *       clamped to lineCap.
 * No match, or NOT_FOUND → return the same draft reference unchanged.
 */
export function applyScanToFulfill(
  draft: FulfillDraft,
  lines: ProjectPullLinePublic[],
  scan: ScanLookupResult,
): FulfillDraft {
  if (scan.kind === "UNIT") {
    const barcode = scan.data.castranova_barcode
    const line = lines.find(
      (l) => l.line_kind === "UNIT" && l.unit_serial === barcode,
    )
    if (!line) return draft
    return { ...draft, [line.id]: 1 }
  }
  if (scan.kind === "PART") {
    const productId = scan.data.product_id
    const line = lines.find(
      (l) => l.line_kind === "PART" && l.product_id === productId,
    )
    if (!line) return draft
    const next = Math.min((draft[line.id] ?? 0) + 1, lineCap(line))
    return { ...draft, [line.id]: next }
  }
  return draft
}

/** Set a line's qty, clamped to [0, cap], floored. */
export function setLineFulfilledQty(
  draft: FulfillDraft,
  line: ProjectPullLinePublic,
  qty: number,
): FulfillDraft {
  const clamped = Math.max(
    0,
    Math.min(lineCap(line), Math.floor(Number.isFinite(qty) ? qty : 0)),
  )
  return { ...draft, [line.id]: clamped }
}

/** Build the fulfill payload — every draft entry sent explicitly (see header). */
export function buildFulfillPayload(draft: FulfillDraft): ProjectPullFulfill {
  return {
    lines: Object.entries(draft).map(([line_id, fulfilled_qty]) => ({
      line_id,
      fulfilled_qty,
    })),
  }
}

/** Preview: FULFILLED iff every line's drafted qty >= its cap, else SHORT. */
export function projectedPullState(
  lines: ProjectPullLinePublic[],
  draft: FulfillDraft,
): "FULFILLED" | "SHORT" {
  const allFull = lines.every((l) => (draft[l.id] ?? 0) >= lineCap(l))
  return allFull ? "FULFILLED" : "SHORT"
}
