# QR Code Unit Labels — Design

**Date:** 2026-06-16
**Branch:** `dev` → feature branch (`feat/qr-unit-labels`)
**Source:** `/brainstorming` session. Replaces the Code128 symbology on serialized-unit labels with QR. Library APIs confirmed via context7 (`/websites/reportlab`, `/mebjas/html5-qrcode`).

## Summary

Serialized units print a small label on receive (and on the lost-label reprint path). Today `backend/app/services/barcode.py::render_unit_label` draws a **Code128** barcode of the unit's `castranova_barcode` value. This change swaps the drawn symbology to **QR**, leaving the stored value, scan-lookup logic, FIFO/stock, DB schema, and SDK untouched.

The change is small and backend-concentrated because the plumbing already supports QR:

- The **wedge scan path** (`useScanner`/`ScanInput`) is symbology-agnostic — the hardware decodes and types keystrokes. Warehouse scanners are confirmed **2D-capable** (they read QR), so a QR-only label works on the primary path.
- The **camera fallback** (`CameraScanFallback`, `html5-qrcode`) already decodes QR + Code128.
- Backend deps already include `reportlab>=4.2.0` (ships a native vector QR widget) — **no new dependency**, no Pillow. The pre-declared-but-unused `qrcode` dep is left as-is (removal is out of scope).

## Constraints (hard)

- **QR payload is the raw `castranova_barcode` string** (`"CN-" + uuid hex`, ≤ 64 chars). Encoding a URL or any wrapper would make the wedge type a different string and break `useScanLookup` / all scan-to-action logic. Not a design choice — a requirement.
- **No DB migration, no `models.py` change, no SDK regen, no FIFO/stock/ledger change.** Only label rendering and camera read config.
- **Both text lines stay on the label.** The bold human-readable `CN-…` line is the manual fallback for the lost-label reprint path (`S-lost-label`); the caption stays the supplier serial.

## Approach (chosen)

**ReportLab-native QR, QR-only label.** Considered and rejected: (2) the `qrcode` lib + `drawImage` — raster, needs Pillow, worse quality than native vector, more moving parts; (3) dual QR+Code128 labels — YAGNI given confirmed 2D scanners, bigger label and more code for no benefit.

## Design

### Backend — `services/barcode.py`

Replace the Code128 strip with a QR symbol; keep the canvas size (~60×30mm) and both text lines.

- Build `QrCodeWidget(castranova_barcode, barLevel="M")` and add it to a `reportlab.graphics.shapes.Drawing`, scaled to fit a ~22mm square on the left of the label, drawn onto the existing `canvas` via `reportlab.graphics.renderPDF.draw(drawing, pdf, x, y)`.
  - The widget reports its natural bounds via `.getBounds()`; compute a scale `transform` so the QR fills the target mm box with a small quiet-zone margin. (Exact transform math settled in the plan.)
- Error correction level **M** (standard balance; tunable). The `CN-…` value is ~19 alphanumeric chars → QR version 1–2, modules ~1mm at 22mm — comfortably scannable on a printed warehouse label.
- Keep: bold `castranova_barcode` text line + the supplier-serial caption (`caption[:48]`).

Label layout (60×30mm landscape):

```
+------------------------------------------------+
| ┌────────────┐                                 |
| │ ▄▄ ▄  ▄▄▄  │    CN-A1B2C3D4E5F6A7B8           |  <- bold (human-readable)
| │ █  ▄▄  █   │    SN: <supplier_serial>         |  <- caption
| │ ▄▄▄ ▄ ▄▄   │                                  |
| └────────────┘                                  |
+------------------------------------------------+
     ~22mm QR            text block
```

The function signature `render_unit_label(*, castranova_barcode: str, caption: str) -> bytes` is **unchanged**, so the route (`receipts.py::read_unit_label`) needs no edit.

### Frontend — `CameraScanFallback.tsx`

Pin the camera decoder to the two symbologies in use (default is *all* formats; restricting drops EAN/UPC false-positive reads while keeping old Code128 labels working):

- Import `Html5QrcodeSupportedFormats` from `html5-qrcode`.
- Add `formatsToSupport: [Html5QrcodeSupportedFormats.QR_CODE, Html5QrcodeSupportedFormats.CODE_128]` to the existing `.start(..., { fps: 10, qrbox: 250 }, ...)` config object.

The wedge path (`useScanner`, `ScanInput`) needs **no change** — the 2D scanner decodes QR/Code128 and types the value; the keystroke buffer is symbology-blind.

### Backwards compatibility

Already-printed Code128 labels keep scanning on both paths: the 2D wedge imager reads 1D, and the camera keeps Code128 enabled. No prod data changes; the stored `castranova_barcode` is identical before and after.

## Testing

Label rendering is low blast-radius (no money, stock, ledger, or auth), but it is adjacent to the scan flow, so verify the decode round-trips rather than just asserting the PDF is non-empty.

- **Backend (TDD, failing test first):**
  - `render_unit_label(...)` → rasterize the one-page PDF → decode → assert the decoded text equals the exact `castranova_barcode` **and** the detected format is QR. *Open implementation detail:* decoder/rasterizer choice — `pdf2image`+`opencv-python-headless` `QRCodeDetector`, or rasterize + `pyzbar`. Pick the lightest that installs cleanly on the Windows dev box + CI in the plan; gate the test with a skip if the optional decoder isn't present so the suite still runs.
  - Keep existing tests green: `test_label_pdf_returned_for_unit`, `test_staff_can_fetch_unit_label`, `test_unauthenticated_cannot_fetch_unit_label` (PDF magic bytes + auth).
- **Frontend:**
  - Browserless check (per repo convention for pure logic) that the `formatsToSupport` array passed to `html5-qrcode` is exactly `[QR_CODE, CODE_128]`. If the value isn't cleanly extractable without a DOM, cover it instead with the E2E below.
  - Optional `ecc:e2e-runner` Playwright pass: generate a QR image of a known `CN-…` value, feed it to `html5-qrcode` `scanFileV2`, assert `decodedText` and `format.formatName === "QR_CODE"` — end-to-end decode proof.

## Review

Per CLAUDE.md stage 5: run `requesting-code-review` → dispatch `ecc:fastapi-reviewer` + `ecc:react-reviewer`. `ecc:database-reviewer` / `ecc:security-reviewer` are **not** required — no schema, ledger, money, or auth change.

## Out of scope

- Removing the unused `qrcode` backend dependency.
- Changing the stored `castranova_barcode` format/length.
- Any `ServiceTicketPart` idempotency work (tracked separately in CLAUDE.md backlog).
- Reprint UI changes — the existing `label.pdf` endpoint and receive-screen print button are untouched.
