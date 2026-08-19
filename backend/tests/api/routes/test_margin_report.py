import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlmodel import Session, select

from app import crud
from app.models import (
    Channel,
    MarginBreakdownReport,
    MarginDimension,
    SaleLine,
    SaleLineInput,
    SaleLineKind,
    SaleReturn,
    SaleReturnCreateRequest,
    SaleReturnLineInput,
    ServiceTicketPartCreate,
)
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


def test_channel_grouping_empty_month_all_zero(db: Session, seed) -> None:  # noqa: ARG001, F811
    """margin_report(group_by=CHANNEL) for an empty month: always three fixed
    rows, all zero. (Legacy crud.channel_margin_report was deleted in FR-013
    Task 5; this test used to assert parity against it.)"""
    new = crud.margin_report(
        session=db, year=2099, month=2, group_by=MarginDimension.CHANNEL
    )
    # Always three channel rows, fixed order, even for an empty month.
    assert [r.key for r in new.rows] == [
        Channel.SALE.value,
        Channel.MAINTENANCE.value,
        Channel.PROJECT.value,
    ]
    assert _totals(new) == (Decimal("0.00"), Decimal("0.00"), Decimal("0.00"))
    for row in new.rows:
        assert row.revenue_thb == Decimal("0.00")
        assert row.cogs_thb == Decimal("0.00")
        assert row.margin_thb == Decimal("0.00")


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
    ticket = crud.record_service_ticket(
        session=db,
        customer_id=customer.id,
        issue="noisy",
        parts=[ServiceTicketPartCreate(sku=maint_part.sku, quantity=2)],
        idempotency_key=uuid.uuid4(),
        actor_user_id=admin.id,
    )
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


def test_customer_grouping_reconciles_and_labels(db: Session, seed: dict[str, Any]) -> None:  # noqa: F811
    # Dedicated month (2026-06): distinct from every other month pinned in
    # this session-scoped db (2026-03/04/05), per the isolation convention.
    when = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    _seed_full_month(db, seed, when=when)
    by_customer = crud.margin_report(
        session=db, year=2026, month=6, group_by=MarginDimension.CUSTOMER
    )
    by_channel = crud.margin_report(
        session=db, year=2026, month=6, group_by=MarginDimension.CHANNEL
    )
    assert _totals(by_customer) == _totals(by_channel)
    # All activity in the seed belongs to the one seeded customer.
    assert len(by_customer.rows) == 1
    assert by_customer.rows[0].label == "Report Cust"


def test_project_grouping_all_channels_has_bucket(db: Session, seed: dict[str, Any]) -> None:  # noqa: F811
    # Dedicated month (2026-10): 2026-07/08/09 are used by test_reports.py's
    # adjacent-month and pull tests, so this doesn't float their assertions.
    when = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
    _seed_full_month(db, seed, when=when)
    by_project = crud.margin_report(
        session=db, year=2026, month=10, group_by=MarginDimension.PROJECT
    )
    by_channel = crud.margin_report(
        session=db, year=2026, month=10, group_by=MarginDimension.CHANNEL
    )
    assert _totals(by_project) == _totals(by_channel)
    labels = {r.label for r in by_project.rows}
    assert "(not project work)" in labels  # SALE + MAINTENANCE remainder
    bucket = next(r for r in by_project.rows if r.key == "")
    # The bucket equals SALE + MAINTENANCE margin.
    sale = next(r for r in by_channel.rows if r.key == Channel.SALE.value)
    maint = next(r for r in by_channel.rows if r.key == Channel.MAINTENANCE.value)
    assert bucket.margin_thb == sale.margin_thb + maint.margin_thb


def test_project_grouping_scoped_to_project_has_no_bucket(db: Session, seed: dict[str, Any]) -> None:  # noqa: F811
    # Dedicated month (2026-11): distinct from the sibling test above (2026-10)
    # so the two seedings in this session-scoped db don't collide.
    when = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
    _seed_full_month(db, seed, when=when)
    scoped = crud.margin_report(
        session=db, year=2026, month=11,
        group_by=MarginDimension.PROJECT, channel=Channel.PROJECT,
    )
    assert all(r.key != "" for r in scoped.rows)
    assert len(scoped.rows) == 1  # the single seeded project


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


