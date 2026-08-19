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

/** Print-label control for serialized units and quantity SKUs.
 *
 * A serialized unit is a single unique item, so exactly one label can ever be
 * printed for it — the "unit" target shows just a print button. A "sku" target
 * is a shelf label printed in bulk, so it gets a quantity input (1–1000)
 * alongside the button. The button opens the label PDF in a new tab; both
 * encode a QR (unit barcode / product sku) the in-app scanner resolves. While
 * the PDF is in flight the control disables and reads "Opening…", preventing a
 * double-click from spawning two tabs.
 *
 * `defaultQty` seeds the SKU quantity input on mount only; to reset it for a
 * different target (e.g. a newly received batch), give the element a changing
 * `key` so React remounts it. */
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

  const isUnit = target.kind === "unit"
  const what = isUnit ? `serial ${target.serial}` : `SKU ${target.sku}`

  async function handlePrint() {
    let n = 1
    if (target.kind === "sku") {
      n = Number(qty)
      if (!Number.isInteger(n) || n < 1 || n > 1000) {
        showErrorToast("Enter a quantity between 1 and 1000.")
        return
      }
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
      {isUnit ? null : (
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
      )}
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="h-11"
        aria-label={
          isUnit ? `Print label for ${what}` : `Print labels for ${what}`
        }
        disabled={isOpening}
        onClick={handlePrint}
      >
        <Printer className="size-4" />
        {isOpening ? "Opening…" : isUnit ? "Print label" : "Print labels"}
      </Button>
    </div>
  )
}
