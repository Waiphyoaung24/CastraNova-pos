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
    # getBounds() returns (0, 0, w, h) for QrCodeWidget today, so the translation
    # terms below collapse to zero; they are kept defensively so the scale-to-fit
    # stays correct if a future ReportLab returns a non-zero origin.
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
