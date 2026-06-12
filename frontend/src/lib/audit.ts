import type { AuditListAuditData, MovementType } from "@/client/types.gen"

// ---------------------------------------------------------------------------
// Pure helper for the admin audit ledger (FR-019): map the filter form to the
// SDK query, dropping blanks so an unset filter doesn't constrain the result.
// ---------------------------------------------------------------------------

export interface AuditFilter {
  eventType: string
  fromDate: string
  toDate: string
}

export function buildAuditQuery(f: AuditFilter): AuditListAuditData {
  const q: AuditListAuditData = {}
  if (f.eventType) q.eventType = f.eventType as MovementType
  if (f.fromDate) q.fromDate = f.fromDate
  if (f.toDate) q.toDate = f.toDate
  return q
}
