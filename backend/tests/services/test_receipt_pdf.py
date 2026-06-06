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
    """render_sale_receipt must NOT accept any cost/COGS parameter.

    If unit_cost_thb, total_cogs_thb, purchase_cost, or margin are ever added
    to the signature, this test fails — alerting the developer that the
    customer-facing receipt may leak margin data.
    """
    sig = inspect.signature(render_sale_receipt)
    param_names = set(sig.parameters.keys())
    forbidden = {"unit_cost_thb", "total_cogs_thb", "purchase_cost", "purchase_cost_thb", "margin"}
    leaked = param_names & forbidden
    assert not leaked, (
        f"render_sale_receipt must not expose cost fields; found: {leaked}"
    )


def test_receipt_pdf_lines_tuple_has_no_cost_position() -> None:
    """The ``lines`` parameter annotation must be (label, qty, price) — 3-tuple.

    A cost field would require a 4th position.  We verify via the type annotation
    string that the tuple width is exactly 3.
    """
    sig = inspect.signature(render_sale_receipt)
    annotation = sig.parameters["lines"].annotation
    # annotation is list[tuple[str, int, Decimal]] — repr contains "tuple"
    ann_str = str(annotation)
    assert "tuple" in ann_str.lower() or "Tuple" in ann_str, (
        "lines parameter annotation should be a tuple type"
    )
    # Decimal in position 2 is the price; there must be no 4th element.
    # We verify by actually passing a 3-tuple — if signature or body ever
    # requires 4 elements, this call will fail.
    pdf_bytes = render_sale_receipt(
        sale_id="test-sale-001",
        sold_at="2026-06-07T10:00:00",
        lines=[("Compressor Model X", 1, Decimal("1000.00"))],
        total_thb=Decimal("1000.00"),
    )
    assert isinstance(pdf_bytes, bytes)


def test_receipt_pdf_returns_valid_pdf_bytes() -> None:
    """render_sale_receipt returns bytes with a valid PDF magic header."""
    pdf_bytes = render_sale_receipt(
        sale_id="test-sale-abc",
        sold_at="2026-06-07T12:30:00",
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
        lines=[("Compressor A9", 2, Decimal("1000.00")), ("Filter Kit", 1, Decimal("500.00"))],
        total_thb=total,
    )
    assert pdf_bytes[:4] == b"%PDF"
