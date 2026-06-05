from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app import crud
from app.api.deps import SessionDep, get_admin
from app.models import (
    ChannelMarginReport,
    HoldingPeriodReport,
    OverrideExceptionsReport,
)

router = APIRouter(
    prefix="/reports", tags=["reports"], dependencies=[Depends(get_admin)]
)


@router.get("/channel-margin", response_model=ChannelMarginReport)
def channel_margin(
    *,
    session: SessionDep,
    month: Annotated[
        str,
        Query(
            pattern=r"^20\d{2}-(0[1-9]|1[0-2])$",
            description="Reporting month in YYYY-MM (year 2000-2099)",
            examples=["2026-03"],
        ),
    ],
) -> ChannelMarginReport:
    """Monthly revenue/COGS/margin by derived channel for ``month`` (YYYY-MM),
    admin-only (FR-013, spec §8)."""
    year, mon = int(month[:4]), int(month[5:7])
    return crud.channel_margin_report(session=session, year=year, month=mon)


@router.get("/override-exceptions", response_model=OverrideExceptionsReport)
def override_exceptions(
    *,
    session: SessionDep,
    month: Annotated[
        str,
        Query(
            pattern=r"^20\d{2}-(0[1-9]|1[0-2])$",
            description="Reporting month in YYYY-MM (year 2000-2099)",
            examples=["2026-03"],
        ),
    ],
) -> OverrideExceptionsReport:
    """Monthly pricing-override exceptions for ``month`` (YYYY-MM), admin-only
    (FR-010, spec §8). Lists every override requested that month with per-state
    counts."""
    year, mon = int(month[:4]), int(month[5:7])
    return crud.override_exceptions_report(session=session, year=year, month=mon)


@router.get("/holding-period", response_model=HoldingPeriodReport)
def holding_period(
    *,
    session: SessionDep,
    over_threshold_only: bool = False,
) -> HoldingPeriodReport:
    """In-stock holding period per SERIALIZED unit + per QUANTITY SKU (oldest
    active batch), flagged against the system_setting threshold, admin-only
    (FR-014, spec §8)."""
    return crud.holding_period_report(
        session=session, only_over_threshold=over_threshold_only
    )
