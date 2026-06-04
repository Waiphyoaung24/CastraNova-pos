import { useCallback, useRef } from "react"

/**
 * Keyboard-wedge barcode scanners (e.g. TYSSO BCP-2DC, Posiflex CD-3870) type the
 * decoded code into the focused input as fast keystrokes terminated by Enter (CR).
 * We buffer keystrokes and commit ONLY on the CR terminator, and reset the buffer
 * when the inter-key gap is too large — that drops stray/human keystrokes so they
 * don't get prepended to the next scan burst.
 */

export interface ScanBufferState {
  buffer: string
  lastKeyAt: number
}

export interface ScanKeyOptions {
  minLength: number
  interKeyTimeoutMs: number
}

export const initialScanState: ScanBufferState = { buffer: "", lastKeyAt: 0 }

/**
 * Pure transition for one keystroke. Returns the next buffer state and, when the
 * CR terminator commits a long-enough code, the `emit` string. Kept pure so the
 * wedge behaviour can be tested without a DOM.
 */
export function feedScanKey(
  state: ScanBufferState,
  key: string,
  now: number,
  opts: ScanKeyOptions,
): { state: ScanBufferState; emit?: string } {
  if (key === "Enter") {
    const code = state.buffer
    const next = { buffer: "", lastKeyAt: now }
    if (code.length >= opts.minLength) {
      return { state: next, emit: code }
    }
    return { state: next }
  }
  // Only single printable characters extend the buffer; modifiers are ignored.
  if (key.length !== 1) {
    return { state }
  }
  const gapTooLarge = now - state.lastKeyAt > opts.interKeyTimeoutMs
  const base = gapTooLarge ? "" : state.buffer
  return { state: { buffer: base + key, lastKeyAt: now } }
}

export interface UseScannerOptions {
  onScan: (code: string) => void
  minLength?: number
  interKeyTimeoutMs?: number
}

/** Returns an `onKeyDown` handler to attach to the focused scan input. */
export function useScanner({
  onScan,
  minLength = 3,
  interKeyTimeoutMs = 50,
}: UseScannerOptions) {
  const stateRef = useRef<ScanBufferState>(initialScanState)

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      const { state, emit } = feedScanKey(
        stateRef.current,
        e.key,
        performance.now(),
        { minLength, interKeyTimeoutMs },
      )
      stateRef.current = state
      if (e.key === "Enter") {
        // Stop the CR from submitting a surrounding form.
        e.preventDefault()
      }
      if (emit !== undefined) {
        onScan(emit)
      }
    },
    [onScan, minLength, interKeyTimeoutMs],
  )

  return { onKeyDown }
}
