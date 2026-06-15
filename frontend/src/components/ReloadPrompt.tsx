import { useRegisterSW } from "virtual:pwa-register/react"

/** Toast prompting a reload when a new service worker (app version) is ready.
 * registerType is 'autoUpdate', so this is a courtesy prompt for in-session updates. */
export function ReloadPrompt() {
  const {
    needRefresh: [needRefresh, setNeedRefresh],
    updateServiceWorker,
  } = useRegisterSW()

  const close = () => {
    setNeedRefresh(false)
  }

  if (!needRefresh) return null

  return (
    <div className="fixed right-4 bottom-4 z-50 rounded-md border bg-background p-4 shadow-lg">
      <div className="mb-2 text-sm">New version available.</div>
      <div className="flex gap-2">
        {needRefresh && (
          <button
            type="button"
            className="rounded bg-primary px-3 py-1 text-sm text-primary-foreground"
            onClick={() => updateServiceWorker(true)}
          >
            Reload
          </button>
        )}
        <button
          type="button"
          className="rounded border px-3 py-1 text-sm"
          onClick={close}
        >
          Close
        </button>
      </div>
    </div>
  )
}
