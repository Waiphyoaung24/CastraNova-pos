import type {
  ProjectPullCreate,
  ProjectPullLineCreate,
} from "@/client/types.gen"

// ---------------------------------------------------------------------------
// Pure create-cart logic for the project-pull screen (admin create flow).
//
// UNIT lines are serialized request lines (keyed by barcode, qty 1). PART
// lines are quantity request lines (keyed by sku, qty merges). No cost anywhere.
// ---------------------------------------------------------------------------

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

/** Merge a QUANTITY product into the cart as a PART line, keyed by sku. */
export function addPartToCreateCart(
  lines: CreateLine[],
  product: { productId: string; sku: string; modelName: string },
  qty: number,
): CreateLine[] {
  const add = Math.max(1, Math.floor(Number.isFinite(qty) ? qty : 1))
  const key = product.sku
  if (lines.some((l) => l.key === key)) {
    return lines.map((l) =>
      l.key === key ? { ...l, requestedQty: l.requestedQty + add } : l,
    )
  }
  return [
    ...lines,
    {
      key,
      lineKind: "PART",
      productId: product.productId,
      sku: product.sku,
      modelName: product.modelName,
      requestedQty: add,
    },
  ]
}

/**
 * Append one UNIT line per serial (keyed by serial), skipping serials already
 * in the cart. Returns the same array ref when nothing fresh is added.
 */
export function addUnitsToCreateCart(
  lines: CreateLine[],
  product: { productId: string; sku: string; modelName: string },
  serials: string[],
): CreateLine[] {
  const present = new Set(
    lines.filter((l) => l.lineKind === "UNIT").map((l) => l.key),
  )
  const fresh = serials.filter((s) => s.length > 0 && !present.has(s))
  if (fresh.length === 0) return lines
  return [
    ...lines,
    ...fresh.map(
      (serial): CreateLine => ({
        key: serial,
        lineKind: "UNIT",
        productId: product.productId,
        sku: product.sku,
        modelName: product.modelName,
        unitSerial: serial,
        requestedQty: 1,
      }),
    ),
  ]
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
