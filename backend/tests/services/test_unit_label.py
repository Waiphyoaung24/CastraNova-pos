"""Unit tests for render_unit_label / _unit_qr_drawing (FR-005, QR labels).

Strategy mirrors test_receipt_pdf.py: the project intentionally carries no
PDF-rasterizing/decoding dependency, so we assert structurally rather than
decoding pixels. Two guards:
- the QR Drawing carries the exact value at ECC level M (catches a wrong value
  or a silent revert to a different symbology), and
- the full render pipeline executes and emits a well-formed PDF (proves the QR
  actually encodes + draws without error).

Real camera-scannability of the printed label is verified manually (scan the
label PDF with the in-app camera fallback) — a 19-char ECC-M QR is decodable by
spec, and pixel-level decode would require a heavy raster backend the repo omits.
"""

import inspect

from app.services.barcode import _unit_qr_drawing, render_unit_label

_BARCODE = "CN-A1B2C3D4E5F6A7B8"


def test_render_unit_label_signature_is_stable() -> None:
    """Pin the public contract the route depends on (mirrors test_receipt_pdf.py).

    The receipts route calls render_unit_label(castranova_barcode=..., caption=...);
    a rename here would silently break that call site, so lock the parameter set.
    """
    sig = inspect.signature(render_unit_label)
    assert set(sig.parameters.keys()) == {"castranova_barcode", "caption"}


def test_unit_qr_drawing_encodes_exact_value() -> None:
    drawing = _unit_qr_drawing(_BARCODE)
    widgets = [c for c in drawing.contents if hasattr(c, "value")]
    assert len(widgets) == 1, "expected exactly one QR widget in the drawing"
    widget = widgets[0]
    assert widget.value == _BARCODE
    assert widget.barLevel == "M"


def test_render_unit_label_returns_valid_pdf() -> None:
    pdf = render_unit_label(castranova_barcode=_BARCODE, caption="SN-XYZ")
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 100
