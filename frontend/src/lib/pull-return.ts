import type {
  ProjectPullLinePublic,
  ProjectPullPublic,
  ProjectPullReturnCreate,
} from "@/client/types.gen"

// line_id -> qty to put back into stock. The server re-checks every cap under
// a lock; clamping here only keeps the steppers honest. No cost in here.
export type ReturnDraft = Record<string, number>

/** A waiting pull is undone with Cancel; a settled one returns what's still out. */
export function canReturnPull(pull: ProjectPullPublic): boolean {
  return (
    pull.state !== "PENDING" &&
    pull.lines.some((l) => (l.returnable_qty ?? 0) > 0)
  )
}

/** Set a line's return qty, clamped to [0, returnable_qty], floored. */
export function setReturnQty(
  draft: ReturnDraft,
  line: ProjectPullLinePublic,
  qty: number,
): ReturnDraft {
  const clamped = Math.max(
    0,
    Math.min(
      line.returnable_qty ?? 0,
      Math.floor(Number.isFinite(qty) ? qty : 0),
    ),
  )
  return { ...draft, [line.id]: clamped }
}

export function returnDraftTotal(draft: ReturnDraft): number {
  return Object.values(draft).reduce((sum, q) => sum + q, 0)
}

/** Zero lines are dropped — the API rejects quantity 0. */
export function buildPullReturnPayload(
  draft: ReturnDraft,
  idempotencyKey: string,
): ProjectPullReturnCreate {
  return {
    idempotency_key: idempotencyKey,
    lines: Object.entries(draft)
      .filter(([, quantity]) => quantity > 0)
      .map(([line_id, quantity]) => ({ line_id, quantity })),
  }
}