def test_sale_cogs_reconciles_for_non_cent_divisible_part_line(
    db: Session, seed: dict[str, Any]  # noqa: F811
) -> None:
    """Regression: a PART sale line whose FIFO cost doesn't divide evenly by
    quantity snapshots a ROUNDED SaleLine.unit_cost_thb, while Sale.total_cogs_thb
    stays exact. PRODUCT/CUSTOMER groupings must derive SALE COGS from the exact
    sources (CostLine/Unit), not by reconstructing quantity * unit_cost_thb, or
    they diverge from the CHANNEL grouping by a cent.

    Batches [(1, "10.00"), (2, "10.01")] -> FIFO cost for qty=3 is exactly
    10.00 + 20.02 = 30.02. 30.02 / 3 = 10.006666... rounds to 10.01, so the
    (buggy) reconstruction 3 * 10.01 = 30.03 != 30.02.
    """
    # Dedicated month (2027-03): distinct from every other month pinned in
    # this session-scoped db (2026-03/04/05/06/10/11/12, 2027-01/02).
    when = datetime(2027, 3, 15, 12, 0, tzinfo=timezone.utc)
    admin, customer = seed["admin"], seed["customer"]
    part = seed["make_part"]("100.00", "20.00", [(1, "10.00"), (2, "10.01")])
    sale = crud.create_sale(
        session=db, customer_id=customer.id, created_by_user_id=admin.id,
        idempotency_key=uuid.uuid4(),
        lines=[
            SaleLineInput(line_kind=SaleLineKind.PART, sku=part.sku, quantity=3),
        ],
    )
    _pin_sale(db, sale.id, when)

    refreshed = db.get(type(sale), sale.id)
    assert refreshed is not None
    assert refreshed.total_cogs_thb == Decimal("30.02")

    by_channel = crud.margin_report(
        session=db, year=2027, month=3,
        group_by=MarginDimension.CHANNEL, channel=Channel.SALE,
    )
    by_product = crud.margin_report(
        session=db, year=2027, month=3,
        group_by=MarginDimension.PRODUCT, channel=Channel.SALE,
    )
    by_customer = crud.margin_report(
        session=db, year=2027, month=3,
        group_by=MarginDimension.CUSTOMER, channel=Channel.SALE,
    )
    assert _totals(by_product) == _totals(by_channel)
    assert _totals(by_customer) == _totals(by_channel)


def test_per_channel_amounts_reconcile_against_channel_filtered_products(
    db: Session, seed: dict[str, Any]  # noqa: F811
) -> None:
    """The other reconciliation tests only compare grand TOTALs across
    groupings, so a bug that shifts revenue/COGS BETWEEN channels while
    preserving the grand total would go undetected. Here we tie each
    individual channel row to an independently-filtered PRODUCT-dimension
    aggregation for that same channel, which catches cross-channel shifts."""
    # Dedicated month (2027-02): distinct from every other month pinned in
    # this session-scoped db (2026-03/04/05/06/10/11/12, 2027-01).
    when = datetime(2027, 2, 15, 12, 0, tzinfo=timezone.utc)
    _seed_full_month(db, seed, when=when)
    by_channel = crud.margin_report(
        session=db, year=2027, month=2, group_by=MarginDimension.CHANNEL
    )
    # The seed produced nonzero money somewhere, so the reconciliation below
    # can't pass vacuously on all-zeros.
    assert by_channel.total_revenue_thb > 0

    for row in by_channel.rows:
        by_product_for_channel = crud.margin_report(
            session=db,
            year=2027,
            month=2,
            group_by=MarginDimension.PRODUCT,
            channel=Channel(row.key),
        )
        assert by_product_for_channel.total_revenue_thb == row.revenue_thb
        assert by_product_for_channel.total_cogs_thb == row.cogs_thb
        assert by_product_for_channel.total_margin_thb == row.margin_thb


# --- Sale returns (design 2026-07-25) ----------------------------------------

# Dedicated months so tests in this session-scoped db cannot collide. Months
# already claimed elsewhere: 2026-03/04/05/06/09/10/11/12, 2027-01/02/03.
_RET_CHANNEL = datetime(2027, 4, 15, 12, 0, tzinfo=timezone.utc)
_RET_SOLD = datetime(2027, 5, 15, 12, 0, tzinfo=timezone.utc)
_RET_LATER = datetime(2027, 6, 15, 12, 0, tzinfo=timezone.utc)
_RET_MAINT_FILTER = datetime(2027, 7, 15, 12, 0, tzinfo=timezone.utc)
_RET_SALE_FILTER = datetime(2027, 8, 15, 12, 0, tzinfo=timezone.utc)
_RET_PRODUCT = datetime(2027, 9, 15, 12, 0, tzinfo=timezone.utc)
_RET_CUSTOMER = datetime(2027, 10, 15, 12, 0, tzinfo=timezone.utc)
_RET_RECONCILE = datetime(2027, 11, 15, 12, 0, tzinfo=timezone.utc)
_RET_SERIALIZED = datetime(2027, 12, 15, 12, 0, tzinfo=timezone.utc)


