import { Printer } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import useCustomToast from "@/hooks/useCustomToast"
import { openAuthedPdf } from "@/lib/print-pdf"

/** What to print: a serialized unit's label or a product's SKU label. */
export type PrintLabelTarget =
  | { kind: "unit"; unitId: string; serial: string }
  | { kind: "sku"; productId: string; sku: string }

/** Identical print-label control for serialized units and quantity SKUs.
 *
 * A quantity input (1–1000) + a print button that opens an N-copy label PDF in
 * a new tab. Serialized → the unit-label endpoint; quantity → the SKU-label
 * endpoint. Both encode a QR (unit barcode / product sku) the in-app scanner
 * resolves. While the PDF is in flight the control disables and reads
 * "Opening…", preventing a double-click from spawning two tabs.
 *
 * `defaultQty` seeds the input on mount only; to reset it for a different
 * target (e.g. a newly received batch), give the element a changing `key` so
 * React remounts it. */
export function PrintLabelButton({
  target,
  defaultQty = 1,
}: {
  target: PrintLabelTarget
  defaultQty?: number
}) {
  const { showErrorToast } = useCustomToast()
  const [qty, setQty] = useState(String(defaultQty))
  const [isOpening, setIsOpening] = useState(false)

  const what =
    target.kind === "unit" ? `serial ${target.serial}` : `SKU ${target.sku}`

  async function handlePrint() {
    const n = Number(qty)
    if (!Number.isInteger(n) || n < 1 || n > 1000) {
      showErrorToast("Enter a quantity between 1 and 1000.")
      return
    }
    const path =
      target.kind === "unit"
        ? `/receipts/serialized/${target.unitId}/label.pdf?qty=${n}`
        : `/products/${target.productId}/label.pdf?qty=${n}`
    setIsOpening(true)
    const result = await openAuthedPdf(path)
    setIsOpening(false)
    if (result === "no-token") {
      showErrorToast("Session expired. Please log in again.")
    } else if (result === "popup-blocked") {
      showErrorToast("Pop-up blocked. Allow pop-ups and try again.")
    } else if (result === "fetch-failed") {
      showErrorToast("Could not load label PDF.")
    }
  }

  return (
    <div className="flex items-center gap-2">
      <Input
        type="number"
        inputMode="numeric"
        min={1}
        max={1000}
        placeholder="1"
        value={qty}
        onChange={(e) => setQty(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault()
            handlePrint()
          }
        }}
        className="num h-11 w-20"
        aria-label={`Number of labels for ${what}`}
        disabled={isOpening}
      />
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="h-11"
        aria-label={`Print labels for ${what}`}
        disabled={isOpening}
        onClick={handlePrint}
      >
        <Printer className="size-4" />
        {isOpening ? "Opening…" : "Print labels"}
      </Button>
    </div>
  )
}
