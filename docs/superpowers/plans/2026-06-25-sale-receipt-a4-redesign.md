# Sale Receipt A4 Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the sale receipt PDF from a minimal A6 list into an A4 invoice-style document with a CastraNova logo header, sale metadata, a bordered `NO / DESCRIPTION / QTY / PER UNIT / TOTAL AMOUNT` table, a GRAND TOTAL row, and a faint logo watermark.

**Architecture:** All work is in `backend/app/services/receipt_pdf.py` plus two committed logo PNG assets. The renderer uses reportlab `platypus` (`SimpleDocTemplate` + `Table`/`TableStyle`) for the bordered grid and an `onPage` callback to paint the watermark and header logo. The route, CRUD, `SaleReceiptData`, and frontend are unchanged — `render_sale_receipt` keeps its exact signature.

**Tech Stack:** Python, reportlab 4.5.1 (`platypus`, already a dep), Pillow 12.2.0 (already installed in the backend image), pytest.

## Global Constraints

- `render_sale_receipt` signature MUST stay exactly: `*, sale_id: str, sold_at: str, customer_name: str, sold_by: str, lines: list[tuple[str, int, Decimal]], total_thb: Decimal` returning `bytes`. (Enforced by `test_receipt_pdf_signature_has_no_cost_parameter` / `..._lines_tuple_has_no_cost_position` — a security guard against leaking cost/margin data. Do NOT add parameters.)
- `lines` element type stays exactly `tuple[str, int, Decimal]` (label, qty, price). No 4th position.
- Page size: A4 portrait.
- Amounts: comma-grouped, 2 decimals (e.g. `49,900.00`). Total carries a ` THB` suffix.
- Sale ID shown as first 8 chars only.
- Date: `25 Jun 2026, 14:02`; fall back to the raw string if `sold_at` is unparseable.
- No new pip dependency — reportlab and Pillow are already present.
- All user-supplied strings (`customer_name`, `sold_by`, line `label`) MUST be XML-escaped before going into a reportlab `Paragraph` (a `&` or `<` in a name otherwise breaks rendering).
- Logo assets resolved relative to the module: `Path(__file__).resolve().parent.parent / "assets"` → `backend/app/assets/`.

---

### Task 1: Generate and commit the logo assets

The source `frontend/public/assets/images/castranova-logo-trimmed.png` is gold-on-**black** — a black box on white paper. Produce two derived PNGs (black → transparent header logo; faint watermark) with Pillow and commit them. The generation is a one-time step; only the output PNGs are committed.

**Files:**
- Create: `backend/app/assets/castranova-logo-header.png` (generated)
- Create: `backend/app/assets/castranova-logo-watermark.png` (generated)

**Interfaces:**
- Produces: two RGBA PNGs at the paths above, consumed by Task 3.

- [ ] **Step 1: Create the assets directory on the host**

Run:
```bash
mkdir -p backend/app/assets
```

- [ ] **Step 2: Copy the source logo into the backend container**

Run:
```bash
docker compose cp frontend/public/assets/images/castranova-logo-trimmed.png backend:/tmp/logo-src.png
```
Expected: no error (file copied).

- [ ] **Step 3: Generate the two PNGs inside the container (has Pillow)**

Run:
```bash
docker compose exec -T backend python - <<'PY'
from PIL import Image
src = Image.open("/tmp/logo-src.png").convert("RGBA")
# Near-black background -> transparent; keep the gold wordmark/wings.
header = [(r, g, b, 0) if (r < 40 and g < 40 and b < 40) else (r, g, b, a)
         for (r, g, b, a) in src.getdata()]
src.putdata(header)
src.save("/tmp/castranova-logo-header.png")
# Watermark: same logo, faint (10% alpha). 0.10 is the tuning knob for faintness.
wm = src.copy()
wm.putdata([(r, g, b, int(a * 0.10)) for (r, g, b, a) in src.getdata()])
wm.save("/tmp/castranova-logo-watermark.png")
print("generated", src.size)
PY
```
Expected: prints `generated (W, H)`.

- [ ] **Step 4: Copy the generated PNGs back to the working tree**

Run:
```bash
docker compose cp backend:/tmp/castranova-logo-header.png backend/app/assets/castranova-logo-header.png
docker compose cp backend:/tmp/castranova-logo-watermark.png backend/app/assets/castranova-logo-watermark.png
```

- [ ] **Step 5: Verify the assets are valid RGBA PNGs**

Run:
```bash
docker compose cp backend/app/assets/castranova-logo-header.png backend:/tmp/v-header.png
docker compose exec -T backend python -c "from PIL import Image; h=Image.open('/tmp/v-header.png'); print(h.mode, h.size); assert h.mode=='RGBA' and h.size[0]>50"
```
Expected: prints `RGBA (W, H)` with width > 50, no assertion error.