def _pin_return(db: Session, sale_return_id: uuid.UUID, when: datetime) -> None:
    """Rewrite returned_at so a test owns a month. salereturn is not a ledger
    table, so a plain UPDATE is allowed (unlike part_movement)."""
    row = db.get(SaleReturn, sale_return_id)
    assert row is not None
    row.returned_at = when
    db.add(row)
    db.commit()


def _sell_and_return_part(
    db: Session,
    seed: dict[str, Any],  # noqa: F811
    *,
    sold_when: datetime,
    returned_when: datetime,
    sell_qty: int = 2,
    return_qty: int = 1,
) -> Any:
    """Sell ``sell_qty`` of a fresh part (retail 100, single batch @ cost 10) and
    return ``return_qty`` of it. Returns the part product so callers can find its
    row. Hand-checkable: revenue 100/unit, COGS 10/unit."""
    admin, customer = seed["admin"], seed["customer"]
    part = seed["make_part"]("100.00", "20.00", [(10, "10.00")])
    sale = crud.create_sale(
        session=db,
        customer_id=customer.id,
        created_by_user_id=admin.id,
        idempotency_key=uuid.uuid4(),
        lines=[
            SaleLineInput(
                line_kind=SaleLineKind.PART, sku=part.sku, quantity=sell_qty
            )
        ],
    )
    _pin_sale(db, sale.id, sold_when)
    line = db.exec(select(SaleLine).where(SaleLine.sale_id == sale.id)).one()
    ret = crud.create_sale_return(
        session=db,
        sale_id=sale.id,
        payload=SaleReturnCreateRequest(
            idempotency_key=uuid.uuid4(),
            reason="customer returned it",
            lines=[SaleReturnLineInput(sale_line_id=line.id, quantity=return_qty)],
        ),
        created_by_user_id=admin.id,
    )
    _pin_return(db, ret.id, returned_when)
    return part


def test_channel_view_shows_a_negative_sale_return_row(
    db: Session, seed: dict[str, Any]  # noqa: F811
) -> None:
    """Sell 2 @ 100 (cost 10 each), return 1: a separate SALE RETURNS row with
    negative revenue and COGS. The SALE row itself is untouched; totals net."""
    _sell_and_return_part(
        db, seed, sold_when=_RET_CHANNEL, returned_when=_RET_CHANNEL
    )

    report = crud.margin_report(session=db, year=2027, month=4)
    rows = {r.key: r for r in report.rows}

    assert rows["SALE"].revenue_thb == Decimal("200.00")
    assert rows["SALE"].cogs_thb == Decimal("20.00")
    assert rows["SALE_RETURN"].label == "SALE RETURNS"
    assert rows["SALE_RETURN"].revenue_thb == Decimal("-100.00")
    assert rows["SALE_RETURN"].cogs_thb == Decimal("-10.00")
    assert rows["SALE_RETURN"].margin_thb == Decimal("-90.00")
    assert report.total_revenue_thb == Decimal("100.00")
    assert report.total_cogs_thb == Decimal("10.00")
    assert report.total_margin_thb == Decimal("90.00")


def test_no_sale_return_row_when_no_returns_that_month(
    db: Session, seed: dict[str, Any]  # noqa: ARG001, F811
) -> None:
    report = crud.margin_report(session=db, year=2099, month=2)
    assert all(r.key != "SALE_RETURN" for r in report.rows)
    assert [r.key for r in report.rows] == ["SALE", "MAINTENANCE", "PROJECT"]


def test_a_return_only_moves_the_return_month(
    db: Session, seed: dict[str, Any]  # noqa: F811
) -> None:
    """A sale in May returned in June leaves May's report identical forever."""
    _sell_and_return_part(db, seed, sold_when=_RET_SOLD, returned_when=_RET_LATER)

    may = crud.margin_report(session=db, year=2027, month=5)
    assert all(r.key != "SALE_RETURN" for r in may.rows)
    assert may.total_revenue_thb == Decimal("200.00")  # untouched by the return

    june = crud.margin_report(session=db, year=2027, month=6)
    rows = {r.key: r for r in june.rows}
    assert rows["SALE_RETURN"].revenue_thb == Decimal("-100.00")
    assert rows["SALE"].revenue_thb == Decimal("0.00")


def test_maintenance_channel_filter_excludes_returns(
    db: Session, seed: dict[str, Any]  # noqa: F811
) -> None:
    _sell_and_return_part(
        db, seed, sold_when=_RET_MAINT_FILTER, returned_when=_RET_MAINT_FILTER
    )
    report = crud.margin_report(
        session=db, year=2027, month=7, channel=Channel.MAINTENANCE
    )
    assert all(r.key != "SALE_RETURN" for r in report.rows)


