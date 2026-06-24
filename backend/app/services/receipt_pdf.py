"""Sale receipt PDF rendering (FR-007).

Minimal A6-ish receipt: header, line items (price), and totals. Rendered on
demand from the persisted sale + sale_line rows.
"""

import io
from decimal import Decimal

from reportlab.lib.pagesizes import A6  # type: ignore[import-untyped]
from reportlab.lib.units import mm  # type: ignore[import-untyped]
from reportlab.pdfgen import canvas  # type: ignore[import-untyped]


def render_sale_receipt(
    *,
    sale_id: str,
    sold_at: str,
    customer_name: str,
    sold_by: str,
    lines: list[tuple[str, int, Decimal]],
    total_thb: Decimal,
) -> bytes:
    """Return a one-page receipt PDF. ``lines`` are (label, quantity, price)."""
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A6)
    width, height = A6
    y = height - 12 * mm
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(8 * mm, y, "CastraNova POS — Receipt")
    pdf.setFont("Helvetica", 7)
    y -= 6 * mm
    pdf.drawString(8 * mm, y, f"Sale {sale_id[:8]}")
    y -= 4 * mm
    pdf.drawString(8 * mm, y, f"Date {sold_at}")
    y -= 4 * mm
    pdf.drawString(8 * mm, y, f"Customer {customer_name[:34]}")
    y -= 4 * mm
    pdf.drawString(8 * mm, y, f"Sold by {sold_by[:34]}")
    y -= 8 * mm
    # Each line item spans two rows: the full product name on its own row (so
    # long "Model · serial" / "Model (SKU)" labels are not cut mid-word), then
    # the quantity x unit price = line total right-aligned beneath it.
    for label, qty, price in lines:
        pdf.setFont("Helvetica", 8)
        pdf.drawString(8 * mm, y, label[:46])
        y -= 4 * mm
        pdf.setFont("Helvetica", 7)
        pdf.drawRightString(
            width - 8 * mm, y, f"{qty} x {price:,.2f} = {qty * price:,.2f}"
        )
        y -= 6 * mm
    y -= 1 * mm
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(8 * mm, y, "Total")
    pdf.drawRightString(width - 8 * mm, y, f"{total_thb:,.2f} THB")
    pdf.showPage()
    pdf.save()
    return buf.getvalue()
