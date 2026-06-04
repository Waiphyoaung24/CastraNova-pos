import { useEffect, useState } from "react"

/** Fixed banner shown while the browser is offline. Queued mutations replay on
 * reconnect (see query-client setMutationDefaults + resumePausedMutations). */
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

  if (online) return null

  return (
    <div className="fixed inset-x-0 bottom-0 z-50 bg-amber-500 px-4 py-2 text-center text-sm font-medium text-amber-950">
      Offline — changes are saved and will sync when you reconnect.
    </div>
  )
}
