# SKU/Bin QR Labels for QUANTITY Products — Design Spec

**Date:** 2026-06-16
**Status:** Approved (brainstorming → design); ready for implementation planning
**Scope:** Add printable **SKU/bin QR labels** for QUANTITY (commodity) products, and **unify the print-label UI** so the serialized and quantity print buttons are identical.
**Relates to:** [System Design](2026-05-23-castranova-pos-system-design.md) (FR-005/FR-006, Flow A), [QR Unit Labels plan](../plans/2026-06-16-castranova-qr-unit-labels.md) (the serialized-unit QR label this builds on), [PRD v3.0](../../client/2026-06-02-castranova-pos-v3.0-prd.md) §5/§6.2/§7.2.

---

## 1. Problem

Serialized products mint one `unit` row per piece, each with a unique `castranova_barcode`, and get a per-piece QR label (`render_unit_label` → `GET /receipts/serialized/{unit_id}/label.pdf`). **QUANTITY products have no label at all** — they are received as a fungible `part_batch` with no per-unit identity. The client wants commodity stock to be **scannable on the shelf/bin**: a QR label they can print N times and stick on bins/pieces, so a scan at Sale/Receive resolves the product.

This fills a real gap: PRD §5/§7.2 says YGN staff "label new stock," but FR-005 only specifies serialized labels.

## 2. Goals / Non-Goals

**Goals**
- Print N identical QR labels for a QUANTITY product; each QR encodes the raw `product.sku`.
- Reuse the existing QR renderer and 60×30mm label so SKU labels look identical to serialized labels (client requirement: "match with serialized").
- **Unify the print button** — one component, identical UI/behavior for serialized and quantity.
- Reachable from three places: Receive (Quantity tab), Stock screen, Catalog.

**Non-Goals**
- No per-piece tracking of commodity items (does **not** break the FIFO/QUANTITY model; labels are fungible).
- No new product-level barcode field — encode the raw `sku` (resolves via the existing `searchSku` path with zero backend resolution changes).
- No DB migration, no `models.py`/schema change, no grid/Avery sheet layout.

## 3. Key Decisions (from brainstorming)

| # | Decision | Rationale |
|---|---|---|
| D1 | QR encodes raw `product.sku` | Resolves through existing `searchSerial` 404 → `searchSku` scan path (`useScanLookup.ts`); a new `CN-` field would need migration + new resolution plumbing for no functional gain on a fungible label. |
| D2 | 2D QR, 60×30mm, ECC level **M**, reuse `_unit_qr_drawing` | Client wants it to match serialized labels; ECC-M is the standard print default; 20mm QR + default 4-module quiet zone clears the ~20mm reliable-scan minimum for a short SKU payload. |
| D3 | One label per page × N pages (multi-page PDF) | Matches the TSC TDP-225 roll thermal printer and the existing single-page label pipeline. |
| D4 | `qty` bounded `1 ≤ qty ≤ 1000` | Prevents an accidental runaway PDF; covers realistic batch sizes. |
| D5 | **Unify the print button** for serialized + quantity (identical UI) | Explicit client requirement. Serialized label endpoint gains an optional `?qty=N` (default 1, backward-compatible); one frontend component serves both. |
| D6 | Endpoint open to **both roles** (`get_current_user`) | Mirrors the existing unit-label endpoint; staff print on receive. No financials exposed. |
| D7 | Not high-risk (no ledger/FIFO/money/schema) | The mandatory FIFO-concurrency test and DB/security reviewers (CLAUDE.md §5) do **not** apply; review = `ecc:fastapi-reviewer` + `ecc:react-reviewer`. |

## 4. Backend

### 4.1 `app/services/barcode.py`
Factor the single-label drawing out of `render_unit_label`, then add a generic N-page renderer. Keep `_unit_qr_drawing` (ECC-M, scale-to-fit) unchanged.

- `_draw_label_page(pdf, *, qr_value: str, line1: str, line2: str) -> None` — draws one 60×30mm label page (QR on the left via `renderPDF.draw`, `line1` bold + `line2` to the right), then `pdf.showPage()`. Extracted verbatim from the current `render_unit_label` body.
- `render_label_sheet(*, qr_value: str, line1: str, line2: str, qty: int = 1) -> bytes` — one `canvas.Canvas`, loop `_draw_label_page` `qty` times, `save()`, return bytes.
- `render_unit_label(*, castranova_barcode: str, caption: str) -> bytes` — **kept** as a thin wrapper delegating to `render_label_sheet(qr_value=castranova_barcode, line1=castranova_barcode, line2=caption, qty=1)` so the existing `test_unit_label.py` stays green with no churn.

