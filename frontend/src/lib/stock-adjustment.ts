import type {
  AdjustmentTarget,
  SkuBatchAdminPublic,
  SkuBatchPublic,
  SkuSearchAdminResult,
  SkuSearchResult,
  StockAdjustmentCreate,
} from "@/client/types.gen"

// ---------------------------------------------------------------------------
// Pure form logic for the admin Stock Adjustment screen (FR-011 / Flow E).
//
// Mirrors the backend StockAdjustmentCreate validator so the UI only POSTs a
// body the server will accept:
//   - UNIT     → castranova_barcode + reason (unit → terminal ADJUSTED_OUT)
//   - QUANTITY → sku + non-zero quantity_delta + reason; a positive delta also
//                needs purchase_cost_thb (cost basis of the new ADJ batch).
// ---------------------------------------------------------------------------

export interface AdjustmentDraft {
  targetKind: AdjustmentTarget
  barcode: string
  sku: string
  /** Signed integer as typed; parsed at submit. */
  qtyDelta: string
  /** Decimal string; only used for a positive QUANTITY delta. */
  purchaseCost: string
  reason: string
}

export const emptyAdjustmentDraft: AdjustmentDraft = {
  targetKind: "UNIT",
  barcode: "",
  sku: "",
  qtyDelta: "",
  purchaseCost: "",
  reason: "",
}

/** Parsed signed integer, or null if not a valid integer. */
function parseDelta(raw: string): number | null {
  const trimmed = raw.trim()
  if (!/^-?\d+$/.test(trimmed)) return null
  return Number.parseInt(trimmed, 10)
}

export function canSubmitAdjustment(d: AdjustmentDraft): boolean {
  if (d.reason.trim() === "") return false
  if (d.targetKind === "UNIT") return d.barcode.trim() !== ""
  // QUANTITY
  if (d.sku.trim() === "") return false
  const delta = parseDelta(d.qtyDelta)
  if (delta === null || delta === 0) return false
  if (delta > 0 && d.purchaseCost.trim() === "") return false
  return true
}

export function buildAdjustmentPayload(
  d: AdjustmentDraft,
  idempotencyKey: string,
): StockAdjustmentCreate {
  if (d.targetKind === "UNIT") {
    return {
      target_kind: "UNIT",
      castranova_barcode: d.barcode.trim(),
      reason: d.reason.trim(),
      idempotency_key: idempotencyKey,
    }
  }
  const delta = parseDelta(d.qtyDelta) ?? 0
  const body: StockAdjustmentCreate = {
    target_kind: "QUANTITY",
    sku: d.sku.trim(),
    quantity_delta: delta,
    reason: d.reason.trim(),
    idempotency_key: idempotencyKey,
  }
  if (delta > 0) body.purchase_cost_thb = d.purchaseCost.trim()
  return body
}

/** A bare `in` check leaves the staff shape in the union (TS widens it to
 *  `SkuBatchPublic & Record<"purchase_cost_thb", unknown>`), so the narrowing
 *  is spelled out as a predicate. */
function hasCost(
  batch: SkuBatchAdminPublic | SkuBatchPublic,
): batch is SkuBatchAdminPublic {
  return "purchase_cost_thb" in batch
}

/** Newest batch for a SKU — the search endpoint returns batches oldest-first,
 *  so that is the last one. This is the default cost basis for a positive
 *  adjustment. Null for staff-scoped results (no cost in the payload),
 *  SERIALIZED SKUs, and SKUs that have never been received. */
export function latestCostBatch(
  res: SkuSearchAdminResult | SkuSearchResult | undefined,
): SkuBatchAdminPublic | null {
  const batches = res?.batches ?? []
  // Not .at(-1): tsconfig targets ES2020 and Array.prototype.at is ES2022.
  const newest = batches[batches.length - 1]
  return newest && hasCost(newest) ? newest : null
}
