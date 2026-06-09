import type { SaleCreateRequest, SaleLineInput } from "@/client/types.gen"
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

type CartLineBase = {
  /** Stable id: barcode for UNIT, sku for PART. */
  key: string
  sku: string
  productId: string
  quantity: number
  /** Selling price from priceMap; 0 when the product is missing from the map. */
  unitPriceThb: number
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

/** Σ unitPriceThb × quantity across all lines (display-only). */
export function cartSubtotalThb(lines: CartLine[]): number {
  return lines.reduce((sum, l) => sum + l.unitPriceThb * l.quantity, 0)
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
    lines: lines.map(
      (l): SaleLineInput =>
        l.lineKind === "UNIT"
          ? {
              line_kind: "UNIT",
              castranova_barcode: l.barcode,
              quantity: l.quantity,
            }
          : { line_kind: "PART", sku: l.sku, quantity: l.quantity },
    ),
  }
}
