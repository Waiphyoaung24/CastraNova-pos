# SKU/Bin QR Labels + Unified Print Button — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add printable SKU/bin QR labels for QUANTITY products (`GET /products/{id}/label.pdf?qty=N`, QR encodes `product.sku`), and unify the serialized + quantity print buttons into one identical UI control.

**Architecture:** Backend factors the existing single-label drawing out of `render_unit_label` into a shared `render_label_sheet(qty)` N-page renderer; the serialized label endpoint gains an optional `?qty`, and a new products endpoint renders SKU labels. Frontend extracts the authed-PDF-open logic into `lib/print-pdf.ts` and replaces `PrintLabelButton` with one component (qty input + print button) used for both unit and SKU labels. No DB migration, no `models.py` change.

**Tech Stack:** Python · ReportLab (`QrCodeWidget`, `renderPDF`, `canvas`) · FastAPI · pytest · React/TypeScript · TanStack Query · shadcn/ui · biome.

**Spec:** `docs/superpowers/specs/2026-06-16-castranova-sku-qr-labels-design.md`

---

## File Structure

- **Modify** `backend/app/services/barcode.py` — add `_draw_label_page` + `render_label_sheet`; make `render_unit_label` a thin wrapper.
- **Create** `backend/tests/services/test_label_sheet.py` — page-count + PDF-validity tests (parser-free, mirrors `test_unit_label.py`).
- **Modify** `backend/app/api/routes/receipts.py` — add `qty` to the unit-label endpoint; render via `render_label_sheet`.
- **Modify** `backend/tests/api/routes/test_receipts_serialized.py` — add a qty multi-page test.
- **Modify** `backend/app/api/routes/products.py` — new `GET /{product_id}/label.pdf` SKU-label endpoint.
- **Modify** `backend/tests/api/routes/test_products.py` — SKU-label endpoint tests (happy path, 404, 400, 422, auth, staff).
- **Create** `frontend/src/lib/print-pdf.ts` — `openAuthedPdf(path)` shared helper.
- **Modify** `frontend/src/components/PrintLabelButton.tsx` — unified component (discriminated `target` + `defaultQty`).
- **Modify** `frontend/src/routes/_layout/receive.tsx` — update serialized call site; add SKU labels to the Quantity tab.
- **Modify** `frontend/src/routes/_layout/stock.tsx` — update serialized call site; add SKU button to QUANTITY rows.
- **Modify** `frontend/src/routes/_layout/products.tsx` — add SKU button to QUANTITY catalog rows.
- **Untouched:** `models.py`, migrations, `crud.py` (`get_product` already exists at `crud.py:420`), `_unit_qr_drawing`.

---

## Task 1: Backend — shared N-page label renderer (TDD)

**Files:**
- Modify: `backend/app/services/barcode.py`
- Test: `backend/tests/services/test_label_sheet.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/services/test_label_sheet.py`:

