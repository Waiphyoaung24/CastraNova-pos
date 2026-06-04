import { useRef } from "react"
import { useScanner } from "@/hooks/useScanner"

interface ScanInputProps {
  onScan: (code: string) => void
  placeholder?: string
  autoFocus?: boolean
}

/** Primary scan path: a focused input fed by a keyboard-wedge BT scanner. Clears
 * itself after each committed scan so the next code can be scanned immediately. */
export function ScanInput({
  onScan,
  placeholder = "Scan barcode…",
  autoFocus = true,
}: ScanInputProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const { onKeyDown } = useScanner({
    onScan: (code) => {
      onScan(code)
      if (inputRef.current) inputRef.current.value = ""
    },
  })

  return (
    <input
      ref={inputRef}
      type="text"
      inputMode="none"
      autoComplete="off"
      // biome-ignore lint/a11y/noAutofocus: scan screens must capture the wedge immediately
      autoFocus={autoFocus}
      onKeyDown={onKeyDown}
      placeholder={placeholder}
      aria-label="Scan barcode"
      className="w-full rounded-md border bg-background px-3 py-2 text-sm"
    />
  )
}
