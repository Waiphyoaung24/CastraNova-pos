"""Sale invoice PDF rendering (FR-007; black & gold redesign 2026-09-22).

A4 invoice on CastraNova letterhead: logo header over a gold rule, an INVOICE
pill, two gold boxes (Sold To / Invoice No + Date + Sold by), a gold-headed
line-item table (No / Description / Qty / Price per Unit / Amount), Sub Total
and a gold Total Amount row, and the gold-and-black wave along the foot.
Rendered on demand from the persisted sale + sale_line rows; carries no cost.
"""

import io
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from reportlab.lib import colors  # type: ignore[import-untyped]
from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]
from reportlab.lib.styles import (  # type: ignore[import-untyped]
    ParagraphStyle,
    getSampleStyleSheet,
)
from reportlab.lib.units import mm  # type: ignore[import-untyped]
from reportlab.lib.utils import ImageReader  # type: ignore[import-untyped]
from reportlab.platypus import (  # type: ignore[import-untyped]
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
_LOGO_HEADER = _ASSETS / "castranova-logo-header.png"
_FOOTER_WAVE = _ASSETS / "invoice-footer-wave.jpg"

# The app's brand gold (frontend --primary) with black text; pale gold for hairlines.
GOLD = colors.HexColor("#D4AF37")
GOLD_PALE = colors.HexColor("#E8D9A0")
GOLD_DARK = colors.HexColor("#8A6D1F")
INK = colors.HexColor("#0B0B0D")

# Invoices print the shop's wall clock, like every screen does via the
# browser; the DB stores UTC. ponytail: fixed zone, make it a setting if the
# shop ever spans zones.
SHOP_TZ = ZoneInfo("Asia/Bangkok")

_MARGIN = 16 * mm
_CONTENT_W = A4[0] - 2 * _MARGIN  # 178 mm
_HEADER_H = 40 * mm  # logo + rule + INVOICE pill
_WAVE_W = A4[0]
_WAVE_H = _WAVE_W * 192 / 1130  # asset aspect (1130x192)


def _fmt_amount(value: Decimal) -> str:
    """Comma-grouped THB with 2 decimals, e.g. ``49,900.00``."""
    return f"{value:,.2f}"


def _fmt_date(sold_at: str) -> str:
    """ISO string -> ``25 Jun 2026, 14:02`` in shop time; raw on parse failure."""
    try:
        dt = datetime.fromisoformat(sold_at)
    except ValueError:
        return sold_at
    if dt.tzinfo is not None:
        dt = dt.astimezone(SHOP_TZ)
    return dt.strftime("%d %b %Y, %H:%M")


def _draw_page_furniture(canvas: Any, doc: Any) -> None:
    """onPage callback: logo + gold rule + INVOICE pill in the top margin, the
    wave along the foot. Missing assets are skipped so the table still renders."""
    page_w, page_h = A4
    top = page_h - 12 * mm
    if _LOGO_HEADER.exists():
        logo_w = 52 * mm
        img = ImageReader(str(_LOGO_HEADER))
        iw, ih = img.getSize()
        logo_h = logo_w * ih / iw
        canvas.drawImage(
            img, _MARGIN, top - logo_h, width=logo_w, height=logo_h,
            mask="auto", preserveAspectRatio=True,
        )
    rule_y = page_h - _HEADER_H + 4 * mm  # clear of the wings above it
    canvas.setStrokeColor(GOLD_DARK)
    canvas.setLineWidth(1.2)
    canvas.line(_MARGIN, rule_y, page_w - _MARGIN, rule_y)
    # INVOICE pill, centred on the rule like the paper form.
    pill_w, pill_h = 40 * mm, 8 * mm
    canvas.setFillColor(GOLD)
    canvas.setStrokeColor(GOLD)
    canvas.roundRect(
        (page_w - pill_w) / 2, rule_y - pill_h / 2, pill_w, pill_h, 2 * mm, fill=1, stroke=0
    )
    canvas.setFillColor(INK)
    canvas.setFont("Helvetica-Bold", 11)
    canvas.drawCentredString(page_w / 2, rule_y - 1.4 * mm, "INVOICE")
    if _FOOTER_WAVE.exists():
        canvas.drawImage(
            ImageReader(str(_FOOTER_WAVE)), 0, 0, width=_WAVE_W, height=_WAVE_H,
            preserveAspectRatio=True,
        )
    canvas.setFillColor(colors.HexColor("#777777"))
    canvas.setFont("Helvetica", 7.5)
    canvas.drawRightString(page_w - _MARGIN, _WAVE_H + 3 * mm, f"Page {doc.page}")


def _gold_box(rows: list[tuple[str, str]], width: float) -> Table:
    """A rounded gold box of bold label / value rows (Sold To, Invoice No...)."""
    label = ParagraphStyle("box-label", fontName="Helvetica-Bold", fontSize=10, leading=14, textColor=INK)
    value = ParagraphStyle("box-value", fontName="Helvetica", fontSize=10, leading=14, textColor=INK)
    data = [[Paragraph(escape(k), label), Paragraph(escape(v), value)] for k, v in rows]
    box = Table(data, colWidths=[26 * mm, width - 26 * mm])
    box.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), GOLD),
                ("ROUNDEDCORNERS", [8, 8, 8, 8]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
            ]
        )
    )
    return box


