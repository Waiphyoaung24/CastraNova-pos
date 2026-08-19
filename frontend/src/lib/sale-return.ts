import type { SaleReturnCreateRequest } from "@/client/types.gen"

// ---------------------------------------------------------------------------
// Pure form logic for recording a sale return from the Stock Adjustment screen
// (design 2026-07-25). Mirrors the backend guards so the UI never POSTs a body
// the server will reject:
//   - a sale line must be picked
//   - quantity is a positive integer, capped at what is still returnable
//   - a reason is required, like every stock adjustment
// The refund is NOT part of the draft: it is fixed at the original sale price
// and is display-only.
// ---------------------------------------------------------------------------

export interface ReturnDraft {
  saleId: string
  saleLineId: string
  /** Positive integer as typed; parsed at submit. */
  quantity: string
  reason: string
}

export const emptyReturnDraft: ReturnDraft = {
  saleId: "",
  saleLineId: "",
  quantity: "1",
  reason: "",
}

/** Parsed positive integer, or null if not a valid one. */
function parseQuantity(raw: string): number | null {
  const trimmed = raw.trim()
  if (!/^\d+$/.test(trimmed)) return null
  const n = Number.parseInt(trimmed, 10)
  return n > 0 ? n : null
}

/**
 * Constrains what the quantity field will hold as it is typed: digits only,
 * no leading zeros, never above the cap. An empty result is kept empty so the
 * field can be cleared and retyped — `canSubmitReturn` rejects it.
 */
export function clampReturnQuantity(raw: string, maxQuantity: number): string {
  const digits = raw.replace(/\D/g, "").replace(/^0+/, "")
  if (digits === "") return ""
  return String(Math.min(Number.parseInt(digits, 10), maxQuantity))
}

export function canSubmitReturn(d: ReturnDraft, maxQuantity: number): boolean {
  if (d.saleLineId.trim() === "") return false
  if (d.reason.trim() === "") return false
  const qty = parseQuantity(d.quantity)
  if (qty === null) return false
  return qty <= maxQuantity
}

export function buildReturnPayload(
  d: ReturnDraft,
  idempotencyKey: string,
): SaleReturnCreateRequest {
  return {
    idempotency_key: idempotencyKey,
    reason: d.reason.trim(),
    lines: [
      {
        sale_line_id: d.saleLineId.trim(),
        quantity: parseQuantity(d.quantity) ?? 0,
      },
    ],
  }
}
