"""QR label rendering for serialized units (FR-005) and SKU/bin labels.

Produces small self-contained PDF labels so warehouse staff can print/reprint
on receive. A serialized label encodes a unit's castranova_barcode; a SKU label
encodes a product's sku. Both share one 60x30mm QR + two-line layout and can
emit N identical pages (one label per page) for the roll thermal printer. The
encoded value is also printed human-readable for the manual fallback.
"""

import base64
import io

import qrcode  # type: ignore[import-untyped]
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


def render_qr_png_data_uri(value: str) -> str:
    """Return `value` as a QR code, encoded as a base64 PNG data URI.

    For on-screen display (the Telegram connect card's deep link) rather than
    print: unlike render_label_sheet's ReportLab vector/PDF output, this uses
    the `qrcode` package directly to get a raster image cheaply.
    """
    img = qrcode.make(value)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


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
