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
    pdf.drawString(8 * mm, y, f"Sale {sale_id}")
    y -= 4 * mm
    pdf.drawString(8 * mm, y, f"Date {sold_at}")
    y -= 8 * mm
    pdf.setFont("Helvetica", 8)
    for label, qty, price in lines:
        pdf.drawString(8 * mm, y, f"{label[:28]}")
        pdf.drawRightString(width - 8 * mm, y, f"{qty} x {price}")
        y -= 5 * mm
    y -= 3 * mm
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(8 * mm, y, "Total")
    pdf.drawRightString(width - 8 * mm, y, f"{total_thb} THB")
    pdf.showPage()
    pdf.save()
    return buf.getvalue()
