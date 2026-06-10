import type { BulkMinStockItem } from "@/client/types.gen"

// ---------------------------------------------------------------------------
// Pure helper for the low-stock dashboard bulk min-level save (FR-016).
// ---------------------------------------------------------------------------

export interface MinStockDraft {
  productId: string
  /** Raw input value from the row's number field. */
  value: string
  /** The currently persisted min-stock level, to detect a real change. */
  original: number
}

/**
 * Bulk-update items for rows whose edited value is a valid non-negative integer
 * different from the persisted level. Blank, invalid, and unchanged rows are
 * dropped, so a no-op save sends nothing.
 */
export function buildBulkMinStockUpdate(
  drafts: MinStockDraft[],
): BulkMinStockItem[] {
  const items: BulkMinStockItem[] = []
  for (const d of drafts) {
    const trimmed = d.value.trim()
    if (trimmed === "") continue
    const n = Number(trimmed)
    if (!Number.isInteger(n) || n < 0) continue
    if (n === d.original) continue
    items.push({ product_id: d.productId, min_stock_level: n })
  }
  return items
}
