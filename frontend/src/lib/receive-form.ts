import type {
  ReceiveQuantityRequest,
  ReceiveSerializedRequest,
} from "../client/types.gen"
import { todayISO } from "./date-field"

// Pure, React-free form logic for the Receive screen (Task 4.1).
// Costs stay as strings end-to-end (money-boundary discipline); they are only
// parsed at the Number() validation boundary. The backend coerces the string
// cost into a Decimal, so request builders pass it through untouched.

/** In-progress row of the serialized-receive form. `key` is a stable local id. */
export type DraftPiece = {
  key: string
  supplierSerial: string
  purchaseCostThb: string
}

/** In-progress state of the quantity-receive form (all strings from inputs). */
export type QuantityDraft = {
  productId: string
  supplierId: string
  receivedQty: string
  purchaseCostThb: string
  supplierBatchRef: string
  expectedQty: string
  note: string
  receivedDate: string
}

// ---------------------------------------------------------------------------
// Receive date
// ---------------------------------------------------------------------------

// `todayISO` lives in `date-field.ts` now — a generic date module must not
// depend on a receive-form module. Re-exported so `receive.tsx` and
// `receive-form.test.ts` keep importing it from here.
export { todayISO }

/** A well-formed, non-future receive date. ISO dates compare correctly as
 * strings, so no Date parsing is needed. The server re-checks this — the guard
 * here only stops an obviously-bad submit. */
export function isValidReceivedDate(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && value <= todayISO()
}

// ---------------------------------------------------------------------------
// Serialized piece list — immutable mutations
// ---------------------------------------------------------------------------

export function addPiece(
  pieces: DraftPiece[],
  piece: DraftPiece,
): DraftPiece[] {
  return [...pieces, piece]
}

export function removePiece(pieces: DraftPiece[], key: string): DraftPiece[] {
  return pieces.filter((p) => p.key !== key)
}

export function updatePiece(
  pieces: DraftPiece[],
  key: string,
  patch: Partial<Omit<DraftPiece, "key">>,
): DraftPiece[] {
  return pieces.map((p) => (p.key === key ? { ...p, ...patch } : p))
}

// ---------------------------------------------------------------------------
// Request builders (boundary to the SDK shapes)
// ---------------------------------------------------------------------------

export function buildReceiveSerializedRequest(
  pieces: DraftPiece[],
  productId: string,
  supplierId: string,
  idempotencyKey: string,
  receivedDate: string,
): ReceiveSerializedRequest {
  return {
    product_id: productId,
    supplier_id: supplierId,
    pieces: pieces.map((p) => ({
      supplier_serial: p.supplierSerial.trim(),
      purchase_cost_thb: p.purchaseCostThb.trim(),
    })),
    idempotency_key: idempotencyKey,
    received_date: receivedDate,
  }
}

export function buildReceiveQuantityRequest(
  draft: QuantityDraft,
  idempotencyKey: string,
): ReceiveQuantityRequest {
  return {
    product_id: draft.productId,
    supplier_id: draft.supplierId,
    received_qty: Number(draft.receivedQty),
    purchase_cost_thb: draft.purchaseCostThb.trim(),
    supplier_batch_ref: draft.supplierBatchRef.trim() || null,
    expected_qty:
      draft.expectedQty.trim() !== "" ? Number(draft.expectedQty.trim()) : null,
    note: draft.note.trim() || null,
    idempotency_key: idempotencyKey,
    received_date: draft.receivedDate,
  }
}

// ---------------------------------------------------------------------------
// Submit guards
// ---------------------------------------------------------------------------

function isPositiveCost(value: string): boolean {
  const n = Number(value)
  return Number.isFinite(n) && n > 0
}

export function canSubmitSerialized(
  pieces: DraftPiece[],
  productId: string,
  supplierId: string,
  receivedDate: string,
): boolean {
  return (
    Boolean(productId) &&
    Boolean(supplierId) &&
    isValidReceivedDate(receivedDate) &&
    pieces.length >= 1 &&
    pieces.every(
      (p) =>
        p.supplierSerial.trim().length > 0 && isPositiveCost(p.purchaseCostThb),
    )
  )
}

export function canSubmitQuantity(draft: QuantityDraft): boolean {
  const qty = Number(draft.receivedQty)
  return (
    Boolean(draft.productId) &&
    Boolean(draft.supplierId) &&
    isValidReceivedDate(draft.receivedDate) &&
    Number.isInteger(qty) &&
    qty >= 1 &&
    isPositiveCost(draft.purchaseCostThb)
  )
}
