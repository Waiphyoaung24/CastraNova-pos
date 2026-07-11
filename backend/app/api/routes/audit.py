import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app import crud
from app.api.deps import SessionDep, get_admin
from app.models import AuditEntryPublic, MovementType

router = APIRouter(
    prefix="/audit", tags=["audit"], dependencies=[Depends(get_admin)]
)


@router.get("", response_model=list[AuditEntryPublic])
def list_audit(
    *,
    session: SessionDep,
    event_type: MovementType | None = None,
    from_date: Annotated[
        datetime | None, Query(description="ISO-8601 lower bound, inclusive")
    ] = None,
    to_date: Annotated[
        datetime | None, Query(description="ISO-8601 upper bound, exclusive")
    ] = None,
    actor_user_id: Annotated[
        uuid.UUID | None, Query(description="Restrict to a single acting user")
    ] = None,
    product_id: Annotated[
        uuid.UUID | None, Query(description="Restrict to PART entries for a product")
    ] = None,
    unit_id: Annotated[
        uuid.UUID | None, Query(description="Restrict to UNIT entries for a unit")
    ] = None,
    sku: Annotated[
        str | None,
        Query(description="Restrict to a product's SKU (spans UNIT + PART ledgers)"),
    ] = None,
    skip: Annotated[int, Query(ge=0, le=10_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AuditEntryPublic]:
    """Chronological (occurred_at DESC) audit trail over the append-only
    unit_movement + part_movement ledgers, admin-only (FR-019). ``product_id``
    restricts to PART entries; ``unit_id`` restricts to UNIT entries; ``sku``
    scopes to a product across whichever ledger it uses."""
    return crud.list_audit(
        session=session,
        event_type=event_type,
        from_date=from_date,
        to_date=to_date,
        actor_user_id=actor_user_id,
        product_id=product_id,
        unit_id=unit_id,
        sku=sku,
        skip=skip,
        limit=limit,
    )