```python
"""Structural tests for render_label_sheet (SKU/bin + serialized QR labels).

Mirrors test_unit_label.py's parser-free philosophy: assert page count and PDF
validity from raw bytes (the repo deliberately carries no PDF-parsing dep). The
per-page QR value/ECC-M guarantee is already covered by test_unit_label.py via
the shared _unit_qr_drawing helper that render_label_sheet reuses.
"""

import re

from app.services.barcode import render_label_sheet, render_unit_label


def _page_count(pdf: bytes) -> int:
    # One PDF page object ("/Type /Page") per label. The negative lookahead on
    # the trailing 's' excludes the single "/Type /Pages" catalog node.
    return len(re.findall(rb"/Type\s*/Page(?!s)", pdf))


def test_render_label_sheet_default_is_one_page() -> None:
    pdf = render_label_sheet(qr_value="FLT-001", line1="FLT-001", line2="Filter")
    assert pdf[:4] == b"%PDF"
    assert _page_count(pdf) == 1


def test_render_label_sheet_emits_qty_pages() -> None:
    pdf = render_label_sheet(
        qr_value="FLT-001", line1="FLT-001", line2="Filter", qty=5
    )
    assert pdf[:4] == b"%PDF"
    assert _page_count(pdf) == 5


def test_render_unit_label_wrapper_still_one_page() -> None:
    pdf = render_unit_label(castranova_barcode="CN-ABC123", caption="SN-9")
    assert pdf[:4] == b"%PDF"
    assert _page_count(pdf) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `backend/`):

```bash
pytest tests/services/test_label_sheet.py -v
```

Expected: FAIL — `ImportError: cannot import name 'render_label_sheet' from 'app.services.barcode'`.

- [ ] **Step 3: Implement the shared renderer**

In `backend/app/services/barcode.py`, replace the module docstring and the `render_unit_label` function (keep the imports, the `_LABEL_*`/`_QR_SIZE` constants, and `_unit_qr_drawing` exactly as they are).

Replace the top docstring with:

```python
"""QR label rendering for serialized units (FR-005) and SKU/bin labels.

Produces small self-contained PDF labels so warehouse staff can print/reprint
on receive. A serialized label encodes a unit's castranova_barcode; a SKU label
encodes a product's sku. Both share one 60x30mm QR + two-line layout and can
emit N identical pages (one label per page) for the roll thermal printer. The
encoded value is also printed human-readable for the manual fallback.
"""
```

Then replace the existing `render_unit_label` function with these three definitions:

```python
def _draw_label_page(
    pdf: canvas.Canvas, *, qr_value: str, line1: str, line2: str
) -> None:
    """Draw one 60x30mm label page (QR + two text lines) and end the page."""
    renderPDF.draw(_unit_qr_drawing(qr_value), pdf, 3 * mm, 5 * mm)
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(26 * mm, 16 * mm, line1)
    pdf.setFont("Helvetica", 6)
    pdf.drawString(26 * mm, 9 * mm, line2[:48])
    pdf.showPage()


def render_label_sheet(
    *, qr_value: str, line1: str, line2: str, qty: int = 1
) -> bytes:
    """Return a `qty`-page PDF (bytes); every page is an identical QR label."""
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=(_LABEL_W, _LABEL_H))
    for _ in range(qty):
        _draw_label_page(pdf, qr_value=qr_value, line1=line1, line2=line2)
    pdf.save()
    return buf.getvalue()


def render_unit_label(*, castranova_barcode: str, caption: str) -> bytes:
    """One-page serialized-unit QR label PDF (bytes).

    Thin wrapper over render_label_sheet, kept for the receipts route's existing
    call site and test_unit_label.py's pinned signature.
    """
    return render_label_sheet(
        qr_value=castranova_barcode,
        line1=castranova_barcode,
        line2=caption,
        qty=1,
    )
```

- [ ] **Step 4: Run the new + existing label tests**

Run (from `backend/`):

```bash
pytest tests/services/test_label_sheet.py tests/services/test_unit_label.py -v
```

Expected: PASS — all three new tests plus the existing `test_unit_label.py` (the `render_unit_label` signature + `_unit_qr_drawing` ECC-M guards still hold).

- [ ] **Step 5: Typecheck**

Run (from `backend/`):

```bash
mypy app/services/barcode.py
```

Expected: `Success: no issues found`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/barcode.py backend/tests/services/test_label_sheet.py
git commit -m "feat(stock): shared N-page QR label renderer (render_label_sheet)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Backend — serialized label endpoint gains `?qty` (TDD)

**Files:**
- Modify: `backend/app/api/routes/receipts.py`
- Test: `backend/tests/api/routes/test_receipts_serialized.py`

- [ ] **Step 1: Write the failing test**

In `backend/tests/api/routes/test_receipts_serialized.py`, add `import re` at the top of the import block (after `import uuid`), then append this helper + test at the end of the file:

```python
def _page_count(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page(?!s)", pdf))


def test_unit_label_qty_emits_multiple_pages(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    seed_product_supplier: tuple[uuid.UUID, uuid.UUID],
) -> None:
    product_id, supplier_id = seed_product_supplier
    rec = client.post(
        f"{PREFIX}/receipts/serialized",
        headers=superuser_token_headers,
        json=_body(product_id, supplier_id),
    )
    unit_id = rec.json()["units"][0]["id"]

    r3 = client.get(
        f"{PREFIX}/receipts/serialized/{unit_id}/label.pdf?qty=3",
        headers=superuser_token_headers,
    )
    assert r3.status_code == 200
    assert _page_count(r3.content) == 3

    r1 = client.get(
        f"{PREFIX}/receipts/serialized/{unit_id}/label.pdf",
        headers=superuser_token_headers,
    )
    assert _page_count(r1.content) == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `backend/`):

