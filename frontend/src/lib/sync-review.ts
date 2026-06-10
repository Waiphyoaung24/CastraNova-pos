import type { SyncReviewState } from "@/client/types.gen"

// ---------------------------------------------------------------------------
// Pure helper for the admin sync-review queue (§6.7). Only PENDING items are
// actionable (mirrors the backend resolve guard).
// ---------------------------------------------------------------------------

export function isResolvable(state: SyncReviewState): boolean {
  return state === "PENDING"
}
