# QR Code Unit Labels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Code128 barcode on serialized-unit labels with a QR symbol of the same `castranova_barcode` value, and pin the camera fallback to read `{QR, Code128}`.

**Architecture:** Backend `render_unit_label` draws a ReportLab-native vector QR (new `_unit_qr_drawing` helper) instead of Code128 — same canvas, same two text lines, identical function signature, so the route is untouched. Frontend `CameraScanFallback` restricts the `html5-qrcode` decoder to QR + Code128 (old labels still scan). No DB migration, no `models.py`/schema change, no SDK regen.

**Tech Stack:** Python · ReportLab (`reportlab.graphics.barcode.qr.QrCodeWidget`, `renderPDF`, `renderPM`) · pytest · React/TypeScript · `html5-qrcode` 2.3.8 · `opencv-python-headless` (test-only, optional).

Spec: `docs/superpowers/specs/2026-06-16-castranova-qr-unit-label-design.md`

---

## File Structure

- **Modify** `backend/app/services/barcode.py` — swap Code128 → QR; add private `_unit_qr_drawing` helper. Keep `render_unit_label(*, castranova_barcode, caption) -> bytes`.
- **Create** `backend/tests/services/test_unit_label.py` — structural test (always-on, zero-dep) + decode round-trip (optional `cv2`/`renderPM`, `importorskip`).
- **Modify** `backend/pyproject.toml` — add `opencv-python-headless` to the `dev` dependency-group (test-only decoder).
- **Modify** `frontend/src/components/CameraScanFallback.tsx` — restrict decoder formats in the `Html5Qrcode` **constructor**.
- **Untouched:** `backend/app/api/routes/receipts.py` (signature unchanged), `models.py`, migrations, `frontend/src/client/**`, `useScanner.ts`, `ScanInput.tsx`.

