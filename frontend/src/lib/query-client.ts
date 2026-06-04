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

const handleApiError = (error: Error) => {
  if (error instanceof ApiError && [401, 403].includes(error.status)) {
    localStorage.removeItem("access_token")
    window.location.href = "/login"
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
