"""Structural tests for render_label_sheet (SKU/bin + serialized QR labels).

Mirrors test_unit_label.py's parser-free philosophy: assert page count and PDF
validity from raw bytes (the repo deliberately carries no PDF-parsing dep). The
per-page QR value/ECC-M guarantee is already covered by test_unit_label.py via
the shared _unit_qr_drawing helper that render_label_sheet reuses.
"""

import re

from app.services.barcode import render_label_sheet, render_unit_label


def _page_count(pdf: bytes) -> int:
    # One PDF page object ("/Type /Page") per label. The negative lookahead on
    # the trailing 's' excludes the single "/Type /Pages" catalog node.
    return len(re.findall(rb"/Type\s*/Page(?!s)", pdf))


def test_render_label_sheet_default_is_one_page() -> None:
    pdf = render_label_sheet(qr_value="FLT-001", line1="FLT-001", line2="Filter")
    assert pdf[:4] == b"%PDF"
    assert _page_count(pdf) == 1


def test_render_label_sheet_emits_qty_pages() -> None:
    pdf = render_label_sheet(
        qr_value="FLT-001", line1="FLT-001", line2="Filter", qty=5
    )
    assert pdf[:4] == b"%PDF"
    assert _page_count(pdf) == 5


def test_render_label_sheet_page_is_80x60mm() -> None:
    # The page size must match the Hoin printer's 80x60mm label stock;
    # 80mm = 226.77pt, 60mm = 170.08pt. Pinned from raw bytes, parser-free.
    pdf = render_label_sheet(qr_value="FLT-001", line1="FLT-001", line2="Filter")
    assert re.search(rb"/MediaBox\s*\[\s*0 0 226\.77\d* 170\.07\d*\s*\]", pdf)


def test_render_unit_label_wrapper_still_one_page() -> None:
    pdf = render_unit_label(castranova_barcode="CN-ABC123", caption="SN-9")
    assert pdf[:4] == b"%PDF"
    assert _page_count(pdf) == 1