- [ ] **Step 6: Commit**

```bash
git add backend/app/assets/castranova-logo-header.png backend/app/assets/castranova-logo-watermark.png
git commit -m "assets(receipt): print-friendly CastraNova logo + watermark PNGs"
```

---

### Task 2: A4 table renderer (no images yet)

Rewrite `render_sale_receipt` to emit an A4 PDF with the metadata block, the bordered 5-column table, and the GRAND TOTAL row, using reportlab `platypus`. Logo/watermark come in Task 3. The existing signature-guard tests must keep passing; add new tests for A4 size and the empty-lines case.

**Files:**
- Modify: `backend/app/services/receipt_pdf.py` (full rewrite of the module body below)
- Test: `backend/tests/services/test_receipt_pdf.py` (add 2 tests; keep the existing 4)

**Interfaces:**
- Consumes: nothing new (same inputs as today).
- Produces: `render_sale_receipt(...) -> bytes` — A4 PDF; `_fmt_amount(Decimal) -> str`, `_fmt_date(str) -> str` module helpers (used by Task 3 unchanged).

- [ ] **Step 1: Add the failing tests**

Add to `backend/tests/services/test_receipt_pdf.py`:
```python
def test_receipt_pdf_is_a4() -> None:
    """The receipt renders at A4 (MediaBox ~595x842pt), not the old A6."""
    pdf_bytes = render_sale_receipt(
        sale_id="test-sale-a4",
        sold_at="2026-06-25T14:02:00",
        customer_name="Walk-in",
        sold_by="admin@example.com",
        lines=[("Compressor Model X", 1, Decimal("1000.00"))],
        total_thb=Decimal("1000.00"),
    )
    # ponytail: grep the MediaBox bytes instead of adding a PDF-parser dep.
    # A4 = 595.27 x 841.89 pt; the page dict is uncompressed plain text.
    assert b"841.8" in pdf_bytes and b"595.2" in pdf_bytes


def test_receipt_pdf_empty_lines_does_not_crash() -> None:
    """A sale with no resolvable lines still renders header + GRAND TOTAL."""
    pdf_bytes = render_sale_receipt(
        sale_id="test-sale-empty",
        sold_at="2026-06-25T14:02:00",
        customer_name="Walk-in",
        sold_by="admin@example.com",
        lines=[],
        total_thb=Decimal("0.00"),
    )
    assert pdf_bytes[:4] == b"%PDF"
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `docker compose exec -T backend pytest tests/services/test_receipt_pdf.py::test_receipt_pdf_is_a4 -v`
Expected: FAIL (current renderer emits A6, so `595.2`/`841.8` not present).

- [ ] **Step 3: Rewrite the renderer module**

Replace the entire contents of `backend/app/services/receipt_pdf.py` with:
```python
"""Sale receipt PDF rendering (FR-007).

A4 invoice-style receipt: CastraNova logo header, sale metadata, a bordered
line-item table (NO / DESCRIPTION / QTY / PER UNIT / TOTAL AMOUNT), a GRAND
TOTAL row, and a faint logo watermark behind the table. Rendered on demand
from the persisted sale + sale_line rows.
"""

