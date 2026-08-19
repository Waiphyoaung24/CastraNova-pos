import type {
  ServiceTicketPartCreate,
  ServiceTicketRecordRequest,
} from "@/client/types.gen"
import type { ScanLookupResult } from "@/hooks/useScanLookup"

// ---------------------------------------------------------------------------
// Pure cart logic for the service-ticket screen.
//
// Pricing here is DISPLAY-ONLY (the customer-facing repair price), never cost.
// The backend is authoritative at close time; the only price the screen shows is
// `repair_price_thb` from the products catalog, supplied via `partLookup`.
//
// Only QUANTITY-tracked PART scans are valid ticket parts (the backend's
// add-part endpoint rejects non-QUANTITY products). UNIT (serialized) scans,
// NOT_FOUND scans, and SKUs absent from the catalog leave the cart unchanged —
// the route renders the user-facing notice.
// ---------------------------------------------------------------------------

/** A catalog entry keyed by sku, built from the products query (QUANTITY only). */
export type PartCatalogEntry = {
  productId: string
  modelName: string
  /** Customer-facing repair price in THB (display only). */
  repairPriceThb: number
}

/** A single repair-part line, keyed and merged by sku. */
export type TicketPartLine = {
  /** Stable id == sku. */
  key: string
  sku: string
  productId: string
  modelName: string
  quantity: number
  unitPriceThb: number
}

/**
 * Append a scanned PART to the cart, or merge it into the existing line.
 * Returns `lines` unchanged (same reference) for UNIT / NOT_FOUND scans and for
 * PART SKUs that are not present in `partLookup`.
 */
export function addScanToTicketParts(
  lines: TicketPartLine[],
  scan: ScanLookupResult,
  partLookup: Map<string, PartCatalogEntry>,
): TicketPartLine[] {
  if (scan.kind !== "PART") return lines
  const entry = partLookup.get(scan.data.sku)
  if (!entry) return lines

  const key = scan.data.sku
  if (lines.some((l) => l.key === key)) {
    return lines.map((l) =>
      l.key === key ? { ...l, quantity: l.quantity + 1 } : l,
    )
  }
  return [
    ...lines,
    {
      key,
      sku: scan.data.sku,
      productId: entry.productId,
      modelName: entry.modelName,
      quantity: 1,
      unitPriceThb: entry.repairPriceThb,
    },
  ]
}

/** Set the quantity of the line with `key`, floored at 1. */
export function setPartQuantity(
  lines: TicketPartLine[],
  key: string,
  quantity: number,
): TicketPartLine[] {
  return lines.map((l) =>
    l.key === key
      ? {
          ...l,
          quantity: Math.max(
            1,
            Math.floor(Number.isFinite(quantity) ? quantity : 1),
          ),
        }
      : l,
  )
}

/** Remove the line with `key`. */
export function removePart(
  lines: TicketPartLine[],
  key: string,
): TicketPartLine[] {
  return lines.filter((l) => l.key !== key)
}

/** Σ unitPriceThb × quantity across all lines (display-only). */
export function ticketPartsSubtotalThb(lines: TicketPartLine[]): number {
  return lines.reduce((sum, l) => sum + l.unitPriceThb * l.quantity, 0)
}

/** The single atomic record payload sent on "Close ticket". */
export type TicketSubmission = ServiceTicketRecordRequest

/**
 * Shape the atomic record request. Blank `notes`/`resolution` become null; one
 * parts entry per cart line. Price is never sent — the backend defaults to the
 * product's repair price (or an approved override).
 */
export function buildTicketSubmission(
  lines: TicketPartLine[],
  customerId: string,
  issue: string,
  notes: string,
  resolution: string,
  idempotencyKey: string,
): TicketSubmission {
  const orNull = (s: string): string | null => (s.trim() === "" ? null : s)
  const parts: ServiceTicketPartCreate[] = lines.map((l) => ({
    sku: l.sku,
    quantity: l.quantity,
  }))
  return {
    customer_id: customerId,
    issue,
    notes: orNull(notes),
    resolution: orNull(resolution),
    idempotency_key: idempotencyKey,
    parts,
  }
}