```bash
pytest tests/api/routes/test_receipts_serialized.py::test_unit_label_qty_emits_multiple_pages -v
```

Expected: FAIL — `assert 1 == 3` (the endpoint ignores `qty` and always renders one page).

- [ ] **Step 3: Implement `qty` on the endpoint**

In `backend/app/api/routes/receipts.py`:

Change the imports. Replace line 1–3:

```python
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
```

with:

```python
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
```

Change the service import (line 13) from:

```python
from app.services.barcode import render_unit_label
```

to:

```python
from app.services.barcode import render_label_sheet
```

Replace the entire `read_unit_label` function with:

```python
@router.get(
    "/serialized/{unit_id}/label.pdf",
    dependencies=[Depends(get_current_user)],
)
def read_unit_label(
    *,
    session: SessionDep,
    unit_id: uuid.UUID,
    qty: Annotated[int, Query(ge=1, le=1000)] = 1,
) -> Response:
    unit = crud.get_unit(session=session, unit_id=unit_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    pdf = render_label_sheet(
        qr_value=unit.castranova_barcode,
        line1=unit.castranova_barcode,
        line2=unit.supplier_serial,
        qty=qty,
    )
    return Response(content=pdf, media_type="application/pdf")
```

- [ ] **Step 4: Run the receipts serialized suite**

Run (from `backend/`):

```bash
pytest tests/api/routes/test_receipts_serialized.py -v
```

Expected: PASS — the new qty test plus all existing label/receive tests (`test_label_pdf_returned_for_unit`, `test_staff_can_fetch_unit_label`, etc.).

- [ ] **Step 5: Typecheck**

Run (from `backend/`):

```bash
mypy app/api/routes/receipts.py
```

Expected: `Success: no issues found`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/receipts.py backend/tests/api/routes/test_receipts_serialized.py
git commit -m "feat(stock): unit label endpoint accepts ?qty for N copies

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Backend — SKU label endpoint for QUANTITY products (TDD)

**Files:**
- Modify: `backend/app/api/routes/products.py`
- Test: `backend/tests/api/routes/test_products.py`

- [ ] **Step 1: Write the failing tests**

In `backend/tests/api/routes/test_products.py`, add `import re` after `import uuid`, then append this helper + tests at the end of the file:

