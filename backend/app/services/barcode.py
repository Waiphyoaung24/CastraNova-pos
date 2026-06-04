"""Code128 barcode label rendering for serialized units (FR-005).

Produces a small self-contained PDF label per piece so warehouse staff can
print/reprint on receive (the reprint-by-serial path covers a lost label, S-lost-label).
"""

import io

from reportlab.graphics.barcode import code128  # type: ignore[import-untyped]
from reportlab.lib.units import mm  # type: ignore[import-untyped]
from reportlab.pdfgen import canvas  # type: ignore[import-untyped]

# Compact label: ~ 60mm x 30mm.
_LABEL_W = 60 * mm
_LABEL_H = 30 * mm


def render_unit_label(*, castranova_barcode: str, caption: str) -> bytes:
    """Return a one-page PDF (bytes) with a Code128 barcode + human-readable text."""
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=(_LABEL_W, _LABEL_H))
    bar = code128.Code128(castranova_barcode, barHeight=12 * mm, barWidth=0.33 * mm)
    bar.drawOn(pdf, 4 * mm, 13 * mm)
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(4 * mm, 8 * mm, castranova_barcode)
    pdf.setFont("Helvetica", 6)
    pdf.drawString(4 * mm, 3 * mm, caption[:48])
    pdf.showPage()
    pdf.save()
    return buf.getvalue()
