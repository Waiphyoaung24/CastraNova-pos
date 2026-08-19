"""Unit tests for render_sale_receipt (FR-007, Task 1.4).

Strategy: no PDF-text-extraction library is in the project deps, so we use
structural assertions on the function interface rather than parsing PDF bytes.

The function signature is the contract: ``render_sale_receipt`` accepts only
(sale_id, sold_at, lines, total_thb) where ``lines`` is a list of
(label, qty, unit_price_thb) tuples.  There is no parameter that can carry
cost/COGS data.  We lock this contract with an ``inspect``-based test, which
will fail if a cost field is ever accidentally added to the signature.

We also exercise the function end-to-end and verify the output is a
well-formed PDF that starts with the ``%PDF`` magic bytes.
"""

import inspect
from decimal import Decimal

from app.services.receipt_pdf import render_sale_receipt


def test_receipt_pdf_signature_has_no_cost_parameter() -> None:
    """render_sale_receipt must accept EXACTLY the expected safe parameter set.

    The allowlist is {"sale_id", "sold_at", "lines", "total_thb"}.  Any
    deviation — including a new parameter with an unanticipated cost-related
    name such as ``cost``, ``cogs_thb``, ``landed_cost``, etc. — will cause
    this test to fail, alerting the developer that the customer-facing receipt
    renderer may leak margin/cost data and must be reviewed before merging.
    """
    sig = inspect.signature(render_sale_receipt)
    param_names = set(sig.parameters.keys())
    expected = {"sale_id", "sold_at", "customer_name", "sold_by", "lines", "total_thb"}
    assert param_names == expected, (
        f"render_sale_receipt parameter names changed. "
        f"Expected exactly {expected}, got {param_names}. "
        "A new parameter to the receipt renderer could leak cost/margin data "
        "and MUST be reviewed before this test is updated."
    )


def test_receipt_pdf_lines_tuple_has_no_cost_position() -> None:
    """The ``lines`` annotation must be exactly ``list[tuple[str, int, Decimal]]``.

    This pins the element type and width to a 3-tuple (label, qty, price).
    Adding a 4th position for cost/COGS would change the annotation and break
    this test, making the change visible during review.

    The render call below is a secondary guard: passing a 3-tuple confirms the
    function body also accepts exactly 3 elements (no runtime unpacking of 4).
    """
    sig = inspect.signature(render_sale_receipt)
    annotation = sig.parameters["lines"].annotation
    expected_annotation = list[tuple[str, int, Decimal]]
    assert annotation == expected_annotation, (
        f"lines parameter annotation must be exactly {expected_annotation!r}, "
        f"got {annotation!r}. "
        "Widening the tuple (e.g. adding a cost position) could leak margin data."
    )
    # Secondary guard: the function body must accept a 3-tuple without error.
    pdf_bytes = render_sale_receipt(
        sale_id="test-sale-001",
        sold_at="2026-06-07T10:00:00",
        customer_name="Walk-in",
        sold_by="admin@example.com",
        lines=[("Compressor Model X", 1, Decimal("1000.00"))],
        total_thb=Decimal("1000.00"),
    )
    assert isinstance(pdf_bytes, bytes)


def test_receipt_pdf_returns_valid_pdf_bytes() -> None:
    """render_sale_receipt returns bytes with a valid PDF magic header."""
    pdf_bytes = render_sale_receipt(
        sale_id="test-sale-abc",
        sold_at="2026-06-07T12:30:00",
        customer_name="Walk-in",
        sold_by="admin@example.com",
        lines=[
            ("Unit SN-ABC123", 1, Decimal("1500.00")),
            ("Service Charge", 1, Decimal("200.00")),
        ],
        total_thb=Decimal("1700.00"),
    )
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes[:4] == b"%PDF", "Output must be a PDF (starts with %PDF)"
    assert len(pdf_bytes) > 100, "PDF content unexpectedly small"


def test_receipt_pdf_selling_total_is_included() -> None:
    """total_thb (selling price) is accepted and the PDF renders without error.

    We cannot parse the PDF text without a new dependency, but we verify the
    function completes successfully when given a known selling total, and that
    the result is a non-empty PDF.
    """
    total = Decimal("2500.00")
    pdf_bytes = render_sale_receipt(
        sale_id="test-sale-xyz",
        sold_at="2026-06-07T09:00:00",
        customer_name="Walk-in",
        sold_by="admin@example.com",
        lines=[("Compressor A9", 2, Decimal("1000.00")), ("Filter Kit", 1, Decimal("500.00"))],
        total_thb=total,
    )
    assert pdf_bytes[:4] == b"%PDF"


def test_receipt_pdf_is_a4() -> None:
    """The receipt renders at A4 (MediaBox ~595x842pt), not the old A6."""
    pdf_bytes = render_sale_receipt(
        sale_id="test-sale-a4",
        sold_at="2026-06-25T14:02:00",
        customer_name="Walk-in",
        sold_by="admin@example.com",
        lines=[("Compressor Model X", 1, Decimal("1000.00"))],
        total_thb=Decimal("1000.00"),
    )
    # ponytail: grep the MediaBox bytes instead of adding a PDF-parser dep.
    # A4 = 595.27 x 841.89 pt; the page dict is uncompressed plain text.
    assert b"841.8" in pdf_bytes and b"595.2" in pdf_bytes


def test_receipt_pdf_embeds_logo_image() -> None:
    """With assets present, the rendered PDF embeds an image (logo/watermark)."""
    pdf_bytes = render_sale_receipt(
        sale_id="test-sale-img",
        sold_at="2026-06-25T14:02:00",
        customer_name="Walk-in",
        sold_by="admin@example.com",
        lines=[("Compressor Model X", 1, Decimal("1000.00"))],
        total_thb=Decimal("1000.00"),
    )
    assert b"/Image" in pdf_bytes, "expected an embedded image XObject"


def test_receipt_pdf_empty_lines_does_not_crash() -> None:
    """A sale with no resolvable lines still renders header + GRAND TOTAL."""
    pdf_bytes = render_sale_receipt(
        sale_id="test-sale-empty",
        sold_at="2026-06-25T14:02:00",
        customer_name="Walk-in",
        sold_by="admin@example.com",
        lines=[],
        total_thb=Decimal("0.00"),
    )
    assert pdf_bytes[:4] == b"%PDF"