```python
def _page_count(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page(?!s)", pdf))


def _create_quantity_product(
    client: TestClient, headers: dict[str, str]
) -> dict[str, object]:
    sku = f"QTY-{uuid.uuid4().hex[:8]}"
    r = client.post(
        f"{PREFIX}/products/",
        headers=headers,
        json=_product_body(sku, tracking_mode="QUANTITY"),
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_sku_label_pdf_for_quantity_product(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    p = _create_quantity_product(client, superuser_token_headers)
    r = client.get(
        f"{PREFIX}/products/{p['id']}/label.pdf?qty=4",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"
    assert _page_count(r.content) == 4


def test_sku_label_defaults_to_one_page(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    p = _create_quantity_product(client, superuser_token_headers)
    r = client.get(
        f"{PREFIX}/products/{p['id']}/label.pdf", headers=superuser_token_headers
    )
    assert r.status_code == 200
    assert _page_count(r.content) == 1


def test_sku_label_404_for_missing_product(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.get(
        f"{PREFIX}/products/{uuid.uuid4()}/label.pdf",
        headers=superuser_token_headers,
    )
    assert r.status_code == 404


def test_sku_label_400_for_serialized_product(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    sku = f"SER-{uuid.uuid4().hex[:8]}"
    p = client.post(
        f"{PREFIX}/products/",
        headers=superuser_token_headers,
        json=_product_body(sku, tracking_mode="SERIALIZED"),
    ).json()
    r = client.get(
        f"{PREFIX}/products/{p['id']}/label.pdf", headers=superuser_token_headers
    )
    assert r.status_code == 400


def test_sku_label_qty_out_of_range_422(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    p = _create_quantity_product(client, superuser_token_headers)
    assert (
        client.get(
            f"{PREFIX}/products/{p['id']}/label.pdf?qty=0",
            headers=superuser_token_headers,
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"{PREFIX}/products/{p['id']}/label.pdf?qty=1001",
            headers=superuser_token_headers,
        ).status_code
        == 422
    )


def test_sku_label_requires_auth(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    p = _create_quantity_product(client, superuser_token_headers)
    r = client.get(f"{PREFIX}/products/{p['id']}/label.pdf")
    assert r.status_code == 401


def test_staff_can_fetch_sku_label(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    staff_token_headers: dict[str, str],
) -> None:
    p = _create_quantity_product(client, superuser_token_headers)
    r = client.get(
        f"{PREFIX}/products/{p['id']}/label.pdf", headers=staff_token_headers
    )
    assert r.status_code == 200
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `backend/`):

```bash
pytest tests/api/routes/test_products.py -k sku_label -v
```

Expected: FAIL — the label route does not exist yet (404 for the happy-path test / route-not-found).

- [ ] **Step 3: Implement the endpoint**

In `backend/app/api/routes/products.py`:

Change the FastAPI import (line 4) from:

```python
from fastapi import APIRouter, Depends, HTTPException, Query
```

to:

```python
from fastapi import APIRouter, Depends, HTTPException, Query, Response
```

Add `TrackingMode` to the `app.models` import block and add the barcode-service import. The models import currently lists `MinStockLevelUpdate, PriceChangePublic, ProductCreate, ProductPublic, ProductUpdate` — add `TrackingMode` to that list. Then after the models import block add:

```python
from app.services.barcode import render_label_sheet
```

Add this route (place it directly after the existing `read_products` function, before `create_product`):

```python
# Shared-team access (mirrors the serialized unit-label endpoint): any
# authenticated staff/admin may print SKU labels. The QR encodes the raw
# product.sku, which resolves via GET /search/sku/{sku}. No financials exposed.
@router.get("/{product_id}/label.pdf", dependencies=[Depends(get_current_user)])
def read_sku_label(
    *,
    session: SessionDep,
    product_id: uuid.UUID,
    qty: Annotated[int, Query(ge=1, le=1000)] = 1,
) -> Response:
    """Print N identical SKU/bin QR labels for a QUANTITY product."""
    product = crud.get_product(session=session, product_id=product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if product.tracking_mode == TrackingMode.SERIALIZED:
        raise HTTPException(
            status_code=400,
            detail="SKU labels are only for quantity-tracked products",
        )
    pdf = render_label_sheet(
        qr_value=product.sku,
        line1=product.sku,
        line2=product.model_name,
        qty=qty,
    )
    return Response(content=pdf, media_type="application/pdf")
```

(`Annotated` is already imported at the top of `products.py`.)

- [ ] **Step 4: Run the tests to verify they pass**

Run (from `backend/`):

```bash
pytest tests/api/routes/test_products.py -v
```

Expected: PASS — all `sku_label` tests plus the existing product tests.

- [ ] **Step 5: Typecheck**

Run (from `backend/`):

```bash
mypy app/api/routes/products.py
```

Expected: `Success: no issues found`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/products.py backend/tests/api/routes/test_products.py
git commit -m "feat(stock): SKU/bin QR label endpoint for quantity products

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Frontend — shared PDF helper + unified PrintLabelButton

**Files:**
- Create: `frontend/src/lib/print-pdf.ts`
- Modify: `frontend/src/components/PrintLabelButton.tsx`

- [ ] **Step 1: Create the shared authed-PDF helper**

Create `frontend/src/lib/print-pdf.ts`:

```ts
/** Fetches an authed binary PDF and opens it in a new browser tab.
 *
 * Label PDFs are authed binary downloads the generated SDK types as `unknown`,
 * so this is the app's one sanctioned bare fetch — it attaches the bearer token
 * by hand. Returns a result code the caller maps to a toast; never throws.
 *
 * `path` is the API path AFTER `/api/v1` (e.g. "/products/<id>/label.pdf?qty=3").
 */
export type PrintPdfResult = "ok" | "no-token" | "fetch-failed" | "popup-blocked"

export async function openAuthedPdf(path: string): Promise<PrintPdfResult> {
  const token = localStorage.getItem("access_token")
  if (!token) return "no-token"
  let url: string | null = null
  try {
    const res = await fetch(`${import.meta.env.VITE_API_URL}/api/v1${path}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) return "fetch-failed"
    url = URL.createObjectURL(await res.blob())
    const win = window.open(url, "_blank", "noopener,noreferrer")
    if (!win) {
      URL.revokeObjectURL(url)
      return "popup-blocked"
    }
    // The new tab needs the object URL alive while it loads the blob; revoke
    // after a delay so it is not leaked for the page's lifetime.
    const created = url
    setTimeout(() => URL.revokeObjectURL(created), 60_000)
    return "ok"
  } catch {
    if (url) URL.revokeObjectURL(url)
    return "fetch-failed"
  }
}
```

- [ ] **Step 2: Replace PrintLabelButton with the unified component**

Replace the entire contents of `frontend/src/components/PrintLabelButton.tsx` with:

```tsx
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

/** Identical print-label control for serialized units and quantity SKUs.
 *
 * A quantity input (1–1000) + a print button that opens an N-copy label PDF in
 * a new tab. Serialized → the unit-label endpoint; quantity → the SKU-label
 * endpoint. Both encode a QR (unit barcode / product sku) the in-app scanner
 * resolves. While the PDF is in flight the control disables and reads
 * "Opening…", preventing a double-click from spawning two tabs. */
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

  const what =
    target.kind === "unit" ? `serial ${target.serial}` : `SKU ${target.sku}`

  async function handlePrint() {
    const n = Number(qty)
    if (!Number.isInteger(n) || n < 1 || n > 1000) {
      showErrorToast("Enter a quantity between 1 and 1000.")
      return
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
      <Input
        type="number"
        min={1}
        max={1000}
        value={qty}
        onChange={(e) => setQty(e.target.value)}
        className="num h-11 w-20"
        aria-label={`Number of labels for ${what}`}
        disabled={isOpening}
      />
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="h-11"
        aria-label={`Print labels for ${what}`}
        disabled={isOpening}
        onClick={handlePrint}
      >
        <Printer className="size-4" />
        {isOpening ? "Opening…" : "Print labels"}
      </Button>
    </div>
  )
}
```

- [ ] **Step 3: Typecheck (expect call-site errors — fixed in Task 5)**

Run (from `frontend/`):

```bash
bunx biome check src/lib/print-pdf.ts src/components/PrintLabelButton.tsx
```

Expected: biome reports no errors on these two files. (`bunx tsc --noEmit` will still fail on `stock.tsx`/`receive.tsx` call sites — those are fixed in Task 5; do not run the full typecheck until then.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/print-pdf.ts frontend/src/components/PrintLabelButton.tsx
git commit -m "feat(stock): unify PrintLabelButton (qty + shared openAuthedPdf)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Frontend — wire the three placements

**Files:**
- Modify: `frontend/src/routes/_layout/receive.tsx`
- Modify: `frontend/src/routes/_layout/stock.tsx`
- Modify: `frontend/src/routes/_layout/products.tsx`

- [ ] **Step 1: Update the serialized call site + add SKU labels in `receive.tsx`**

In `frontend/src/routes/_layout/receive.tsx`:

(a) Add `ProductPublic` to the `@/client` import block (it currently imports `ProductsService`, `ReceiptsReceiveQuantityResponse`, `ReceiptsService`, `ReceiveQuantityRequest`, `ReceiveSerializedRequest`, `ReceiveSerializedResponse`, `SuppliersService`, `UnitPublic`) — add `type ProductPublic`.

(b) In `ReceivedUnits`, change the existing button:

```tsx
                <PrintLabelButton unitId={u.id} serial={u.supplier_serial} />
```

to:

```tsx
                <PrintLabelButton
                  target={{ kind: "unit", unitId: u.id, serial: u.supplier_serial }}
                />
```

(c) In `QuantityTab`, add a state field for the just-received batch. After the existing `const [draft, setDraft] = useState<QuantityDraft>(EMPTY_QUANTITY_DRAFT)` line add:

```tsx
  const [receivedBatch, setReceivedBatch] =
    useState<ReceiptsReceiveQuantityResponse | null>(null)
```

(d) In the `QuantityTab` mutation `onSuccess`, add `setReceivedBatch(batch)` as the first line (keep the existing `setDraft`/`announceMessage`/`showSuccessToast` calls):

```tsx
    onSuccess: (batch) => {
      setReceivedBatch(batch)
      setDraft(EMPTY_QUANTITY_DRAFT)
      announceMessage(
        `Received ${batch.received_qty} unit(s) into batch ${batch.batch_no}.`,
      )
      showSuccessToast(`Received batch ${batch.batch_no}.`)
    },
```

(e) In `QuantityTab`'s returned JSX, add the labels block immediately after the submit-button `<div>` (the one containing the "Receive" button), still inside the `<form>`:

```tsx
      {receivedBatch ? (
        <ReceivedBatchLabels batch={receivedBatch} products={quantityProducts} />
      ) : null}
```

(f) Add this component at the end of the file (after `ReceivedUnits`):

```tsx
function ReceivedBatchLabels({
  batch,
  products,
}: {
  batch: ReceiptsReceiveQuantityResponse
  products: ProductPublic[]
}) {
  const product = products.find((p) => p.id === batch.product_id)
  if (!product) return null
  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-lg font-semibold">Print SKU labels</h2>
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-muted-foreground text-sm">
          {product.sku} — batch {batch.batch_no}
        </span>
        <PrintLabelButton
          target={{ kind: "sku", productId: product.id, sku: product.sku }}
          defaultQty={Math.min(batch.received_qty, 1000)}
        />
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Update `stock.tsx` (serialized call site + QUANTITY-row SKU button)**

In `frontend/src/routes/_layout/stock.tsx`:

(a) In the main table header (the `<TableRow>` with `SKU`/`Model`/`Category`/`Mode`/`On hand`), add a trailing actions head after the `On hand` `<TableHead>`:

```tsx
              <TableHead className="text-right">On hand</TableHead>
              <TableHead className="w-0" aria-label="Labels" />
```

(b) In `StockRow`'s main `<TableRow>`, add a trailing cell after the `On hand` cell (`<TableCell className="num text-right">{quantityOnHand}</TableCell>`):

```tsx
        <TableCell className="num text-right">{quantityOnHand}</TableCell>
        <TableCell className="text-right">
          {isQuantity ? (
            <PrintLabelButton
              target={{ kind: "sku", productId, sku }}
            />
          ) : null}
        </TableCell>
```

(c) Bump the expanded-row `colSpan` from `6` to `7`:

```tsx
          <TableCell colSpan={7} className="bg-muted/30">
```

(d) In the SERIALIZED drill-down units table, change the existing button:

```tsx
                        <PrintLabelButton
                          unitId={u.id}
                          serial={u.supplier_serial}
                        />
```

to:

```tsx
                        <PrintLabelButton
                          target={{
                            kind: "unit",
                            unitId: u.id,
                            serial: u.supplier_serial,
                          }}
                        />
```

- [ ] **Step 3: Update `products.tsx` (QUANTITY-row SKU button)**

In `frontend/src/routes/_layout/products.tsx`:

(a) Add the import after the existing `EmptyState` import:

```tsx
import { PrintLabelButton } from "@/components/PrintLabelButton"
```

(b) In the catalog table header, add a `Labels` head after the `History` head:

```tsx
                <TableHead className="text-right">History</TableHead>
                <TableHead className="text-right">Labels</TableHead>
```

(c) In the catalog row, add a trailing cell after the `PriceHistoryDialog` cell:

```tsx
                  <TableCell className="text-right">
                    <PriceHistoryDialog productId={p.id} sku={p.sku} />
                  </TableCell>
                  <TableCell className="text-right">
                    {(p.tracking_mode ?? "QUANTITY") === "QUANTITY" ? (
                      <PrintLabelButton
                        target={{ kind: "sku", productId: p.id, sku: p.sku }}
                      />
                    ) : null}
                  </TableCell>
```

- [ ] **Step 4: Lint + full typecheck**

Run (from `frontend/`):

```bash
bunx biome check src/routes/_layout/receive.tsx src/routes/_layout/stock.tsx src/routes/_layout/products.tsx
bunx tsc --noEmit
```

Expected: biome clean on the three files; `tsc` exits 0 (all call sites now use the `target` prop).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/_layout/receive.tsx frontend/src/routes/_layout/stock.tsx frontend/src/routes/_layout/products.tsx
git commit -m "feat(stock): print SKU labels from receive, stock, and catalog

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Full verification + SDK sync + code review

**Files:** `frontend/src/client/**` (regenerated only)

- [ ] **Step 1: Full backend suite + strict typecheck**

Run (from `backend/`):

```bash
bash scripts/test.sh
mypy app
```

Expected: all tests PASS; mypy `Success: no issues found`.

- [ ] **Step 2: Regenerate the SDK (keep the generated client in sync)**

The new `GET /products/{id}/label.pdf` route changes the OpenAPI schema. The app bare-fetches label PDFs so it does not depend on the generated method, but regenerate so the committed SDK matches and pre-commit stays quiet. Ensure the dev stack is running (`docker compose watch`), then run (from `frontend/`):

```bash
bun run generate-client
```

Expected: `src/client/**` updates to include the new `readSkuLabel`/label method (typed `unknown`). If the generator can't reach the backend, this step is non-blocking for functionality — note it and move on.

- [ ] **Step 3: Frontend lint + typecheck (whole app)**

Run (from `frontend/`):

```bash
bunx biome check src
bunx tsc --noEmit
```

Expected: clean.

- [ ] **Step 4: Commit any SDK regen**

```bash
git add frontend/src/client
git commit -m "chore(client): regenerate SDK for SKU label endpoint

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

(Skip this commit if `git status` shows no changes under `frontend/src/client`.)

- [ ] **Step 5: Dispatch code review (CLAUDE.md §5 stage 5)**

Invoke `superpowers:requesting-code-review`, then dispatch in parallel via the Agent tool, **both with `model: "opus"` (Opus 4.8 — standing preference for ecc agents):**
- `ecc:fastapi-reviewer` — `backend/app/services/barcode.py`, `backend/app/api/routes/receipts.py`, `backend/app/api/routes/products.py` + their tests.
- `ecc:react-reviewer` — `frontend/src/lib/print-pdf.ts`, `frontend/src/components/PrintLabelButton.tsx`, and the three route files.

(`ecc:database-reviewer` / `ecc:security-reviewer` are **not** required — no schema, ledger, money, or auth change.)

- [ ] **Step 6: Address review findings**

Apply fixes via `superpowers:receiving-code-review` (verify each suggestion before implementing); re-run the relevant tests from Steps 1–3 after any change, then commit.

---

## Self-Review (completed during planning)

- **Spec coverage:** D1 raw-sku QR → Task 3 (`qr_value=product.sku`); D2 reuse `_unit_qr_drawing`/ECC-M/60×30mm → Task 1 (`_draw_label_page` reuses `_unit_qr_drawing`, untouched); D3 one-label-per-page N pages → Task 1 (`render_label_sheet` loop); D4 `1≤qty≤1000` → Tasks 2/3 (`Query(ge=1, le=1000)`) + Task 4 (client clamp/validate); D5 unified identical button + serialized `?qty` → Task 2 + Task 4 + Task 5; D6 both-roles access → Task 3 (`Depends(get_current_user)`, `test_staff_can_fetch_sku_label`); D7 review scope → Task 6 (fastapi + react reviewers only, Opus 4.8). Placements (receive/stock/catalog) → Task 5.
- **Placeholder scan:** none — every code/command step shows full content.
- **Type/name consistency:** `render_label_sheet(*, qr_value, line1, line2, qty=1)` defined in Task 1 is called identically in Tasks 2–3; `render_unit_label(*, castranova_barcode, caption)` signature preserved (Task 1) so `test_unit_label.py`'s pinned-signature guard and the receipts call contract still hold; `PrintLabelButton({ target, defaultQty })` + `PrintLabelTarget` defined in Task 4 match every call site updated in Task 5; `openAuthedPdf(path) → PrintPdfResult` defined in Task 4 is consumed once, in `PrintLabelButton`; `_page_count` helper defined in each backend test file that uses it.
- **No-migration check:** confirmed — no `models.py`/Alembic change in any task; `crud.get_product` already exists (`crud.py:420`).
