import re

from fastapi import APIRouter, Depends, HTTPException

from app import crud
from app.api.deps import SessionDep, get_admin
from app.models import ChannelMarginReport

router = APIRouter(
    prefix="/reports", tags=["reports"], dependencies=[Depends(get_admin)]
)

_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


@router.get("/channel-margin", response_model=ChannelMarginReport)
def channel_margin(*, session: SessionDep, month: str) -> ChannelMarginReport:
    """Monthly revenue/COGS/margin by derived channel for ``month`` (YYYY-MM),
    admin-only (FR-013, spec §8)."""
    m = _MONTH_RE.match(month)
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise HTTPException(status_code=422, detail="month must be YYYY-MM")
    return crud.channel_margin_report(
        session=session, year=int(m.group(1)), month=int(m.group(2))
    )
