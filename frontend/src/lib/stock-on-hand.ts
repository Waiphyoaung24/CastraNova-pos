import type { StockOnHandRow } from "@/client/types.gen"

// ---------------------------------------------------------------------------
// Pure client-side filtering for the Stock-on-Hand dashboard (FR-012).
//
// The server handles the supplier filter (admin-only data) as a query param;
// category + free-text are filtered here for instant feedback over the rows
// already in hand. No cost/margin anywhere — this view is both-roles.
// ---------------------------------------------------------------------------

/** Sorted, unique, non-null categories present in the current rows. */
export function deriveCategories(rows: StockOnHandRow[]): string[] {
  const set = new Set<string>()
  for (const r of rows) {
    if (r.category) set.add(r.category)
  }
  return Array.from(set).sort((a, b) => a.localeCompare(b))
}

export interface StockFilter {
  /** Exact category match; empty string means "all". */
  category: string
  /** Case-insensitive substring match on sku + model_name; empty means "all". */
  query: string
}

export function filterStockRows(
  rows: StockOnHandRow[],
  { category, query }: StockFilter,
): StockOnHandRow[] {
  const q = query.trim().toLowerCase()
  return rows.filter((r) => {
    if (category && r.category !== category) return false
    if (q) {
      const hay = `${r.sku} ${r.model_name}`.toLowerCase()
      if (!hay.includes(q)) return false
    }
    return true
  })
}