**Test-strategy decision (resolves the spec's one open item):** the repo deliberately avoids heavy PDF-parsing deps (see `tests/services/test_receipt_pdf.py`), so the *always-on* guard is a **structural** assertion on the QR widget (catches wrong-value / symbology-revert with zero deps). The real **decode round-trip** is an *optional* test that rasterizes the QR **Drawing** (not the PDF) via reportlab's own `renderPM` and decodes with `opencv`'s `QRCodeDetector` — one wheel-installable dep, no native binary, no PDF parser. It `importorskip`s cleanly so the suite still runs where the decoder is absent.

---

## Task 1: Backend — render QR instead of Code128 (TDD)

**Files:**
- Modify: `backend/pyproject.toml` (dev group)
- Modify: `backend/app/services/barcode.py`
- Test: `backend/tests/services/test_unit_label.py` (create)

- [ ] **Step 1: Add the optional test decoder to the dev dependency-group**

In `backend/pyproject.toml`, add one line to `[dependency-groups] dev` (after `"coverage<8.0.0,>=7.4.3",`):

```toml
    "opencv-python-headless<5.0.0,>=4.9.0",
```

Then sync (run from `backend/`):

```bash
uv sync
```

Expected: resolves and installs `opencv-python-headless` + its `numpy` dependency.

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/services/test_unit_label.py`:

```python
"""Unit tests for render_unit_label / _unit_qr_drawing (FR-005, QR labels).

Two layers:
- Always-on structural test: the QR Drawing carries the exact value at ECC
  level M (catches wrong-value or symbology-revert regressions with zero deps).
- Optional decode round-trip: rasterize the QR Drawing and decode it back,
  proving real scannability. Skipped if the optional decoder (opencv) or the
  reportlab raster backend (renderPM) is unavailable, so the suite still runs.
"""

import pytest

from app.services.barcode import _unit_qr_drawing, render_unit_label

_BARCODE = "CN-A1B2C3D4E5F6A7B8"


def test_unit_qr_drawing_encodes_exact_value() -> None:
    drawing = _unit_qr_drawing(_BARCODE)
    widgets = [c for c in drawing.contents if hasattr(c, "value")]
    assert len(widgets) == 1, "expected exactly one QR widget in the drawing"
    widget = widgets[0]
    assert widget.value == _BARCODE
    assert widget.barLevel == "M"


def test_render_unit_label_returns_valid_pdf() -> None:
    pdf = render_unit_label(castranova_barcode=_BARCODE, caption="SN-XYZ")
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 100


def test_qr_round_trips_through_a_decoder() -> None:
    """Rasterize the QR and decode it — proves the label is actually scannable."""
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    render_pm = pytest.importorskip("reportlab.graphics.renderPM")

    drawing = _unit_qr_drawing(_BARCODE, size=200)  # 200pt → dense enough to decode
    png = render_pm.drawToString(drawing, fmt="PNG", dpi=300)
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
    decoded, _points, _qr = cv2.QRCodeDetector().detectAndDecode(img)
    assert decoded == _BARCODE
```

- [ ] **Step 3: Run the tests to verify they fail**

Run (from `backend/`):

```bash
pytest tests/services/test_unit_label.py -v
```

Expected: FAIL — `ImportError: cannot import name '_unit_qr_drawing' from 'app.services.barcode'`.

- [ ] **Step 4: Implement the QR rendering**

Replace the entire contents of `backend/app/services/barcode.py` with:

```python
"""QR label rendering for serialized units (FR-005).

Produces a small self-contained PDF label per piece so warehouse staff can
print/reprint on receive (the reprint-by-serial path covers a lost label,
S-lost-label). The label encodes the unit's castranova_barcode value as a QR
symbol; the same value is also printed human-readable for the manual fallback.
"""

import io

from reportlab.graphics import renderPDF  # type: ignore[import-untyped]
from reportlab.graphics.barcode.qr import QrCodeWidget  # type: ignore[import-untyped]
from reportlab.graphics.shapes import Drawing  # type: ignore[import-untyped]
from reportlab.lib.units import mm  # type: ignore[import-untyped]
from reportlab.pdfgen import canvas  # type: ignore[import-untyped]

# Compact label: ~ 60mm x 30mm.
_LABEL_W = 60 * mm
_LABEL_H = 30 * mm
# QR occupies a square on the left; the text block sits to its right.
_QR_SIZE = 20 * mm


def _unit_qr_drawing(value: str, size: float = _QR_SIZE) -> Drawing:
    """Return a `size`-square Drawing of `value` as a QR symbol (ECC level M).

    The widget's natural bounds are scaled to exactly fill `size` via the
    Drawing transform, so callers can place it at any (x, y) on a canvas.
    """
    widget = QrCodeWidget(value, barLevel="M")
    x0, y0, x1, y1 = widget.getBounds()
    w = x1 - x0
    h = y1 - y0
    drawing = Drawing(
        size,
        size,
        transform=[size / w, 0, 0, size / h, -size / w * x0, -size / h * y0],
    )
    drawing.add(widget)
    return drawing


def render_unit_label(*, castranova_barcode: str, caption: str) -> bytes:
    """Return a one-page PDF (bytes) with a QR symbol + human-readable text."""
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=(_LABEL_W, _LABEL_H))
    renderPDF.draw(_unit_qr_drawing(castranova_barcode), pdf, 3 * mm, 5 * mm)
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(26 * mm, 16 * mm, castranova_barcode)
    pdf.setFont("Helvetica", 6)
    pdf.drawString(26 * mm, 9 * mm, caption[:48])
    pdf.showPage()
    pdf.save()
    return buf.getvalue()
