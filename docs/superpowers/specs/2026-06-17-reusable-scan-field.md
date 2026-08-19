# Reusable Scan Field — Design

**Date:** 2026-06-17
**Status:** Implemented

## Understanding Summary

- **What:** one reusable `ScanField` component for type / Bluetooth-HID wedge / camera barcode entry, adopted on Search, Sale, Receive, and Stock Adjustment.
- **Why:** the scan UX was duplicated and inconsistent — Sale had the full layout; Search/Receive/Stock-Adjustment used bare inputs (Search had no scan affordance at all).
- **Who:** counter staff (desktop + HID scanner) and floor staff on tablets/phones (need soft keyboard + camera).
- **Constraints:** React + shadcn/ui + Tailwind v4, dark mode; data stays on TanStack Query + SDK; camera needs HTTPS in prod; no backend changes.
- **Non-goals:** new scan API, offline queueing, hardware-pairing UI.

## Assumptions

1. **Typing-first input.** Normal controlled input; Enter / submit button / camera decode all commit via `onScan`. Wedge scanners work because they type fast + Enter. This deliberately does **not** use the `useScanner` keystroke buffer (which dropped stray keys but broke slow human typing).
2. Camera is opt-in and **lazy-loaded** (`import("html5-qrcode")`).
3. `ScanInput`/`useScanner` stay — still used by tickets, pulls, and pull panels (so not orphaned).

## Decision Log

| Decision | Alternatives | Why |
|---|---|---|
| Single `ScanField` for the 4 pages | Per-page inputs | One source of truth |
| Normal input + submit-on-Enter | Keep wedge keystroke buffer | Buffer breaks manual typing; user wants type-or-scan |
| Bluetooth-connected config in localStorage (`useScannerConfig`) | Backend SystemSetting | Per-device fact; no backend change |
| Config drives `inputMode` (none when connected) | Always allow soft keyboard | Suppress soft keyboard for wedge stations, allow it on tablets |
| Camera: BarcodeDetector + retail formats + lazy import | Keep QR+CODE_128 static | Real barcodes need EAN/UPC; native API faster; bundle cost |
| Stable camera handler via ref | Pass `submit` directly | Avoid camera restart on parent re-render |

## Final Design

- **`src/hooks/useScannerConfig.ts`** — `useBluetoothScanner()` returns `[connected, setConnected]`, backed by `localStorage` (`castranova:scanner:bluetooth`) via `useSyncExternalStore`; syncs across tabs.
- **`src/components/ScanField.tsx`** — controlled/uncontrolled input + optional caption, submit button, camera, status slot, and the inline `Bluetooth scanner: On/Off` toggle. `allowKeyboard` defaults to `!connected`.
- **`src/components/CameraScanFallback.tsx`** — dynamic-imported `html5-qrcode`, `useBarCodeDetectorIfSupported`, formats QR/CODE_128/CODE_39/EAN-13/EAN-8/UPC-A, permission-error message.

### Per-page wiring

| Page | Usage |
|---|---|
| Search (both tabs) | `submitLabel="Search"`, `onScan=setTerm` → instant lookup on scan |
| Sale | `clearOnScan`, `status` slot for the two aria-live regions |
| Receive | standalone scan box fills the serial field (`clearOnScan`) |
| Stock Adjustment | controlled barcode/SKU fields (`onValueChange` + `onScan` so camera also sets value) |

## Verification

- `tsc --noEmit` clean (full project); `biome check` clean on all touched files.
- `useScanner` untouched → `tests/scanner.spec.ts` unaffected.
- Manual smoke recommended per page (type, Enter, camera, toggle persistence).
