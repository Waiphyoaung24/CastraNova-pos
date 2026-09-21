import { ApiError } from "@/client"
import type {
  ProjectPullReturnCreate,
  ReturnablePullsPublic,
  ReturnableSalesPublic,
  SaleReturnCreateRequest,
} from "@/client/types.gen"
import { extractErrorMessage } from "@/utils"

// ---------------------------------------------------------------------------
// Pure form logic for recording a sale return from the Returns screen
// (design 2026-07-25). Mirrors the backend guards so the UI never POSTs a body
// the server will reject:
//   - a sale line must be picked
//   - quantity is a positive integer, capped at what is still returnable
//   - a reason is required for a sale return; a project-pull return has none
// The refund is NOT part of the draft: it is fixed at the original sale price
// and is display-only.
// ---------------------------------------------------------------------------

export interface ReturnDraft {
  /** Where the stock is coming back from. */
  source: "sale" | "pull"
  saleId: string
  pullId: string
  /** sale_line_id (sale) or pull line_id (pull) — the picker's line. */
  saleLineId: string
  /** Positive integer as typed; parsed at submit. */
  quantity: string
  /** Required for a sale return; a pull return has no reason field. */
  reason: string
}

export const emptyReturnDraft: ReturnDraft = {
  source: "sale",
  saleId: "",
  pullId: "",
  saleLineId: "",
  quantity: "1",
  reason: "",
}

export interface PickerOption {
  /** "sale:<sale_line_id>" | "pull:<line_id>" */
  value: string
  label: string
  source: "sale" | "pull"
  saleId?: string
  pullId?: string
  lineId: string
  quantityReturnable: number
  unitPriceThb?: string
  /** Sort key: when the sale/pull was made. */
  at: string
}

/** One list for the picker: sales and project requests, newest first. */
export function pickerOptions(
  sales: ReturnableSalesPublic | undefined,
  pulls: ReturnablePullsPublic | undefined,
): PickerOption[] {
  const day = (iso: string) => new Date(iso).toLocaleDateString()
  const fromSales: PickerOption[] = (sales?.sales ?? []).flatMap((s) =>
    s.lines.map((l) => ({
      value: `sale:${l.sale_line_id}`,
      label: `${day(s.sold_at)} · ${s.customer_name} · ${l.quantity_returnable} of ${l.quantity_sold} returnable`,
      source: "sale" as const,
      saleId: s.sale_id,
      lineId: l.sale_line_id,
      quantityReturnable: l.quantity_returnable,
      unitPriceThb: l.unit_price_thb,
      at: s.sold_at,
    })),
  )
  const fromPulls: PickerOption[] = (pulls?.pulls ?? []).flatMap((p) =>
    p.lines.map((l) => ({
      value: `pull:${l.line_id}`,
      label: `${day(p.created_at)} · ${p.project_name} (${p.project_code}) · ${p.customer_name} · ${l.quantity_returnable} of ${l.quantity_out} returnable`,
      source: "pull" as const,
      pullId: p.pull_id,
      lineId: l.line_id,
      quantityReturnable: l.quantity_returnable,
      at: p.created_at,
    })),
  )
  return [...fromSales, ...fromPulls].sort((a, b) => b.at.localeCompare(a.at))
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
  if (d.source === "sale" && d.reason.trim() === "") return false
  const qty = parseQuantity(d.quantity)
  if (qty === null) return false
  return qty <= maxQuantity
}

/**
 * What the Returns page shows when the returnable-sales lookup fails. The
 * only 404 the endpoint raises is "Product not found" (unknown SKU); every
 * other API error carries a user-actionable server reason.
 */
export function lookupErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    return err.status === 404
      ? "No product with this SKU."
      : extractErrorMessage(err)
  }
  return "Could not look up returnable sales."
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

export function buildPullReturnPayload(
  d: ReturnDraft,
  idempotencyKey: string,
): ProjectPullReturnCreate {
  return {
    idempotency_key: idempotencyKey,
    lines: [
      {
        line_id: d.saleLineId.trim(),
        quantity: parseQuantity(d.quantity) ?? 0,
      },
    ],
  }
}