```

- [ ] **Step 5: Run the new tests to verify they pass**

Run (from `backend/`):

```bash
pytest tests/services/test_unit_label.py -v
```

Expected: PASS — all three tests, including `test_qr_round_trips_through_a_decoder` (decoded text equals `CN-A1B2C3D4E5F6A7B8`).

- [ ] **Step 6: Run the existing label tests to verify no regression**

Run (from `backend/`):

```bash
pytest tests/api/routes/test_receipts_serialized.py -v
```

Expected: PASS — including `test_label_pdf_returned_for_unit`, `test_staff_can_fetch_unit_label`, `test_unauthenticated_cannot_fetch_unit_label` (still `%PDF` + auth).

- [ ] **Step 7: Typecheck the changed module**

Run (from `backend/`):

```bash
mypy app/services/barcode.py
```

Expected: `Success: no issues found`.

- [ ] **Step 8: Commit**

```bash
git add backend/pyproject.toml backend/app/services/barcode.py backend/tests/services/test_unit_label.py backend/uv.lock
git commit -m "feat(stock): render serialized-unit labels as QR (was Code128)"
```

---

## Task 2: Frontend — pin camera fallback to QR + Code128

**Files:**
- Modify: `frontend/src/components/CameraScanFallback.tsx`

- [ ] **Step 1: Restrict the decoder formats**

In `frontend/src/components/CameraScanFallback.tsx`:

Change the import on line 1 from:

```tsx
import { Html5Qrcode } from "html5-qrcode"
```

to:

```tsx
import { Html5Qrcode, Html5QrcodeSupportedFormats } from "html5-qrcode"
```

Then change the constructor (currently `const scanner = new Html5Qrcode(readerId)`) to pass the format restriction. `formatsToSupport` belongs on the **`Html5Qrcode` constructor config** (`Html5QrcodeFullConfig`), not the `.start()` config:

```tsx
    const scanner = new Html5Qrcode(readerId, {
      formatsToSupport: [
        Html5QrcodeSupportedFormats.QR_CODE,
        Html5QrcodeSupportedFormats.CODE_128,
      ],
    })
```

Leave the `.start(...)` call (with `{ fps: 10, qrbox: 250 }`) and everything else unchanged.

- [ ] **Step 2: Lint and typecheck**

Run (from `frontend/`):

```bash
bunx biome check src/components/CameraScanFallback.tsx
bunx tsc --noEmit
```

Expected: biome reports no errors on the file; `tsc` exits 0 (the `formatsToSupport` field is valid on the constructor config type).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/CameraScanFallback.tsx
git commit -m "feat(scan): restrict camera fallback to QR + Code128"
```

**Manual / optional verification (not a blocking step):** the camera decode path needs a real camera feed, which can't be faked headlessly. Verify by hand: print or display a unit label from `GET /receipts/serialized/{unit_id}/label.pdf` and scan it with the in-app camera fallback — it should resolve the same `CN-…` value. (Optional stretch: an `ecc:e2e-runner` Playwright harness that feeds a generated QR PNG to `html5-qrcode`'s `scanFileV2` and asserts `decodedText` + `format.formatName === "QR_CODE"`.)

---

## Task 3: Full verification + code review

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend suite + strict typecheck**

Run (from `backend/`):

```bash
bash scripts/test.sh
mypy app
```

Expected: all tests PASS; mypy `Success: no issues found`.

- [ ] **Step 2: Frontend lint + typecheck**

Run (from `frontend/`):

```bash
bunx biome check src/components/CameraScanFallback.tsx
bunx tsc --noEmit
```

Expected: clean.

- [ ] **Step 3: Dispatch code review (CLAUDE.md stage 5)**

Invoke `superpowers:requesting-code-review`, and dispatch in parallel via the Agent tool:
- `ecc:fastapi-reviewer` — backend `barcode.py` + test.
- `ecc:react-reviewer` — `CameraScanFallback.tsx`.

(`ecc:database-reviewer` / `ecc:security-reviewer` are **not** required — no schema, ledger, money, or auth change.)

- [ ] **Step 4: Address any review findings**

Apply fixes via `superpowers:receiving-code-review` (verify each suggestion before implementing); re-run the relevant tests from Steps 1–2 after any change.

---

## Self-Review (completed during planning)

- **Spec coverage:** backend QR swap → Task 1; payload stays raw `CN-…` (no URL) → preserved by passing `castranova_barcode` unchanged in Task 1 Step 4; both text lines kept → Task 1 Step 4; camera `{QR, Code128}` → Task 2; decode round-trip test → Task 1 Step 2; old-label compatibility → covered by keeping Code128 enabled (Task 2) + 2D wedge (no code); no migration/SDK/model change → no such task exists, by design; review gate → Task 3.
- **Placeholder scan:** none — every code/command step shows full content.
- **Type/name consistency:** `_unit_qr_drawing(value, size=_QR_SIZE)` defined in Task 1 Step 4 is the exact symbol imported and called in Task 1 Step 2 (`size=200` override used in the decode test); `render_unit_label(*, castranova_barcode, caption)` signature matches the existing `receipts.py` call site.
