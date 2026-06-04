from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app import crud
from app.api.deps import SessionDep, get_admin
from app.models import ChannelMarginReport

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
