import { Html5Qrcode, Html5QrcodeSupportedFormats } from "html5-qrcode"
import { useEffect, useId, useRef, useState } from "react"

interface CameraScanFallbackProps {
  onScan: (code: string) => void
}

/** Secondary scan path for when no BT wedge scanner is paired: an in-browser
 * camera scanner (html5-qrcode) that emits the same decoded code string. Slower
 * than the wedge; not the primary path (spec §6.11). */
export function CameraScanFallback({ onScan }: CameraScanFallbackProps) {
  const [open, setOpen] = useState(false)
  const readerId = useId().replace(/:/g, "")
  const scannerRef = useRef<Html5Qrcode | null>(null)

  useEffect(() => {
    if (!open) return
    const scanner = new Html5Qrcode(readerId, {
      formatsToSupport: [
        Html5QrcodeSupportedFormats.QR_CODE,
        Html5QrcodeSupportedFormats.CODE_128,
      ],
      verbose: false,
    })
    scannerRef.current = scanner
    let stopped = false

    scanner
      .start(
        { facingMode: "environment" },
        { fps: 10, qrbox: 250 },
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
      .catch(() => setOpen(false))

    return () => {
      stopped = true
      // stop() rejects if the camera never started; swallow either way.
      scanner
        .stop()
        .then(() => scanner.clear())
        .catch(() => undefined)
    }
  }, [open, readerId, onScan])

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="rounded-md border px-3 py-2 text-sm"
      >
        {open ? "Close camera" : "Scan with camera"}
      </button>
      {open && <div id={readerId} className="w-full max-w-xs" />}
    </div>
  )
}
