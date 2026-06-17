import { useSyncExternalStore } from "react"

/**
 * Device-local scanner configuration. Whether a Bluetooth/HID wedge scanner is
 * paired to THIS station is a per-device fact, so it lives in localStorage (not
 * the backend) and is shared across every ScanField via a tiny external store.
 *
 * When `true`, scan fields suppress the on-screen keyboard (inputMode="none")
 * and keep focus for the wedge. When `false` (default), the soft keyboard is
 * available so staff on tablets/phones can type manually. Either way a wedge
 * still works — it just types fast and terminates with Enter.
 */
const KEY = "castranova:scanner:bluetooth"

type Listener = () => void
const listeners = new Set<Listener>()

function read(): boolean {
  if (typeof window === "undefined") return false
  return window.localStorage.getItem(KEY) === "1"
}

let cache = read()

if (typeof window !== "undefined") {
  // Sync across tabs/windows on the same device.
  window.addEventListener("storage", (e) => {
    if (e.key === KEY) {
      cache = read()
      for (const l of listeners) l()
    }
  })
}

function subscribe(listener: Listener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function getSnapshot(): boolean {
  return cache
}

export function setBluetoothScanner(connected: boolean): void {
  if (typeof window !== "undefined") {
    window.localStorage.setItem(KEY, connected ? "1" : "0")
  }
  cache = connected
  for (const l of listeners) l()
}

/** Returns `[bluetoothConnected, setBluetoothConnected]`. */
export function useBluetoothScanner(): readonly [
  boolean,
  (v: boolean) => void,
] {
  const connected = useSyncExternalStore(subscribe, getSnapshot, () => false)
  return [connected, setBluetoothScanner] as const
}
