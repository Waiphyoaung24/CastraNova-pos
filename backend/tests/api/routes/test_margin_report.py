import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlmodel import Session

from app import crud
from app.models import Channel, MarginBreakdownReport, MarginDimension
from tests.api.routes.test_reports import (  # noqa: F401  (seed is a pytest fixture)
    TARGET,
    _pin_pull,
    _pin_sale,
    _pin_ticket,
    _pull_lines,
    seed,
)


def _totals(
    report: MarginBreakdownReport,
) -> tuple[Decimal, Decimal, Decimal]:
    return (report.total_revenue_thb, report.total_cogs_thb, report.total_margin_thb)


def test_channel_grouping_matches_legacy_report(db: Session, seed) -> None:  # noqa: ARG001, F811
    """margin_report(group_by=CHANNEL) equals the legacy channel_margin_report."""
    legacy = crud.channel_margin_report(session=db, year=2099, month=2)  # empty month
    new = crud.margin_report(
        session=db, year=2099, month=2, group_by=MarginDimension.CHANNEL
    )
    # Always three channel rows, fixed order, even for an empty month.
    assert [r.key for r in new.rows] == [
        Channel.SALE.value,
        Channel.MAINTENANCE.value,
        Channel.PROJECT.value,
    ]
    assert _totals(new) == (
        legacy.total_revenue_thb,
        legacy.total_cogs_thb,
        legacy.total_margin_thb,
    )
    for legacy_row, new_row in zip(legacy.channels, new.rows, strict=True):
        assert new_row.label == legacy_row.channel.value
        assert new_row.revenue_thb == legacy_row.revenue_thb
        assert new_row.cogs_thb == legacy_row.cogs_thb
        assert new_row.margin_thb == legacy_row.margin_thb


def test_channel_filter_returns_single_channel(db: Session, seed) -> None:  # noqa: ARG001, F811
    report = crud.margin_report(
        session=db,
        year=2099,
        month=2,
        group_by=MarginDimension.CHANNEL,
        channel=Channel.SALE,
    )
    assert [r.key for r in report.rows] == [Channel.SALE.value]
    assert report.channel == Channel.SALE


def _seed_full_month(db: Session, seed: dict[str, Any], when: datetime = TARGET) -> None:  # noqa: F811
    """One SALE (serialized unit + a part), one MAINTENANCE ticket part, and one
    PROJECT pull (unit + part), all pinned into ``when``'s month (default 2026-03).
    Mirrors test_reports.test_mixed_channel_hand_calc so totals are
    hand-checkable. ``when`` lets callers pick a dedicated month, the same
    isolation convention test_reports.test_short_pull_counted uses, so
    concurrently-seeded tests in this session-scoped db don't collide."""
    from app.models import (
        ProjectCreate,
        ProjectPullCreate,
        ProjectPullFulfillLine,
        ProjectPullLineCreate,
        SaleLineInput,
        SaleLineKind,
    )

    admin, customer = seed["admin"], seed["customer"]
    # --- SALE ---
    sale_part = seed["make_part"]("100.00", "20.00", [(3, "10.00"), (4, "12.00")])
    sale_barcode = seed["make_unit"]("100.00")
    sale = crud.create_sale(
        session=db, customer_id=customer.id, created_by_user_id=admin.id,
        idempotency_key=uuid.uuid4(),
        lines=[
            SaleLineInput(line_kind=SaleLineKind.UNIT, castranova_barcode=sale_barcode),
            SaleLineInput(line_kind=SaleLineKind.PART, sku=sale_part.sku, quantity=5),
        ],
    )
    _pin_sale(db, sale.id, when)

    # --- MAINTENANCE ---
    maint_part = seed["make_part"]("100.00", "20.00", [(3, "10.00"), (4, "12.00")])
    ticket = crud.open_service_ticket(
        session=db,
        customer_id=customer.id,
        issue="noisy",
        idempotency_key=uuid.uuid4(),
        created_by_user_id=admin.id,
    )
    crud.add_service_ticket_part(
        session=db, ticket_id=ticket.id, sku=maint_part.sku, quantity=2
    )
    crud.close_service_ticket(session=db, ticket_id=ticket.id, actor_user_id=admin.id)
    _pin_ticket(db, ticket.id, when)

    # --- PROJECT ---
    proj_part = seed["make_part"]("100.00", "20.00", [(3, "10.00"), (4, "12.00")])
    proj_barcode = seed["make_unit"]("100.00")
    project = crud.create_project(
        session=db,
        project_in=ProjectCreate(
            code=f"PRJ-{uuid.uuid4().hex[:8]}",
            name="Site",
            customer_id=customer.id,
        ),
    )
    pull = crud.create_project_pull(
        session=db,
        pull_in=ProjectPullCreate(
            project_id=project.id,
            lines=[
                ProjectPullLineCreate(
                    line_kind=SaleLineKind.UNIT,
                    product_id=seed["serialized"].id,
                    unit_serial=proj_barcode,
                ),
                ProjectPullLineCreate(
                    line_kind=SaleLineKind.PART,
                    product_id=proj_part.id,
                    requested_qty=3,
                ),
            ],
        ),
        created_by_user_id=admin.id,
    )
    line_ids = {ln.line_kind: ln.id for ln in _pull_lines(db, pull.id)}
    crud.fulfill_project_pull(
        session=db,
        pull_id=pull.id,
        fulfill_lines=[
            ProjectPullFulfillLine(line_id=line_ids[SaleLineKind.UNIT], fulfilled_qty=1),
            ProjectPullFulfillLine(line_id=line_ids[SaleLineKind.PART], fulfilled_qty=3),
        ],
        actor_user_id=admin.id,
    )
    _pin_pull(db, pull.id, when)


def test_product_grouping_reconciles_to_channel(db: Session, seed: dict[str, Any]) -> None:  # noqa: F811
    # Dedicated month (2026-05): the session-scoped db is shared with
    # test_reports.test_mixed_channel_hand_calc, which asserts exact totals
    # for 2026-03 -- seeding there would float that test's hand-calc numbers.
    when = datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)
    _seed_full_month(db, seed, when=when)
    by_channel = crud.margin_report(
        session=db, year=2026, month=5, group_by=MarginDimension.CHANNEL
    )
    by_product = crud.margin_report(
        session=db, year=2026, month=5, group_by=MarginDimension.PRODUCT
    )
    # Reconciliation invariant: same month, same totals, different grouping.
    assert _totals(by_product) == _totals(by_channel)
    # Rows sum to the report totals.
    assert sum((r.revenue_thb for r in by_product.rows), Decimal("0.00")) == (
        by_product.total_revenue_thb
    )
    # Sorted revenue-desc.
    revs = [r.revenue_thb for r in by_product.rows]
    assert revs == sorted(revs, reverse=True)


def test_product_grouping_scoped_to_sale_channel(db: Session, seed: dict[str, Any]) -> None:  # noqa: F811
    # Dedicated month (2026-04) so the session-scoped db's other SALE activity
    # (test_product_grouping_reconciles_to_channel pins to March) doesn't float
    # the "exactly two products" assertion below.
    when = datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc)
    _seed_full_month(db, seed, when=when)
    sale_only = crud.margin_report(
        session=db, year=2026, month=4,
        group_by=MarginDimension.PRODUCT, channel=Channel.SALE,
    )
    by_channel = crud.margin_report(
        session=db, year=2026, month=4, group_by=MarginDimension.CHANNEL,
        channel=Channel.SALE,
    )
    assert _totals(sale_only) == _totals(by_channel)
    # SALE has exactly two products: the serialized unit + the quantity part.
    assert len(sale_only.rows) == 2
