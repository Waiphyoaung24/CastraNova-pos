import type {
  ProjectPullCreate,
  ProjectPullLineCreate,
} from "@/client/types.gen"
import type { ScanLookupResult } from "@/hooks/useScanLookup"

// ---------------------------------------------------------------------------
// Pure create-cart logic for the project-pull screen (admin create flow).
//
// UNIT scans become serialized request lines (keyed by barcode, qty 1). PART
// scans become quantity request lines (keyed by sku, qty merges). The catalog
// (sku -> {productId, modelName}) supplies display names. No cost anywhere.
// ---------------------------------------------------------------------------

/** Catalog entry keyed by sku, built from the products query. */
export type CreateCatalogEntry = {
  productId: string
  modelName: string
}

/** A request line in the create cart, keyed by barcode (UNIT) or sku (PART). */
export type CreateLine = {
  key: string
  lineKind: "UNIT" | "PART"
  productId: string
  sku: string
  modelName: string
  /** Present for UNIT lines (the scanned barcode). */
  unitSerial?: string
  /** Always 1 for UNIT; the requested amount for PART. */
  requestedQty: number
}

/**
 * Append a scanned item to the create cart, or merge it.
 * UNIT: keyed by barcode; re-scan is a no-op (same ref). Always added (a scanned
 *       unit is real); name falls back to its sku if absent from the catalog.
 * PART: keyed by sku; must be in the catalog, else unchanged (same ref); re-scan
 *       increments requestedQty.
 * NOT_FOUND: unchanged (same ref).
 */
export function addScanToCreateCart(
  lines: CreateLine[],
  scan: ScanLookupResult,
  catalog: Map<string, CreateCatalogEntry>,
): CreateLine[] {
  if (scan.kind === "UNIT") {
    const key = scan.data.castranova_barcode
    if (lines.some((l) => l.lineKind === "UNIT" && l.key === key)) return lines
    const entry = catalog.get(scan.data.sku)
    return [
      ...lines,
      {
        key,
        lineKind: "UNIT",
        productId: scan.data.product_id,
        sku: scan.data.sku,
        modelName: entry?.modelName ?? scan.data.sku,
        unitSerial: key,
        requestedQty: 1,
      },
    ]
  }
  if (scan.kind === "PART") {
    const entry = catalog.get(scan.data.sku)
    if (!entry) return lines
    const key = scan.data.sku
    if (lines.some((l) => l.key === key)) {
      return lines.map((l) =>
        l.key === key ? { ...l, requestedQty: l.requestedQty + 1 } : l,
      )
    }
    return [
      ...lines,
      {
        key,
        lineKind: "PART",
        productId: entry.productId,
        sku: scan.data.sku,
        modelName: entry.modelName,
        requestedQty: 1,
      },
    ]
  }
  return lines
}

/** Set a PART line's requestedQty (floored at 1). UNIT lines are left at 1. */
export function setCreateQty(
  lines: CreateLine[],
  key: string,
  qty: number,
): CreateLine[] {
  return lines.map((l) => {
    if (l.key !== key || l.lineKind === "UNIT") return l
    return {
      ...l,
      requestedQty: Math.max(1, Math.floor(Number.isFinite(qty) ? qty : 1)),
    }
  })
}

/** Remove the line with `key`. */
export function removeCreateLine(
  lines: CreateLine[],
  key: string,
): CreateLine[] {
  return lines.filter((l) => l.key !== key)
}

/** Build the create payload; blank notes -> null. */
export function buildCreatePayload(
  lines: CreateLine[],
  projectId: string,
  adminNotes: string,
): ProjectPullCreate {
  return {
    project_id: projectId,
    admin_notes: adminNotes.trim() === "" ? null : adminNotes,
    lines: lines.map(
      (l): ProjectPullLineCreate =>
        l.lineKind === "UNIT"
          ? {
              line_kind: "UNIT",
              product_id: l.productId,
              unit_serial: l.unitSerial ?? null,
            }
          : {
              line_kind: "PART",
              product_id: l.productId,
              requested_qty: l.requestedQty,
            },
    ),
  }
}
