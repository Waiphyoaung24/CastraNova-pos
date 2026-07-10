import { createAsyncStoragePersister } from "@tanstack/query-async-storage-persister"
import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query"
import { del, get, set } from "idb-keyval"
import {
  ApiError,
  ReceiptsService,
  type ReceiveSerializedRequest,
  type SaleCreateRequest,
  SalesService,
} from "@/client"
import { endSession } from "./auth-session"

const handleApiError = (error: Error) => {
  // By the time a 401 reaches here, the request-boundary interceptor has
  // already attempted a refresh and failed — so the session is genuinely dead.
  // 403 = authenticated but under-privileged (e.g. staff hitting an admin
  // route); never log those out.
  if (error instanceof ApiError && error.status === 401) {
    endSession()
  }
}

export const queryClient = new QueryClient({
  defaultOptions: {
    // 24h cache so persisted queries survive an offline reload.
    queries: { gcTime: 1000 * 60 * 60 * 24 },
  },
  queryCache: new QueryCache({ onError: handleApiError }),
  mutationCache: new MutationCache({ onError: handleApiError }),
})

// idb-keyval's get/set/del match the async-storage interface (key) / (key, value)
// / (key); storing the client in IndexedDB keeps queued mutations across reloads.
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
