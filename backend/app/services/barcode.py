"""QR label rendering for serialized units (FR-005) and SKU/bin labels.

Produces small self-contained PDF labels so warehouse staff can print/reprint
on receive. A serialized label encodes a unit's castranova_barcode; a SKU label
encodes a product's sku. Both share one 80x60mm layout (brand band, centered
QR, code + caption) and can emit N identical pages (one label per page) for
the roll thermal printer. The encoded value is also printed human-readable for
the manual fallback. Thermal printers are 1-bit, so everything is pure
black/white — no grays, which dither badly.
"""

import base64
import io

import qrcode  # type: ignore[import-untyped]
from reportlab.graphics import renderPDF  # type: ignore[import-untyped]
from reportlab.graphics.barcode.qr import QrCodeWidget  # type: ignore[import-untyped]
from reportlab.graphics.shapes import Drawing  # type: ignore[import-untyped]
from reportlab.lib.units import mm  # type: ignore[import-untyped]
from reportlab.pdfbase.pdfmetrics import stringWidth  # type: ignore[import-untyped]
from reportlab.pdfgen import canvas  # type: ignore[import-untyped]

# Matches the Hoin thermal printer's 80x60mm label stock.
_LABEL_W = 80 * mm
_LABEL_H = 60 * mm
_QR_SIZE = 30 * mm
# Side inset for text; the brand band is inset further so a millimetre of
# printer feed drift never clips it against the die-cut edge.
_MARGIN = 4 * mm
_BAND_INSET = 2.5 * mm
_BAND_H = 6.5 * mm


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


def _fitted_size(
    text: str, font: str, max_size: float, max_width: float, min_size: float = 5.0
) -> float:
    """Largest font size <= max_size at which `text` fits `max_width` points."""
    width = float(stringWidth(text, font, max_size))
    if width <= max_width:
        return max_size
    return max(min_size, max_size * max_width / width)


def _ellipsized(text: str, font: str, size: float, max_width: float) -> str:
    """Trim `text` with a trailing ellipsis until it fits `max_width` points."""
    if stringWidth(text, font, size) <= max_width:
        return text
    while text and stringWidth(text + "…", font, size) > max_width:
        text = text[:-1]
    return text + "…"


def _draw_label_page(
    pdf: canvas.Canvas, *, qr_value: str, line1: str, line2: str
) -> None:
    """Draw one 80x60mm label page and end the page.

    Top to bottom: inverted brand band, centered QR, the encoded value large
    and bold (auto-shrunk to fit), then the caption line (shrunk, then
    ellipsized as a last resort).
    """
    band_y = _LABEL_H - _BAND_INSET - _BAND_H
    pdf.setFillGray(0)
    pdf.roundRect(
        _BAND_INSET,
        band_y,
        _LABEL_W - 2 * _BAND_INSET,
        _BAND_H,
        1.5 * mm,
        stroke=0,
        fill=1,
    )
    pdf.setFillGray(1)
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawCentredString(
        _LABEL_W / 2, band_y + _BAND_H / 2 - 2.8, "C A S T R A N O V A"
    )
    pdf.setFillGray(0)

    renderPDF.draw(
        _unit_qr_drawing(qr_value), pdf, (_LABEL_W - _QR_SIZE) / 2, 19 * mm
    )

    max_w = _LABEL_W - 2 * _MARGIN
    size1 = _fitted_size(line1, "Helvetica-Bold", 18, max_w)
    pdf.setFont("Helvetica-Bold", size1)
    pdf.drawCentredString(_LABEL_W / 2, 12 * mm, line1)

    size2 = _fitted_size(line2, "Helvetica", 8, max_w)
    pdf.setFont("Helvetica", size2)
    pdf.drawCentredString(
        _LABEL_W / 2, 6 * mm, _ellipsized(line2, "Helvetica", size2, max_w)
    )
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
