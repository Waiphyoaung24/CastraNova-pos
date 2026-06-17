import { Bluetooth, ScanLine } from "lucide-react"
import {
  forwardRef,
  type ReactNode,
  useCallback,
  useId,
  useImperativeHandle,
  useRef,
  useState,
} from "react"

import { CameraScanFallback } from "@/components/CameraScanFallback"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useBluetoothScanner } from "@/hooks/useScannerConfig"

export interface ScanFieldHandle {
  focus: () => void
}

interface ScanFieldProps {
  /** Fires on a completed scan/submit: wedge Enter, manual Enter, camera
   * decode, or the submit button. Receives the trimmed code. */
  onScan: (code: string) => void
  /** Associates the input with an external <Label htmlFor>. */
  id?: string
  /** Optional caption rendered above the input (with a scan icon). */
  label?: string
  /** Accessible name when there is no visible `label` / external label. */
  ariaLabel?: string
  placeholder?: string
  /** Controlled value (forms). Omit for an uncontrolled field. */
  value?: string
  onValueChange?: (value: string) => void
  /** Clear and refocus the field after each scan (rapid-scan flows). */
  clearOnScan?: boolean
  /** Override the device config: allow the on-screen keyboard. Defaults to
   * "no Bluetooth scanner connected" from {@link useBluetoothScanner}. */
  allowKeyboard?: boolean
  /** Renders a submit button with this label (e.g. "Search"). */
  submitLabel?: string
  /** Show the "Scan with camera" fallback. Default true. */
  camera?: boolean
  autoFocus?: boolean
  /** Optional status node rendered below (callers wire their own aria-live). */
  status?: ReactNode
  disabled?: boolean
  /** Show the device scanner config toggle. Default true. */
  showConfig?: boolean
}

/**
 * Reusable scan layout: a single field staff can type into, scan with a
 * Bluetooth/HID wedge, or scan with the camera. Typing-first — a normal input
 * whose value is the source of truth; Enter / the submit button / a camera
 * decode all commit via `onScan`. Wedge scanners work because they type fast
 * and terminate with Enter.
 */
export const ScanField = forwardRef<ScanFieldHandle, ScanFieldProps>(
  function ScanField(
    {
      onScan,
      id,
      label,
      ariaLabel,
      placeholder = "Scan or type a barcode…",
      value,
      onValueChange,
      clearOnScan = false,
      allowKeyboard,
      submitLabel,
      camera = true,
      autoFocus = true,
      status,
      disabled = false,
      showConfig = true,
    },
    ref,
  ) {
    const inputRef = useRef<HTMLInputElement>(null)
    const generatedId = useId()
    const inputId = id ?? generatedId
    const [internal, setInternal] = useState("")
    const [bluetoothConnected] = useBluetoothScanner()

    const isControlled = value !== undefined
    const current = isControlled ? value : internal
    // When a wedge is paired, suppress the soft keyboard so it doesn't pop on
    // tablets; physical typing and the wedge still work.
    const keyboardAllowed = allowKeyboard ?? !bluetoothConnected

    useImperativeHandle(ref, () => ({
      focus: () => inputRef.current?.focus(),
    }))

    const setCurrent = (next: string) => {
      if (!isControlled) setInternal(next)
      onValueChange?.(next)
    }

    const submit = (raw: string) => {
      const code = raw.trim()
      if (code === "") return
      onScan(code)
      if (clearOnScan) {
        setCurrent("")
        inputRef.current?.focus()
      }
    }

    // Stable handler for the camera so an open scanner isn't torn down and
    // restarted on every parent re-render (e.g. Sale's query polling).
    const submitRef = useRef(submit)
    submitRef.current = submit
    const handleCameraScan = useCallback(
      (code: string) => submitRef.current(code),
      [],
    )

    return (
      <div className="space-y-2">
        {label ? (
          <p className="flex items-center gap-2 text-sm font-medium">
            <ScanLine
              className="text-muted-foreground size-4"
              aria-hidden="true"
            />
            {label}
          </p>
        ) : null}

        <div className="flex gap-2">
          <Input
            ref={inputRef}
            id={inputId}
            type="text"
            inputMode={keyboardAllowed ? "text" : "none"}
            autoComplete="off"
            autoFocus={autoFocus}
            aria-label={label ? undefined : (ariaLabel ?? "Scan barcode")}
            disabled={disabled}
            placeholder={placeholder}
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                // Stop the wedge's CR from submitting a surrounding form.
                e.preventDefault()
                submit(current)
              }
            }}
            className="w-full sm:w-80"
          />
          {submitLabel ? (
            <Button
              type="button"
              disabled={disabled || current.trim() === ""}
              onClick={() => submit(current)}
            >
              {submitLabel}
            </Button>
          ) : null}
        </div>

        {camera || showConfig ? (
          <div className="flex flex-wrap items-center gap-3">
            {camera ? <CameraScanFallback onScan={handleCameraScan} /> : null}
            {showConfig ? <ScannerConfigToggle /> : null}
          </div>
        ) : null}

        {status}
      </div>
    )
  },
)

/** Device-local toggle: "is a Bluetooth scanner paired to this station?". */
function ScannerConfigToggle() {
  const [connected, setConnected] = useBluetoothScanner()
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      aria-pressed={connected}
      onClick={() => setConnected(!connected)}
      className="text-muted-foreground"
      title="Toggle whether a Bluetooth/HID scanner is paired to this device"
    >
      <Bluetooth
        className={connected ? "size-4 text-primary" : "size-4"}
        aria-hidden="true"
      />
      Bluetooth scanner: {connected ? "On" : "Off"}
    </Button>
  )
}