### 4.2 Routes
- **`app/api/routes/receipts.py`** — add `qty: Annotated[int, Query(ge=1, le=1000)] = 1` to `read_unit_label`; render via `render_label_sheet(qr_value=unit.castranova_barcode, line1=unit.castranova_barcode, line2=unit.supplier_serial, qty=qty)`. Default `qty=1` keeps current callers unchanged.
- **`app/api/routes/products.py`** — new:
  ```
  GET /products/{product_id}/label.pdf?qty=N   dependencies=[Depends(get_current_user)]
  ```
  - `qty: Annotated[int, Query(ge=1, le=1000)] = 1`.
  - `crud.get_product(session=session, product_id=product_id)` → **404** "Product not found" if missing.
  - **400** "SKU labels are only for quantity-tracked products" if `tracking_mode == TrackingMode.SERIALIZED` (defense-in-depth; UI only shows the button on QUANTITY rows).
  - `render_label_sheet(qr_value=product.sku, line1=product.sku, line2=product.model_name, qty=qty)` → `Response(content=pdf, media_type="application/pdf")`.

No `crud` change needed (`get_product` already exists, `backend/app/crud.py:420`).

## 5. Frontend

### 5.1 `lib/print-pdf.ts` (new)
Extract the authed-PDF-blob-open logic (token check → `fetch` with bearer → `blob` → `URL.createObjectURL` → `window.open` + popup-block handling → object-URL cleanup) from `PrintLabelButton` into one helper, e.g. `openAuthedPdf(path: string): Promise<"ok" | "no-token" | "fetch-failed" | "popup-blocked">`. The caller maps the result to a toast. Keeps both label paths in sync.

### 5.2 `components/PrintLabelButton.tsx` (unified)
One component, identical UI for both kinds: a compact qty number input (min 1, max 1000, default = `defaultQty ?? 1`) + a "Print label(s)" button (Printer icon, `h-11`, "Opening…" while in flight, disabled during fetch — same affordances as today).

Discriminated target prop:
```ts
type PrintLabelTarget =
  | { kind: "unit"; unitId: string; serial: string }
  | { kind: "sku"; productId: string; sku: string }
```
- `kind: "unit"` → `openAuthedPdf(\`/api/v1/receipts/serialized/${unitId}/label.pdf?qty=${n}\`)`
- `kind: "sku"`  → `openAuthedPdf(\`/api/v1/products/${productId}/label.pdf?qty=${n}\`)`

`aria-label` describes the target (serial / SKU). Existing call sites pass the new `kind: "unit"` shape.

### 5.3 Placements (QUANTITY shown for SKU; serialized unchanged in location)
- **Receive → Quantity tab** (`routes/_layout/receive.tsx`): after a batch is received, render `PrintLabelButton kind="sku"` with **`defaultQty = batch.received_qty`** (editable, clamped to 1000). Look up the product from the cached `quantityProducts` by `batch.product_id` for the SKU display.
- **Stock screen** (`routes/_layout/stock.tsx`): on each **QUANTITY top-level row**, `PrintLabelButton kind="sku"` (`defaultQty 1`). Serialized unit rows keep their existing button (now `kind="unit"`, gains the qty input — identical UI).
- **Catalog** (`routes/_layout/products.tsx`): on each **QUANTITY product row**, `PrintLabelButton kind="sku"` (`defaultQty 1`).

### 5.4 SDK
Both label endpoints return binary PDF (typed `unknown` by the generated SDK), so the app uses the sanctioned bare authed fetch — no SDK dependency. `bun run generate-client` will regenerate on pre-commit (adds the new typed-unknown method); the app does not rely on it.

## 6. Data Flow

Print button → authed `GET …/label.pdf?qty=N` → server renders an N-page PDF (each page = QR(sku|barcode) + two text lines) → opens in a new tab → user prints to the TSC TDP-225 → later, scanning any label resolves the product/unit via the existing scan path.

## 7. Error Handling

| Case | Behavior |
|---|---|
| Missing product / unit | 404 → toast "Could not load label PDF." |
| `kind="sku"` against a SERIALIZED product | 400 → toast (defense-in-depth; UI hides the button there) |
| `qty` out of range | 422 from FastAPI `Query` bounds; UI input is clamped 1–1000 |
| Expired session / popup blocked | Same toasts as today's `PrintLabelButton` |

## 8. Testing

**Backend (pytest)** — new `tests/services/test_label_sheet.py` + additions to the receipts/products route tests:
- `render_label_sheet` produces exactly `qty` pages; each page's QR encodes the expected value at ECC-M (structural, zero-dep, mirrors `test_unit_label.py`).
- Output begins `%PDF`; `render_unit_label` wrapper still returns a 1-page `%PDF` (no regression).
- `GET /products/{id}/label.pdf`: valid PDF for a QUANTITY product; **404** missing; **400** serialized; **422** qty 0 / 1001; **401** unauthenticated.
- `GET /receipts/serialized/{id}/label.pdf?qty=3`: 3-page PDF; default (no qty) still 1 page.

**Frontend** — biome + `tsc --noEmit`; manual print/scan verification (camera path can't run headless).

**Review (CLAUDE.md §5 stage 5)** — dispatch `ecc:fastapi-reviewer` (backend) + `ecc:react-reviewer` (frontend), **both with model Opus 4.8**. DB/security reviewers not required (no schema/ledger/money/auth change).

## 9. Out of Scope / Future

- Per-piece serialization of commodity parts (would break FIFO; explicitly rejected).
- Grid/Avery sheet layout for office laser printers (roll thermal only in v1).
- Configurable label dimensions / ECC level (fixed at 60×30mm / ECC-M to match serialized labels).
