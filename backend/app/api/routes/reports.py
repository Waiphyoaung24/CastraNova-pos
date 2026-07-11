from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app import crud
from app.api.deps import SessionDep, get_admin
from app.models import (
    Channel,
    HoldingPeriodReport,
    MarginBreakdownReport,
    MarginDimension,
    OverrideExceptionsReport,
)
from app.services import export

router = APIRouter(
    prefix="/reports", tags=["reports"], dependencies=[Depends(get_admin)]
)

# Reusable YYYY-MM (year 2000-2099) query param.
_Month = Annotated[
    str,
    Query(
        pattern=r"^20\d{2}-(0[1-9]|1[0-2])$",
        description="Reporting month in YYYY-MM (year 2000-2099)",
        examples=["2026-03"],
    ),
]


def _download(
    *, fmt: str, title: str, headers: list[str], rows: list[list[str]], filename: str
) -> Response:
    """Render (title, headers, rows) to a downloadable PDF or XLSX response."""
    if fmt == "pdf":
        return Response(
            content=export.render_table_pdf(title=title, headers=headers, rows=rows),
            media_type=export.PDF_MEDIA_TYPE,
            headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'},
        )
    return Response(
        content=export.render_table_xlsx(title=title, headers=headers, rows=rows),
        media_type=export.XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}.xlsx"'},
    )


# --- Channel margin (FR-013) --------------------------------------------------


_DIM_HEADER = {
    MarginDimension.CHANNEL: "Channel",
    MarginDimension.PRODUCT: "Product",
    MarginDimension.CUSTOMER: "Customer",
    MarginDimension.PROJECT: "Project",
}


def _channel_margin_table(
    report: MarginBreakdownReport,
) -> tuple[str, list[str], list[list[str]]]:
    first = _DIM_HEADER[report.group_by]
    headers = [first, "Revenue (THB)", "COGS (THB)", "Margin (THB)"]
    rows = [
        [r.label, str(r.revenue_thb), str(r.cogs_thb), str(r.margin_thb)]
        for r in report.rows
    ]
    rows.append(
        [
            "TOTAL",
            str(report.total_revenue_thb),
            str(report.total_cogs_thb),
            str(report.total_margin_thb),
        ]
    )
    scope = f" — {report.channel.value}" if report.channel else ""
    title = f"Channel Margin — {report.month} — by {first}{scope}"
    return title, headers, rows


@router.get("/channel-margin", response_model=MarginBreakdownReport)
def channel_margin(
    *,
    session: SessionDep,
    month: _Month,
    group_by: MarginDimension = MarginDimension.CHANNEL,
    channel: Channel | None = None,
) -> MarginBreakdownReport:
    """Monthly revenue/COGS/margin grouped by ``group_by`` (channel default),
    optionally scoped to one ``channel``; admin-only (FR-013, spec §8)."""
    return crud.margin_report(
        session=session, year=int(month[:4]), month=int(month[5:7]),
        group_by=group_by, channel=channel,
    )


@router.get("/channel-margin.pdf")
def channel_margin_pdf(
    *,
    session: SessionDep,
    month: _Month,
    group_by: MarginDimension = MarginDimension.CHANNEL,
    channel: Channel | None = None,
) -> Response:
    report = crud.margin_report(
        session=session, year=int(month[:4]), month=int(month[5:7]),
        group_by=group_by, channel=channel,
    )
    title, headers, rows = _channel_margin_table(report)
    suffix = f"-by-{group_by.value}" + (f"-{channel.value}" if channel else "")
    return _download(
        fmt="pdf", title=title, headers=headers, rows=rows,
        filename=f"channel-margin-{month}{suffix}",
    )


@router.get("/channel-margin.xlsx")
def channel_margin_xlsx(
    *,
    session: SessionDep,
    month: _Month,
    group_by: MarginDimension = MarginDimension.CHANNEL,
    channel: Channel | None = None,
) -> Response:
    report = crud.margin_report(
        session=session, year=int(month[:4]), month=int(month[5:7]),
        group_by=group_by, channel=channel,
    )
    title, headers, rows = _channel_margin_table(report)
    suffix = f"-by-{group_by.value}" + (f"-{channel.value}" if channel else "")
    return _download(
        fmt="xlsx", title=title, headers=headers, rows=rows,
        filename=f"channel-margin-{month}{suffix}",
    )