import io
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors  # type: ignore[import-untyped]
from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]
from reportlab.lib.styles import (  # type: ignore[import-untyped]
    ParagraphStyle,
    getSampleStyleSheet,
)
from reportlab.lib.units import mm  # type: ignore[import-untyped]
from reportlab.platypus import (  # type: ignore[import-untyped]
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
_LOGO_HEADER = _ASSETS / "castranova-logo-header.png"
_LOGO_WATERMARK = _ASSETS / "castranova-logo-watermark.png"


def _fmt_amount(value: Decimal) -> str:
    """Comma-grouped THB with 2 decimals, e.g. ``49,900.00``."""
    return f"{value:,.2f}"


def _fmt_date(sold_at: str) -> str:
    """ISO string -> ``25 Jun 2026, 14:02``; raw string on parse failure."""
    try:
        dt = datetime.fromisoformat(sold_at)
    except ValueError:
        return sold_at
    return dt.strftime("%d %b %Y, %H:%M")


def render_sale_receipt(
    *,
    sale_id: str,
    sold_at: str,
    customer_name: str,
    sold_by: str,
    lines: list[tuple[str, int, Decimal]],
    total_thb: Decimal,
) -> bytes:
    """Return a one-page A4 receipt PDF. ``lines`` are (label, qty, price)."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        topMargin=46 * mm,  # clears the logo header band drawn in the margin
        bottomMargin=18 * mm,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        title="Sales Receipt",
    )

    styles = getSampleStyleSheet()
    cell = ParagraphStyle("cell", parent=styles["Normal"], fontSize=9, leading=12)
    meta = ParagraphStyle("meta", parent=styles["Normal"], fontSize=9, leading=15)

    story: list = []
    for label, value in (
        ("Sale #", sale_id[:8]),
        ("Date", _fmt_date(sold_at)),
        ("Customer", customer_name),
        ("Sold by", sold_by),
    ):
        story.append(Paragraph(f"<b>{label}</b>&nbsp;&nbsp;{escape(value)}", meta))
    story.append(Spacer(1, 8 * mm))

    data: list = [["NO", "DESCRIPTION", "QTY", "PER UNIT", "TOTAL AMOUNT"]]
    for i, (label, qty, price) in enumerate(lines, start=1):
        data.append(
            [
                str(i),
                Paragraph(escape(label), cell),
                str(qty),
                _fmt_amount(price),
                _fmt_amount(Decimal(qty) * price),
            ]
        )
    data.append(["GRAND TOTAL", "", "", "", f"{_fmt_amount(total_thb)} THB"])
    last = len(data) - 1

    table = Table(
        data,
        colWidths=[12 * mm, 90 * mm, 16 * mm, 30 * mm, 36 * mm],
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),  # NO
                ("ALIGN", (2, 0), (2, -1), "CENTER"),  # QTY
                ("ALIGN", (3, 0), (4, -1), "RIGHT"),  # PER UNIT, TOTAL AMOUNT
                # Header row
                ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.9)),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                # GRAND TOTAL row: merge first four cells, bold, right-aligned label
                ("SPAN", (0, last), (3, last)),
                ("FONTNAME", (0, last), (-1, last), "Helvetica-Bold"),
                ("ALIGN", (0, last), (3, last), "RIGHT"),
                ("ALIGN", (4, last), (4, last), "RIGHT"),
            ]
        )
    )
    story.append(table)

    doc.build(story)
    return buf.getvalue()
```

- [ ] **Step 4: Run the full receipt test file**

Run: `docker compose exec -T backend pytest tests/services/test_receipt_pdf.py -v`
Expected: all 6 tests PASS (4 existing signature/PDF guards + the 2 new ones).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/receipt_pdf.py backend/tests/services/test_receipt_pdf.py
git commit -m "feat(receipt): A4 bordered line-item table renderer"
```

---

### Task 3: Header logo + faint watermark

Add the page furniture: paint the faint watermark behind the flowables and the print-friendly logo + "Sales Receipt" title in the top margin, via an `onPage` callback. Degrade gracefully if an asset is missing.

**Files:**
- Modify: `backend/app/services/receipt_pdf.py` (add `ImageReader` import, a `_draw_page_furniture` callback, wire it into `doc.build`)
- Test: `backend/tests/services/test_receipt_pdf.py` (add 1 test)

**Interfaces:**
- Consumes: the two PNGs from Task 1 (`_LOGO_HEADER`, `_LOGO_WATERMARK`).
- Produces: no signature change; the PDF now embeds image XObjects.

- [ ] **Step 1: Add the failing test**

Add to `backend/tests/services/test_receipt_pdf.py`:
```python
def test_receipt_pdf_embeds_logo_image() -> None:
    """With assets present, the rendered PDF embeds an image (logo/watermark)."""
    pdf_bytes = render_sale_receipt(
        sale_id="test-sale-img",
        sold_at="2026-06-25T14:02:00",
        customer_name="Walk-in",
        sold_by="admin@example.com",
        lines=[("Compressor Model X", 1, Decimal("1000.00"))],
        total_thb=Decimal("1000.00"),
    )
    assert b"/Image" in pdf_bytes, "expected an embedded image XObject"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `docker compose exec -T backend pytest tests/services/test_receipt_pdf.py::test_receipt_pdf_embeds_logo_image -v`
Expected: FAIL (renderer draws no images yet).

- [ ] **Step 3: Add the ImageReader import**

In `backend/app/services/receipt_pdf.py`, add below the existing `from reportlab.lib.units import mm` import line:
```python
from reportlab.lib.utils import ImageReader  # type: ignore[import-untyped]
```

- [ ] **Step 4: Add the page-furniture callback**

Insert this function just above `def render_sale_receipt(`:
```python
def _draw_logo(canvas: object, path: Path, x: float, y: float, width: float) -> None:
    """Draw ``path`` at (x, y) scaled to ``width`` preserving aspect ratio."""
    img = ImageReader(str(path))
    iw, ih = img.getSize()
    height = width * ih / iw
    canvas.drawImage(  # type: ignore[attr-defined]
        img, x, y, width=width, height=height, mask="auto", preserveAspectRatio=True
    )


def _draw_page_furniture(canvas: object, doc: object) -> None:
    """onPage callback: faint watermark (behind) + logo header in the top margin.

    Missing assets are skipped so the table still renders (belt-and-suspenders;
    the assets are committed)."""
    page_w, page_h = A4
    if _LOGO_WATERMARK.exists():
        wm_w = 120 * mm
        img = ImageReader(str(_LOGO_WATERMARK))
        iw, ih = img.getSize()
        wm_h = wm_w * ih / iw
        _draw_logo(
            canvas, _LOGO_WATERMARK, (page_w - wm_w) / 2, (page_h - wm_h) / 2, wm_w
        )
    if _LOGO_HEADER.exists():
        logo_w = 60 * mm
        img = ImageReader(str(_LOGO_HEADER))
        iw, ih = img.getSize()
        logo_h = logo_w * ih / iw
        top = page_h - 12 * mm - logo_h
        _draw_logo(canvas, _LOGO_HEADER, (page_w - logo_w) / 2, top, logo_w)
        canvas.setFont("Helvetica", 11)  # type: ignore[attr-defined]
        canvas.drawCentredString(page_w / 2, top - 6 * mm, "Sales Receipt")  # type: ignore[attr-defined]
```

- [ ] **Step 5: Wire the callback into the build call**

In `render_sale_receipt`, change the final build line from:
```python
    doc.build(story)
```
to:
```python
    doc.build(
        story,
        onFirstPage=_draw_page_furniture,
        onLaterPages=_draw_page_furniture,
    )
```

- [ ] **Step 6: Run the full receipt test file**

Run: `docker compose exec -T backend pytest tests/services/test_receipt_pdf.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 7: Visual check (manual)**

Generate a real receipt and eyeball it:
```bash
docker compose exec -T backend python - <<'PY'
from decimal import Decimal
from app.services.receipt_pdf import render_sale_receipt
pdf = render_sale_receipt(
    sale_id="9134ad7c-7eba-4231-ba12-e5732e067912",
    sold_at="2026-06-25T14:02:00",
    customer_name="Tom & Jerry Co.",
    sold_by="admin@example.com",
    lines=[
        ("R 404A gas", 8, Decimal("650000")),
        ("KH-402 A3 Condenser", 1, Decimal("3654000")),
        ("Hongsen sight glass 7/8", 3, Decimal("85260")),
    ],
    total_thb=Decimal("9388780"),
)
open("/tmp/receipt-preview.pdf", "wb").write(pdf)
print("wrote", len(pdf), "bytes")
PY
docker compose cp backend:/tmp/receipt-preview.pdf backend/app/assets/../../../receipt-preview.pdf
```
Open `receipt-preview.pdf` at the repo root and confirm: A4, logo at top, "Sales Receipt" title, metadata block, bordered table with all 5 columns, GRAND TOTAL row, faint watermark, ampersand in the customer name renders correctly. Then delete the preview: `rm receipt-preview.pdf`.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/receipt_pdf.py backend/tests/services/test_receipt_pdf.py
git commit -m "feat(receipt): logo header and faint watermark"
```

---

## Verification (whole feature)

- [ ] `docker compose exec -T backend pytest tests/services/test_receipt_pdf.py -v` → 7 passing.
- [ ] `docker compose exec -T backend pytest tests/ -q` → no regressions in the broader suite (sales/audit receipt tests still green).
- [ ] mypy/ruff via pre-commit pass on the changed file.
- [ ] Manual visual check from Task 3 Step 7 looks like the reference.

## Self-Review Notes

- **Spec coverage:** A4 (Task 2) ✓; 5-column bordered table (Task 2) ✓; GRAND TOTAL row (Task 2) ✓; metadata block with all 4 fields + readable date + short id (Task 2) ✓; logo header (Task 3) ✓; faint watermark (Task 3) ✓; 2-decimal THB (Task 2 `_fmt_amount`) ✓; assets pre-generated & committed (Task 1) ✓; empty-lines + bad-date + long-label + missing-asset error handling (Tasks 2/3) ✓; signature unchanged (Global Constraints; existing guard tests) ✓.
- **Type consistency:** `_fmt_amount`/`_fmt_date`/`_draw_logo`/`_draw_page_furniture` names are consistent across tasks; `_LOGO_HEADER`/`_LOGO_WATERMARK` defined in Task 2 module, used in Task 3.
- **No new deps:** reportlab + Pillow already present (verified in the backend image).
