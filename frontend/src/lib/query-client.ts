import { createAsyncStoragePersister } from "@tanstack/query-async-storage-persister"
import {
  MutationCache,
  onlineManager,
  QueryCache,
  QueryClient,
} from "@tanstack/react-query"
import { del, get, set } from "idb-keyval"
import {
  ApiError,
  ReceiptsService,
  type ReceiveSerializedRequest,
  type SaleCreateRequest,
  SalesService,
  SyncReviewService,
} from "@/client"
import {
  buildSyncReviewItem,
  type Queued,
  shouldDivertConflict,
  staleItemFor,
} from "./sync-producer"

/** Wrap a request body with hidden offline-queue metadata (stripped before the
 *  server call by the registered mutationFn). `idempotencyKey` reuses the
 *  action's own key where it has one; pull-fulfill passes a generated one. */
export function queued<TBody>(
  body: TBody,
  idempotencyKey: string,
): Queued<TBody> {
  return {
    body,
    meta: {
      submittedAt: Date.now(),
      queuedOffline: !onlineManager.isOnline(),
      idempotencyKey,
    },
  }
}

const endSession = () => {
  localStorage.removeItem("access_token")
  window.location.href = "/login"
}

// Best-effort: a failed divert must never throw (it runs inside error handling
// and replay). Server ingest is idempotent on idempotency_key, so a dropped
// POST is safe to lose; log it and move on.
async function postSyncReviewItem(
  item: Parameters<
    typeof SyncReviewService.ingestSyncReviewItem
  >[0]["requestBody"],
): Promise<void> {
  try {
    await SyncReviewService.ingestSyncReviewItem({ requestBody: item })
  } catch (err) {
    console.error("sync-review ingest failed", err)
  }
}

// Queries: only 401 ends the session (unchanged behavior).
const handleQueryError = (error: Error) => {
  if (error instanceof ApiError && error.status === 401) endSession()
}

// Mutations: 401 ends the session; an offline-origin 409 on replay is diverted
// to the admin review queue as CONFLICT. A live (online) 409 falls through to
// the screen's own onError toast, unchanged.
const handleMutationError = (
  error: Error,
  variables: unknown,
  _context: unknown,
  mutation: { options: { mutationKey?: readonly unknown[] } },
) => {
  if (error instanceof ApiError && error.status === 401) {
    endSession()
    return
  }
  const vars = variables as Queued<unknown> | undefined
  if (
    error instanceof ApiError &&
    shouldDivertConflict(error.status, vars?.meta)
  ) {
    const item = buildSyncReviewItem(
      mutation.options.mutationKey,
      vars,
      "CONFLICT",
    )
    if (item) void postSyncReviewItem(item)
  }
}

export const queryClient = new QueryClient({
  defaultOptions: {
    // 24h cache so persisted queries survive an offline reload.
    queries: { gcTime: 1000 * 60 * 60 * 24 },
  },
  queryCache: new QueryCache({ onError: handleQueryError }),
  mutationCache: new MutationCache({ onError: handleMutationError }),
})

// Remove any paused mutation older than the 7-day cap BEFORE replay, so a
// forgotten device can never replay a stale action against current stock
// (PRD §8.3, primary guarantee). Record it for admin review (best-effort).
// Runs only when online — offline we can't post, and resume is a no-op anyway.
export function divertStaleMutations(now = Date.now()): void {
  if (!onlineManager.isOnline()) return
  const cache = queryClient.getMutationCache()
  for (const mutation of cache.getAll()) {
    const item = staleItemFor(
      mutation.state.isPaused,
      mutation.options.mutationKey,
      mutation.state.variables as Queued<unknown> | undefined,
      now,
    )
    if (!item) continue
    cache.remove(mutation)
    void postSyncReviewItem(item)
  }
}

// idb-keyval's get/set/del match the async-storage interface; storing the
// client in IndexedDB keeps queued mutations across reloads.
export const persister = createAsyncStoragePersister({
  storage: { getItem: get, setItem: set, removeItem: del },
})

// Paused (offline) mutations can't be serialized, so their fns must be
// re-registered by key for resumePausedMutations() to replay them after a
// reload. Every offline mutation carries a client idempotency_key, so the
// backend dedupes replays (no app-level encryption — S4).
queryClient.setMutationDefaults(["sales"], {
  mutationFn: (requestBody: SaleCreateRequest) =>
    SalesService.createSale({ requestBody }),
})
queryClient.setMutationDefaults(["receipts"], {
  mutationFn: (requestBody: ReceiveSerializedRequest) =>
    ReceiptsService.receiveSerialized({ requestBody }),
})