def render_sale_receipt(
    *,
    sale_id: str,
    sold_at: str,
    customer_name: str,
    sold_by: str,
    lines: list[tuple[str, int, Decimal]],
    total_thb: Decimal,
) -> bytes:
    """Return an A4 invoice PDF. ``lines`` are (label, qty, price)."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        topMargin=_HEADER_H + 4 * mm,
        bottomMargin=_WAVE_H + 8 * mm,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        title=f"Invoice {sale_id[:8].upper()}",
    )
    styles = getSampleStyleSheet()
    cell = ParagraphStyle("cell", parent=styles["Normal"], fontSize=9.5, leading=12.5, textColor=INK)

    gap = 8 * mm
    box_w = (_CONTENT_W - gap) / 2
    header = Table(
        [
            [
                _gold_box([("Sold To", ""), ("Name", customer_name)], box_w),
                _gold_box(
                    [
                        ("Invoice No", sale_id[:8].upper()),
                        ("Date", _fmt_date(sold_at)),
                        ("Sold by", sold_by),
                    ],
                    box_w,
                ),
            ]
        ],
        colWidths=[box_w + gap, box_w],
    )
    header.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story: list[Any] = [header, Spacer(1, 7 * mm)]

    data: list[Any] = [["No", "Description", "Qty", "Price per Unit", "Amount"]]
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
    col_w = [12 * mm, 84 * mm, 14 * mm, 34 * mm, 34 * mm]  # = 178 mm content
    table = Table(data, colWidths=col_w, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                ("TEXTCOLOR", (0, 0), (-1, -1), INK),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),  # No
                ("ALIGN", (2, 0), (2, -1), "CENTER"),  # Qty
                ("ALIGN", (3, 0), (4, -1), "RIGHT"),  # money
                # Gold header, then quiet rows: no vertical lines, one pale
                # hairline between items, a firm gold line closing the list.
                ("BACKGROUND", (0, 0), (-1, 0), GOLD),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("LINEBELOW", (0, 1), (-1, -1), 0.5, GOLD_PALE),
                ("LINEBELOW", (0, -1), (-1, -1), 0.9, GOLD_DARK),
            ]
        )
    )
    story.append(table)

    # Totals stand apart from the items, right-aligned under the money columns.
    subtotal = sum((Decimal(q) * p for _, q, p in lines), Decimal("0"))
    totals = Table(
        [
            ["Sub Total", _fmt_amount(subtotal)],
            ["Total Amount (THB)", _fmt_amount(total_thb)],
        ],
        colWidths=[38 * mm, 30 * mm],
        hAlign="RIGHT",
    )
    totals.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                ("TEXTCOLOR", (0, 0), (-1, -1), INK),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 1), (-1, 1), 10.5),
                ("BACKGROUND", (0, 1), (-1, 1), GOLD),
                ("ROUNDEDCORNERS", [0, 0, 6, 6]),
            ]
        )
    )
    story.append(Spacer(1, 2 * mm))
    story.append(totals)

    doc.build(story, onFirstPage=_draw_page_furniture, onLaterPages=_draw_page_furniture)
    return buf.getvalue()
