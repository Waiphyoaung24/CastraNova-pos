# Sale Receipt A4 Redesign — Design

**Date:** 2026-06-25
**Status:** Approved (brainstorm)
**Area:** Backend receipt PDF rendering (FR-007)

## Goal

Redesign the sale receipt PDF from the current minimal A6 list into a bordered,
invoice-style A4 document modeled on the reference (`Screenshot 2026-06-25
140206.jpg`): a gridded line-item table with `NO · DESCRIPTION · QTY · PER UNIT
· TOTAL AMOUNT` columns, a `GRAND TOTAL` row, a CastraNova logo header, and a
faint logo watermark behind the table.

## Scope

**Changed:**
- `backend/app/services/receipt_pdf.py` — rewrite `render_sale_receipt`.
- `backend/app/assets/` (new) — two committed, pre-generated logo PNGs.
- `backend/tests/services/test_receipt_pdf.py` — update assertions for A4 +
  table content.

**Unchanged (already correct):**
- `backend/app/api/routes/sales.py` `read_sale_receipt` — still resolves data
  via `crud.get_sale_receipt_data` and streams the returned bytes.
- `crud.get_sale_receipt_data` / `SaleReceiptData` — signature unchanged.
- Frontend (`print-pdf.ts`, the receipt button) — opens the PDF blob; no change.

The function keeps its exact signature:

```python
render_sale_receipt(
    *, sale_id: str, sold_at: str, customer_name: str,
    sold_by: str, lines: list[tuple[str, int, Decimal]], total_thb: Decimal,
) -> bytes
```

## Page & Layout

Page size: **A4 portrait**. Layout top to bottom:

1. **Logo header** — CastraNova wordmark+wings centered at the top
   (print-friendly, transparent background), scaled to ~60 mm wide. "Sales
   Receipt" centered beneath it.
2. **Metadata block** — left-aligned, below the header:
   - `Sale #` — first 8 chars of `sale_id`.
   - `Date` — `sold_at` (an ISO string) reformatted to a readable
     `25 Jun 2026, 14:02`. If it cannot be parsed, fall back to the raw string.
   - `Customer` — `customer_name`.
   - `Sold by` — `sold_by`.
3. **Line-item table** (bordered, full gridlines):

   | NO | DESCRIPTION | QTY | PER UNIT | TOTAL AMOUNT |
   |----|-------------|-----|----------|--------------|

   - Header row: bold, light-gray shaded background, gridlines.
   - `NO`: 1-based row index.
   - `DESCRIPTION`: the `label` from each line tuple (wraps within the column;
     no mid-word truncation).
   - `QTY`: `qty`, centered.
   - `PER UNIT`: `price`, right-aligned, comma-grouped, 2 decimals.
   - `TOTAL AMOUNT`: `qty * price`, right-aligned, comma-grouped, 2 decimals.
4. **GRAND TOTAL row** — final table row, bold, label spanning the first four
   columns, `total_thb` in the TOTAL AMOUNT column (comma-grouped, 2 decimals,
   ` THB` suffix).
5. **Watermark** — faint grayscale CastraNova logo, centered on the page behind
   the table.

## Implementation Approach

- **Table rendering:** use reportlab `platypus` (`SimpleDocTemplate`, `Table`,
  `TableStyle`, `Paragraph`, `Spacer`) instead of manual `canvas.drawString`
  grid drawing. `TableStyle` provides the borders, header shading, and
  alignment declaratively. `Paragraph` in the DESCRIPTION column gives free word
  wrapping.
- **Logo + watermark:** drawn in an `onFirstPage`/`onPage` callback on the
  `SimpleDocTemplate`. The watermark is painted first (background), the logo
  header is drawn in the top margin band, and the flowables (metadata + table)
  render on top. Column widths and the top frame margin leave room for the logo
  band.
- **Logo assets:** the source `frontend/public/assets/images/castranova-logo-trimmed.png`
  is gold-on-black — unusable directly on white paper. Pre-generate two PNGs
  **once** with Pillow and commit them (no runtime image processing):
  - `backend/app/assets/castranova-logo-header.png` — transparent background
    (black pixels made transparent) for the header.
  - `backend/app/assets/castranova-logo-watermark.png` — light grayscale / low
    opacity for the watermark.
  The generation step is a throwaway script run during implementation; only the
  output PNGs are committed. Asset paths are resolved relative to the module
  file so they work inside the backend container.

## Defaults (locked)

- **Amounts:** comma-grouped, **2 decimals** (e.g. `49,900.00`). The reference
  shows no decimals; 2 decimals chosen for money accuracy.
- **Sale ID:** short form, first 8 chars (user asked to keep Sale ID; reference
  has none).
- **Date:** `25 Jun 2026, 14:02` readable format, raw-string fallback on parse
  failure.

## Error Handling

- Empty `lines`: render the table header + GRAND TOTAL row with no item rows
  (total may be `0.00`); never crash.
- Missing/unparseable `sold_at`: show the raw string.
- Long `DESCRIPTION`: wraps within the column (Paragraph), no truncation.
- Logo asset missing at runtime: skip the image draw (header text title +
  table still render); do not raise. The committed assets make this a
  belt-and-suspenders guard.

## Testing

Update `backend/tests/services/test_receipt_pdf.py`:
- Returns non-empty bytes starting with `%PDF`.
- Page size is A4 (assert via the rendered page mediabox, or by checking the
  PDF is produced without the A6 dimensions — extract text with the existing
  approach if one is present).
- Rendered text includes a known line label, a formatted amount, and
  `GRAND TOTAL` / the total.
- Handles the empty-`lines` case without raising.

Run: `bash scripts/test.sh` (or `pytest backend/tests/services/test_receipt_pdf.py`).

## Out of Scope

- Configurable business name/address/letterhead (no such data exists; not
  requested).
- Switching the watermark/decimals to match the reference exactly (defaults
  locked above; trivially adjustable later).
- Any change to how the receipt is fetched or displayed in the frontend.
