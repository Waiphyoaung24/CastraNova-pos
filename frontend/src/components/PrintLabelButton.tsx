import { Printer } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import useCustomToast from "@/hooks/useCustomToast"

/** Opens a serialized unit's QR label PDF in a new tab.
 *
 * The label is an authed binary download the generated SDK types as `unknown`,
 * so this is a sanctioned bare fetch (the only authed binary download in the
 * app) that attaches the bearer token by hand. Shared by Receive (label a
 * freshly received unit) and Stock (reprint an in-stock unit's lost label).
 *
 * While the PDF is in flight the button disables and reads "Opening…" — this
 * gives feedback on the async fetch and stops a double-click from spawning two
 * fetches / two tabs. */
export function PrintLabelButton({
  unitId,
  serial,
}: {
  unitId: string
  serial: string
}) {
  const { showErrorToast } = useCustomToast()
  const objectUrlRef = useRef<string | null>(null)
  const [isOpening, setIsOpening] = useState(false)

  useEffect(() => {
    return () => {
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current)
    }
  }, [])

  async function handlePrint() {
    const token = localStorage.getItem("access_token")
    if (!token) {
      showErrorToast("Session expired. Please log in again.")
      return
    }
    setIsOpening(true)
    try {
      const res = await fetch(
        `${import.meta.env.VITE_API_URL}/api/v1/receipts/serialized/${unitId}/label.pdf`,
        { headers: { Authorization: `Bearer ${token}` } },
      )
      if (!res.ok) {
        showErrorToast("Could not load label PDF.")
        return
      }
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current)
      const url = URL.createObjectURL(await res.blob())
      objectUrlRef.current = url
      const win = window.open(url, "_blank", "noopener,noreferrer")
      if (!win) {
        showErrorToast("Pop-up blocked. Allow pop-ups and try again.")
        URL.revokeObjectURL(url)
        objectUrlRef.current = null
        return
      }
    } catch {
      showErrorToast("Could not load label PDF.")
    } finally {
      setIsOpening(false)
    }
  }

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className="h-11"
      aria-label={`Print label for serial ${serial}`}
      disabled={isOpening}
      onClick={handlePrint}
    >
      <Printer className="size-4" />
      {isOpening ? "Opening…" : "Print label"}
    </Button>
  )
}
