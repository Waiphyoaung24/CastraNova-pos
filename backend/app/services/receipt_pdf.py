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
from typing import Any
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

    story: list[Any] = []
    for label, value in (
        ("Sale #", sale_id[:8]),
        ("Date", _fmt_date(sold_at)),
        ("Customer", customer_name),
        ("Sold by", sold_by),
    ):
        story.append(Paragraph(f"<b>{label}</b>&nbsp;&nbsp;{escape(value)}", meta))
    story.append(Spacer(1, 8 * mm))

    data: list[Any] = [["NO", "DESCRIPTION", "QTY", "PER UNIT", "TOTAL AMOUNT"]]
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
        # Sum = 174 mm = A4 width (210) minus left+right margins (18+18); any
        # wider overflows the printable frame and clips the TOTAL column.
        colWidths=[11 * mm, 75 * mm, 14 * mm, 36 * mm, 38 * mm],
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
