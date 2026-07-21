import type { OverrideState, SaleCreateRequest, SaleLineInput } from "@/client/types.gen"
import type { ScanLookupResult } from "@/hooks/useScanLookup"

// ---------------------------------------------------------------------------
// Pure cart logic for the Sale/POS screen.
//
// Pricing here is DISPLAY-ONLY: the cart computes a local subtotal from a
// caller-supplied catalog `priceMap` (product_id → selling price in THB). The
// backend is authoritative at sale time, so no price fields are sent in the
// request payload.
//
// Merge semantics:
//   - UNIT lines represent a single serialized piece keyed by barcode. A UNIT
//     is always quantity 1; re-scanning the same barcode is a no-op (you can't
//     sell the same serial twice).
//   - PART lines are non-serialized stock keyed by sku; re-scanning the same
//     sku increments the quantity, and PART quantity is floored at 1.
// ---------------------------------------------------------------------------

/** A price-override request attached to a line (FR-010). */
export type LineOverride = {
  /** PricingOverridePublic.id */
  id: string
  state: OverrideState
  requestedPriceThb: number
}

type CartLineBase = {
  /** Stable id: barcode for UNIT, sku for PART. */
  key: string
  sku: string
  productId: string
  quantity: number
  /** Selling price from priceMap; 0 when the product is missing from the map. */
  unitPriceThb: number
  /** Price-override request for this line, if the operator made one. */
  override?: LineOverride
}

/** A single serialized piece, keyed and identified by its barcode. */
export type UnitLine = CartLineBase & {
  lineKind: "UNIT"
  /** Always present for UNIT lines. */
  barcode: string
}

/** Non-serialized stock, keyed by sku; never carries a barcode. */
export type PartLine = CartLineBase & {
  lineKind: "PART"
  barcode?: never
}

export type CartLine = UnitLine | PartLine

function priceFor(priceMap: Map<string, number>, productId: string): number {
  return priceMap.get(productId) ?? 0
}

/**
 * Append a scanned entity to the cart, or merge it into an existing line.
 *
 * UNIT: keyed by barcode; re-scanning an existing UNIT is a no-op (qty stays 1).
 * PART: keyed by sku; re-scanning increments the existing line's quantity.
 * NOT_FOUND: returns `lines` unchanged (same reference).
 */
export function addScanToCart(
  lines: CartLine[],
  scan: ScanLookupResult,
  priceMap: Map<string, number>,
): CartLine[] {
  if (scan.kind === "NOT_FOUND") return lines

  if (scan.kind === "UNIT") {
    const key = scan.data.castranova_barcode
    // Dedup against UNIT lines only, so a UNIT barcode that happens to equal a
    // PART sku can't false-match an existing PART line.
    if (lines.some((l) => l.lineKind === "UNIT" && l.key === key)) {
      return lines // single serial, no dup
    }
    return [
      ...lines,
      {
        key,
        lineKind: "UNIT",
        barcode: key,
        sku: scan.data.sku,
        productId: scan.data.product_id,
        quantity: 1,
        unitPriceThb: priceFor(priceMap, scan.data.product_id),
      },
    ]
  }

  // PART — merge by sku, incrementing quantity on repeat scans.
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
      lineKind: "PART",
      sku: scan.data.sku,
      productId: scan.data.product_id,
      quantity: 1,
      unitPriceThb: priceFor(priceMap, scan.data.product_id),
    },
  ]
}

/**
 * Set the quantity of the line with `key`. PART quantities are floored at 1;
 * UNIT lines are always quantity 1 and are left untouched.
 */
export function setLineQuantity(
  lines: CartLine[],
  key: string,
  quantity: number,
): CartLine[] {
  return lines.map((l) => {
    if (l.key !== key) return l
    if (l.lineKind === "UNIT") return l
    return {
      ...l,
      quantity: Math.max(
        1,
        Math.floor(Number.isFinite(quantity) ? quantity : 1),
      ),
    }
  })
}

/** Remove the line with `key` from the cart. */
export function removeLine(lines: CartLine[], key: string): CartLine[] {
  return lines.filter((l) => l.key !== key)
}

/** AUTO_APPROVED / APPROVED change the effective price; PENDING / REJECTED don't. */
function overrideActive(o: LineOverride | undefined): o is LineOverride {
  return o !== undefined && (o.state === "AUTO_APPROVED" || o.state === "APPROVED")
}

/** Set/replace the override on the line with `key`; unknown key returns `lines`. */
export function applyOverride(
  lines: CartLine[],
  key: string,
  override: LineOverride,
): CartLine[] {
  if (!lines.some((l) => l.key === key)) return lines
  return lines.map((l) => (l.key === key ? { ...l, override } : l))
}

/** Drop the override on the line with `key` (used when a request is REJECTED). */
export function clearOverride(lines: CartLine[], key: string): CartLine[] {
  return lines.map((l) => (l.key === key ? { ...l, override: undefined } : l))
}

/** Effective unit price: the requested price once approved, else retail. */
export function lineUnitPriceThb(line: CartLine): number {
  return overrideActive(line.override)
    ? line.override.requestedPriceThb
    : line.unitPriceThb
}

/** True while any line's override awaits an admin decision; gates checkout. */
export function cartHasPendingOverride(lines: CartLine[]): boolean {
  return lines.some((l) => l.override?.state === "PENDING")
}

/** Σ effective unit price × quantity across all lines (display-only). */
export function cartSubtotalThb(lines: CartLine[]): number {
  return lines.reduce((sum, l) => sum + lineUnitPriceThb(l) * l.quantity, 0)
}

/**
 * Map the cart to a SaleCreateRequest. Price fields are intentionally omitted —
 * the backend computes pricing and is authoritative.
 */
export function buildSaleRequest(
  lines: CartLine[],
  customerId: string,
  idempotencyKey: string,
): SaleCreateRequest {
  return {
    customer_id: customerId,
    idempotency_key: idempotencyKey,
    lines: lines.map((l): SaleLineInput => {
      const base =
        l.lineKind === "UNIT"
          ? {
              line_kind: "UNIT" as const,
              castranova_barcode: l.barcode,
              quantity: l.quantity,
            }
          : { line_kind: "PART" as const, sku: l.sku, quantity: l.quantity }
      // Only a decided-approved override is referenced; the backend re-validates
      // it (state, product match) and stays price-authoritative.
      return overrideActive(l.override)
        ? { ...base, pricing_override_request_id: l.override.id }
        : base
    }),
  }
}