# --- Override exceptions (FR-010) ---------------------------------------------


def _override_exceptions_table(
    report: OverrideExceptionsReport,
) -> tuple[str, list[str], list[list[str]]]:
    headers = [
        "Created", "SKU", "Target", "Default (THB)", "Requested (THB)",
        "Deviation %", "State", "Reason",
    ]
    rows = [
        [
            r.created_at.isoformat(),
            r.sku,
            r.target_kind.value,
            str(r.default_price_thb),
            str(r.requested_price_thb),
            str(r.deviation_pct),
            r.state.value,
            r.reason,
        ]
        for r in report.rows
    ]
    return f"Override Exceptions — {report.month}", headers, rows


@router.get("/override-exceptions", response_model=OverrideExceptionsReport)
def override_exceptions(
    *, session: SessionDep, month: _Month
) -> OverrideExceptionsReport:
    """Monthly pricing-override exceptions for ``month`` (YYYY-MM), admin-only
    (FR-010, spec §8). Lists every override requested that month with per-state
    counts."""
    year, mon = int(month[:4]), int(month[5:7])
    return crud.override_exceptions_report(session=session, year=year, month=mon)


@router.get("/override-exceptions.pdf")
def override_exceptions_pdf(*, session: SessionDep, month: _Month) -> Response:
    report = crud.override_exceptions_report(
        session=session, year=int(month[:4]), month=int(month[5:7])
    )
    title, headers, rows = _override_exceptions_table(report)
    return _download(
        fmt="pdf", title=title, headers=headers, rows=rows,
        filename=f"override-exceptions-{month}",
    )


@router.get("/override-exceptions.xlsx")
def override_exceptions_xlsx(*, session: SessionDep, month: _Month) -> Response:
    report = crud.override_exceptions_report(
        session=session, year=int(month[:4]), month=int(month[5:7])
    )
    title, headers, rows = _override_exceptions_table(report)
    return _download(
        fmt="xlsx", title=title, headers=headers, rows=rows,
        filename=f"override-exceptions-{month}",
    )


# --- Holding period (FR-014) --------------------------------------------------


def _holding_period_table(
    report: HoldingPeriodReport,
) -> tuple[str, list[str], list[list[str]]]:
    headers = [
        "Mode", "SKU", "Reference", "Received", "Holding days", "Qty", "Over threshold",
    ]
    rows = [
        [
            r.tracking_mode.value,
            r.sku,
            r.reference,
            r.received_at.isoformat(),
            str(r.holding_days),
            str(r.quantity),
            "YES" if r.over_threshold else "",
        ]
        for r in report.rows
    ]
    return f"Holding Period (>{report.threshold_days}d flagged)", headers, rows


@router.get("/holding-period", response_model=HoldingPeriodReport)
def holding_period(
    *, session: SessionDep, over_threshold_only: bool = False
) -> HoldingPeriodReport:
    """In-stock holding period per SERIALIZED unit + per QUANTITY SKU (oldest
    active batch), flagged against the system_setting threshold, admin-only
    (FR-014, spec §8)."""
    return crud.holding_period_report(
        session=session, only_over_threshold=over_threshold_only
    )


@router.get("/holding-period.pdf")
def holding_period_pdf(
    *, session: SessionDep, over_threshold_only: bool = False
) -> Response:
    report = crud.holding_period_report(
        session=session, only_over_threshold=over_threshold_only
    )
    title, headers, rows = _holding_period_table(report)
    return _download(
        fmt="pdf", title=title, headers=headers, rows=rows, filename="holding-period",
    )


@router.get("/holding-period.xlsx")
def holding_period_xlsx(
    *, session: SessionDep, over_threshold_only: bool = False
) -> Response:
    report = crud.holding_period_report(
        session=session, only_over_threshold=over_threshold_only
    )
    title, headers, rows = _holding_period_table(report)
    return _download(
        fmt="xlsx", title=title, headers=headers, rows=rows, filename="holding-period",
    )