def test_sale_channel_filter_includes_returns(
    db: Session, seed: dict[str, Any]  # noqa: F811
) -> None:
    """Returns are an event ON the SALE channel, so scoping to SALE keeps them
    — otherwise the filtered view would not reconcile with the unfiltered one."""
    _sell_and_return_part(
        db, seed, sold_when=_RET_SALE_FILTER, returned_when=_RET_SALE_FILTER
    )
    report = crud.margin_report(
        session=db, year=2027, month=8, channel=Channel.SALE
    )
    assert [r.key for r in report.rows] == ["SALE", "SALE_RETURN"]


def test_returns_net_into_the_product_row(
    db: Session, seed: dict[str, Any]  # noqa: F811
) -> None:
    """Sell 2 @ 100 (cost 10), return 1: the product's row reads 100 revenue /
    10 COGS. One netted row — no separate returns row at this grain."""
    part = _sell_and_return_part(
        db, seed, sold_when=_RET_PRODUCT, returned_when=_RET_PRODUCT
    )

    report = crud.margin_report(
        session=db, year=2027, month=9, group_by=MarginDimension.PRODUCT
    )
    row = next(r for r in report.rows if r.key == str(part.id))
    assert row.revenue_thb == Decimal("100.00")
    assert row.cogs_thb == Decimal("10.00")
    assert row.margin_thb == Decimal("90.00")
    assert all(r.key != "SALE_RETURN" for r in report.rows)


def test_returns_net_into_the_customer_row(
    db: Session, seed: dict[str, Any]  # noqa: F811
) -> None:
    _sell_and_return_part(
        db, seed, sold_when=_RET_CUSTOMER, returned_when=_RET_CUSTOMER
    )

    report = crud.margin_report(
        session=db, year=2027, month=10, group_by=MarginDimension.CUSTOMER
    )
    row = next(r for r in report.rows if r.key == str(seed["customer"].id))
    assert row.revenue_thb == Decimal("100.00")
    assert row.cogs_thb == Decimal("10.00")


def test_all_groupings_reconcile_to_the_same_totals_with_returns(
    db: Session, seed: dict[str, Any]  # noqa: F811
) -> None:
    """The report's core promise: for a fixed (month, channel) every grouping
    sums to the same revenue/COGS. Returns must not break it. The month is
    seeded with SALE activity only, like the file's other reconciliation tests."""
    _sell_and_return_part(
        db, seed, sold_when=_RET_RECONCILE, returned_when=_RET_RECONCILE
    )

    by_channel = crud.margin_report(session=db, year=2027, month=11)
    by_product = crud.margin_report(
        session=db, year=2027, month=11, group_by=MarginDimension.PRODUCT
    )
    by_customer = crud.margin_report(
        session=db, year=2027, month=11, group_by=MarginDimension.CUSTOMER
    )

    assert by_channel.total_revenue_thb == by_product.total_revenue_thb
    assert by_channel.total_revenue_thb == by_customer.total_revenue_thb
    assert by_channel.total_cogs_thb == by_product.total_cogs_thb
    assert by_channel.total_cogs_thb == by_customer.total_cogs_thb


def test_a_serialized_return_nets_into_its_product_row(
    db: Session, seed: dict[str, Any]  # noqa: F811
) -> None:
    """A UNIT sale line carries unit_id, NOT product_id — the netting query has
    to recover the product through Unit, exactly like the SALE revenue query
    above it. Without the outer join this row would be keyed on NULL."""
    admin, customer = seed["admin"], seed["customer"]
    barcode = seed["make_unit"]("300.00")  # serialized product, retail 500.00
    sale = crud.create_sale(
        session=db,
        customer_id=customer.id,
        created_by_user_id=admin.id,
        idempotency_key=uuid.uuid4(),
        lines=[
            SaleLineInput(line_kind=SaleLineKind.UNIT, castranova_barcode=barcode)
        ],
    )
    _pin_sale(db, sale.id, _RET_SERIALIZED)
    line = db.exec(select(SaleLine).where(SaleLine.sale_id == sale.id)).one()
    ret = crud.create_sale_return(
        session=db,
        sale_id=sale.id,
        payload=SaleReturnCreateRequest(
            idempotency_key=uuid.uuid4(),
            reason="dead on arrival",
            lines=[SaleReturnLineInput(sale_line_id=line.id, quantity=1)],
        ),
        created_by_user_id=admin.id,
    )
    _pin_return(db, ret.id, _RET_SERIALIZED)

    report = crud.margin_report(
        session=db, year=2027, month=12, group_by=MarginDimension.PRODUCT
    )
    row = next(r for r in report.rows if r.key == str(seed["serialized"].id))
    # Sold for 500 (cost 300) then fully returned: both sides cancel.
    assert row.revenue_thb == Decimal("0.00")
    assert row.cogs_thb == Decimal("0.00")
