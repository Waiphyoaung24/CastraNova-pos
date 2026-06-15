"""Unit tests for render_unit_label / _unit_qr_drawing (FR-005, QR labels).

Two layers:
- Always-on structural test: the QR Drawing carries the exact value at ECC
  level M (catches wrong-value or symbology-revert regressions with zero deps).
- Optional decode round-trip: rasterize the QR Drawing and decode it back,
  proving real scannability. Skipped if the optional decoder (opencv) or the
  reportlab raster backend (renderPM) is unavailable, so the suite still runs.
"""

import pytest

from app.services.barcode import _unit_qr_drawing, render_unit_label

_BARCODE = "CN-A1B2C3D4E5F6A7B8"


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


def test_qr_round_trips_through_a_decoder() -> None:
    """Rasterize the QR and decode it — proves the label is actually scannable."""
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    render_pm = pytest.importorskip("reportlab.graphics.renderPM")

    drawing = _unit_qr_drawing(_BARCODE, size=200)  # 200pt → dense enough to decode
    png = render_pm.drawToString(drawing, fmt="PNG", dpi=300)
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
    decoded, _points, _qr = cv2.QRCodeDetector().detectAndDecode(img)
    assert decoded == _BARCODE
