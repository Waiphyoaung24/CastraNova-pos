import type {
  AuditEntryPublic,
  AuditListAuditData,
  MovementType,
} from "@/client/types.gen"

// ---------------------------------------------------------------------------
// Pure helpers for the admin audit ledger (FR-019): map the filter form to the
// SDK query (dropping blanks), derive each movement's source, and roll the
// loaded page into headline figures. Framework-free so the screen stays thin.
// ---------------------------------------------------------------------------

export interface AuditFilter {
  eventType: string
  fromDate: string
  toDate: string
  /** UUID of a single acting user, or "" for all users. */
  actorUserId: string
  /** Product SKU to scope to (spans both ledgers), or "" for all. */
  sku: string
}

export function buildAuditQuery(f: AuditFilter): AuditListAuditData {
  const q: AuditListAuditData = {}
  if (f.eventType) q.eventType = f.eventType as MovementType
  if (f.fromDate) q.fromDate = f.fromDate
  if (f.toDate) q.toDate = f.toDate
  if (f.actorUserId) q.actorUserId = f.actorUserId
  if (f.sku) q.sku = f.sku
  return q
}

export type MovementSourceKind = "sale" | "ticket" | "pull" | "adjustment"

export interface MovementSource {
  kind: MovementSourceKind
  label: string
}

/**
 * What a movement was raised by, derived from the (mutually exclusive) source
 * IDs the audit row already carries. Returns null for a movement with no linked
 * source (e.g. a bare receipt).
 */
export function movementSource(
  e: Pick<
    AuditEntryPublic,
    "sale_id" | "service_ticket_id" | "project_pull_id" | "stock_adjustment_id"
  >,
): MovementSource | null {
  if (e.sale_id) return { kind: "sale", label: "Sale" }
  if (e.service_ticket_id) return { kind: "ticket", label: "Service ticket" }
  if (e.project_pull_id) return { kind: "pull", label: "Project pull" }
  if (e.stock_adjustment_id) return { kind: "adjustment", label: "Adjustment" }
  return null
}

export interface AuditSummary {
  total: number
  distinctActors: number
  /** RECEIVED movements (stock in). */
  received: number
  /** Every other movement type (stock out). */
  outflow: number
}

/**
 * Headline figures for the loaded page of audit rows. Counts are over what was
 * fetched (the endpoint returns the latest page), so the screen flags when the
 * page is full rather than implying an all-time total.
 */
export function summarizeAudit(
  rows: Pick<AuditEntryPublic, "actor_user_id" | "event_type">[],
): AuditSummary {
  const actors = new Set<string>()
  let received = 0
  for (const r of rows) {
    actors.add(r.actor_user_id)
    if (r.event_type === "RECEIVED") received += 1
  }
  return {
    total: rows.length,
    distinctActors: actors.size,
    received,
    outflow: rows.length - received,
  }
}
