import { Camera } from "lucide-react"
import { useEffect, useId, useRef, useState } from "react"

import { Button } from "@/components/ui/button"

interface CameraScanFallbackProps {
  onScan: (code: string) => void
}

/** Secondary scan path for when no BT wedge scanner is paired: an in-browser
 * camera scanner (html5-qrcode) that emits the same decoded code string. The
 * library is loaded dynamically so pages that never open the camera don't pay
 * its bundle cost. Slower than the wedge; not the primary path (spec §6.11). */
export function CameraScanFallback({ onScan }: CameraScanFallbackProps) {
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const readerId = useId().replace(/:/g, "")
  // The active scanner instance; typed loosely to avoid importing the library
  // eagerly just for its types.
  const scannerRef = useRef<{
    stop: () => Promise<unknown>
    clear: () => void
  }>(null)

  useEffect(() => {
    if (!open) return
    setError(null)
    let stopped = false

    import("html5-qrcode")
      .then(({ Html5Qrcode, Html5QrcodeSupportedFormats }) => {
        if (stopped) return
        const scanner = new Html5Qrcode(readerId, {
          formatsToSupport: [
            Html5QrcodeSupportedFormats.QR_CODE,
            Html5QrcodeSupportedFormats.CODE_128,
            Html5QrcodeSupportedFormats.CODE_39,
            Html5QrcodeSupportedFormats.EAN_13,
            Html5QrcodeSupportedFormats.EAN_8,
            Html5QrcodeSupportedFormats.UPC_A,
          ],
          // Prefer the native, faster BarcodeDetector API when the browser
          // supports it; html5-qrcode falls back to its own decoder otherwise.
          useBarCodeDetectorIfSupported: true,
          verbose: false,
        })
        scannerRef.current = scanner

        return scanner.start(
          { facingMode: "environment" },
          { fps: 10, qrbox: { width: 250, height: 250 } },
          (decodedText) => {
            if (stopped) return
            stopped = true
            onScan(decodedText)
            setOpen(false)
          },
          () => {
            // Per-frame decode failures are normal; ignore.
          },
        )
      })
      .catch(() => {
        if (!stopped) {
          setError("Camera unavailable. Check permissions or use the wedge.")
          setOpen(false)
        }
      })

    return () => {
      stopped = true
      const scanner = scannerRef.current
      scannerRef.current = null
      // stop() rejects if the camera never started; swallow either way.
      scanner
        ?.stop()
        .then(() => scanner.clear())
        .catch(() => undefined)
    }
  }, [open, readerId, onScan])

  return (
    <div className="space-y-2">
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => setOpen((v) => !v)}
      >
        <Camera className="size-4" aria-hidden="true" />
        {open ? "Close camera" : "Scan with camera"}
      </Button>
      {open && <div id={readerId} className="w-full max-w-xs" />}
      {error && <p className="text-destructive text-sm">{error}</p>}
    </div>
  )
}
