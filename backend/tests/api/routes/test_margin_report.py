from sqlmodel import Session

from app import crud
from app.models import Channel, MarginDimension
from tests.api.routes.test_reports import seed  # noqa: F401  (pytest fixture)


def _totals(report):
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
