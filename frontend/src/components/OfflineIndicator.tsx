import { useMutationState } from "@tanstack/react-query"
import { useEffect, useState } from "react"

/** Fixed banner shown while the browser is offline, with a queued-mutation
 * counter that drains as paused mutations replay on reconnect.
 *
 * - Uses `useMutationState` with `isPaused` predicate to count only mutations
 *   that are truly offline-queued (paused), not in-flight online ones.
 * - The `aria-live="polite"` region announces online/offline transitions and
 *   queue-count changes to screen readers without interrupting them. */
export function OfflineIndicator() {
  const [online, setOnline] = useState(
    typeof navigator === "undefined" ? true : navigator.onLine,
  )

  useEffect(() => {
    const goOnline = () => setOnline(true)
    const goOffline = () => setOnline(false)
    window.addEventListener("online", goOnline)
    window.addEventListener("offline", goOffline)
    return () => {
      window.removeEventListener("online", goOnline)
      window.removeEventListener("offline", goOffline)
    }
  }, [])

  // Count mutations that are PAUSED (offline-queued), not merely pending/in-flight.
  // isPaused is set by TanStack Query when a mutation is held back due to no network.
  const queuedCount = useMutationState({
    filters: { predicate: (m) => m.state.isPaused },
  }).length

  const showBanner = !online || queuedCount > 0

  if (!showBanner) return null

  const statusText = online
    ? `Syncing — ${queuedCount} ${queuedCount === 1 ? "change" : "changes"} uploading…`
    : queuedCount > 0
      ? `Offline — ${queuedCount} ${queuedCount === 1 ? "change" : "changes"} queued, will sync when you reconnect.`
      : "Offline — changes are saved and will sync when you reconnect."

  return (
    <output
      aria-live="polite"
      aria-atomic="true"
      className="fixed inset-x-0 bottom-0 z-50 bg-amber-500 px-4 py-2 text-center text-sm font-medium text-amber-950"
    >
      <span aria-hidden="true">{online ? "⟳" : "!"} </span>
      {statusText}
    </output>
  )
}
