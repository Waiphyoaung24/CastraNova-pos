"""Tests for render_qr_png_data_uri (Telegram connect card on-screen QR).

Mirrors test_unit_label.py's approach: no raster-decode dependency in this
project, so assert structurally (valid base64, PNG magic header) rather than
decoding pixels or the QR payload itself.
"""

import base64

from app.services.barcode import render_qr_png_data_uri

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def test_render_qr_png_data_uri_has_the_right_prefix() -> None:
    uri = render_qr_png_data_uri("https://t.me/SomeBot?start=abc123")
    assert uri.startswith("data:image/png;base64,")


def test_render_qr_png_data_uri_decodes_to_a_valid_png() -> None:
    uri = render_qr_png_data_uri("https://t.me/SomeBot?start=abc123")
    b64_part = uri.removeprefix("data:image/png;base64,")
    decoded = base64.b64decode(b64_part)
    assert decoded[:8] == _PNG_MAGIC
