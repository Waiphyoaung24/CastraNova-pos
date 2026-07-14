import type {
  SyncReviewItemCreate,
  SyncReviewReason,
} from "../client/types.gen"

// Pure, runtime-import-free producer logic for the offline sync-review queue.
// The runtime wiring (posting, cache scanning, the queued() factory) lives in
// query-client.ts; keeping this module type-only lets its unit spec load in
// node the same way receive-form.spec.ts does.

/** Offline queue is capped at 7 days (PRD §8.3). */
export const SYNC_STALE_MS = 7 * 24 * 60 * 60 * 1000

/** Hidden metadata carried with a queued mutation; never sent to the server. */
export type QueueMeta = {
  submittedAt: number
  queuedOffline: boolean
  idempotencyKey: string
}

/** A queued mutation's variables: the real request body plus hidden metadata. */
export type Queued<TBody> = { body: TBody; meta: QueueMeta }

export function isStale(submittedAt: number | undefined, now: number): boolean {
  return typeof submittedAt === "number" && now - submittedAt > SYNC_STALE_MS
}

/** Build the ingest payload from a mutation's key + queued variables. */
export function buildSyncReviewItem(
  mutationKey: readonly unknown[] | undefined,
  variables: Queued<unknown> | undefined,
  reason: SyncReviewReason,
): SyncReviewItemCreate | null {
  const meta = variables?.meta
  const kind =
    mutationKey && mutationKey.length > 0 ? String(mutationKey[0]) : ""
  if (!meta || kind === "") return null
  return {
    idempotency_key: meta.idempotencyKey,
    mutation_kind: kind,
    payload: (variables?.body ?? {}) as { [key: string]: unknown },
    reason,
  }
}

/** A STALE review item for a paused mutation past the cap, else null. */
export function staleItemFor(
  isPaused: boolean,
  mutationKey: readonly unknown[] | undefined,
  variables: Queued<unknown> | undefined,
  now: number,
): SyncReviewItemCreate | null {
  if (!isPaused) return null
  if (!isStale(variables?.meta?.submittedAt, now)) return null
  return buildSyncReviewItem(mutationKey, variables, "STALE")
}

/** Only an offline-origin 409 (a lost write-conflict on replay) diverts. */
export function shouldDivertConflict(
  status: number,
  meta: QueueMeta | undefined,
): boolean {
  return status === 409 && meta?.queuedOffline === true
}
