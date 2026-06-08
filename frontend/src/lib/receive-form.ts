import type {
  ReceiveQuantityRequest,
  ReceiveSerializedRequest,
} from "../client/types.gen"

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
): ReceiveSerializedRequest {
  return {
    product_id: productId,
    supplier_id: supplierId,
    pieces: pieces.map((p) => ({
      supplier_serial: p.supplierSerial.trim(),
      purchase_cost_thb: p.purchaseCostThb,
    })),
    idempotency_key: idempotencyKey,
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
    purchase_cost_thb: draft.purchaseCostThb,
    supplier_batch_ref: draft.supplierBatchRef.trim() || null,
    expected_qty: draft.expectedQty ? Number(draft.expectedQty) : null,
    note: draft.note.trim() || null,
    idempotency_key: idempotencyKey,
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
): boolean {
  return (
    Boolean(productId) &&
    Boolean(supplierId) &&
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
    Number.isInteger(qty) &&
    qty >= 1 &&
    isPositiveCost(draft.purchaseCostThb)
  )
}
