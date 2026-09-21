import { FileText } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import useCustomToast from "@/hooks/useCustomToast"
import { openAuthedPdf } from "@/lib/print-pdf"

/** The API path (after /api/v1) of a sale's invoice PDF. */
export function invoicePath(saleId: string): string {
  return `/sales/${saleId}/receipt.pdf`
}

/** Opens a sale's invoice PDF in a new tab (staff + admin). Same authed-PDF
 * path as label printing; disabled while the PDF is in flight so a double
 * click cannot open two tabs. */
export function DownloadInvoiceButton({
  saleId,
  size = "sm",
}: {
  saleId: string
  size?: "sm" | "default"
}) {
  const { showErrorToast } = useCustomToast()
  const [isOpening, setIsOpening] = useState(false)

  async function handleOpen() {
    setIsOpening(true)
    const result = await openAuthedPdf(invoicePath(saleId))
    setIsOpening(false)
    if (result === "no-token") {
      showErrorToast("Session expired. Please log in again.")
    } else if (result === "popup-blocked") {
      showErrorToast("Pop-up blocked. Allow pop-ups and try again.")
    } else if (result === "fetch-failed") {
      showErrorToast("Could not load the invoice PDF.")
    }
  }

  return (
    <Button
      type="button"
      variant="outline"
      size={size}
      disabled={isOpening}
      onClick={handleOpen}
    >
      <FileText />
      {isOpening ? "Opening…" : "Download invoice"}
    </Button>
  )
}
