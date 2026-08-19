import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app import crud
from app.api.deps import CurrentUser, SessionDep, get_current_user
from app.models import (
    ServiceTicket,
    ServiceTicketPartPublic,
    ServiceTicketPublic,
    ServiceTicketRecordRequest,
)
from app.services import notify

router = APIRouter(prefix="/service-tickets", tags=["service-tickets"])


def _to_public(*, session: SessionDep, ticket: ServiceTicket) -> ServiceTicketPublic:
    parts = crud.list_service_ticket_parts(session=session, ticket_id=ticket.id)
    return ServiceTicketPublic(
        id=ticket.id,
        customer_id=ticket.customer_id,
        issue=ticket.issue,
        resolution=ticket.resolution,
        notes=ticket.notes,
        opened_at=ticket.opened_at,
        closed_at=ticket.closed_at,
        parts=[ServiceTicketPartPublic.model_validate(p) for p in parts],
    )


# Shared-team access (recorded decision D3, hardening spec 2026-06-11): any
# authenticated staff/admin may record a service ticket — the ~5-person warehouse
# team works shifts over shared objects (PRD §5). Ownership scoping was considered
# and rejected. No derived financials are exposed on this surface.
@router.post("/record", response_model=ServiceTicketPublic)
def record_service_ticket(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
    payload: ServiceTicketRecordRequest,
) -> ServiceTicketPublic:
    """Record a maintenance ticket in one atomic, idempotent call: open + parts +
    FIFO-consume + close (FR-008). Offline-replay-safe on idempotency_key."""
    ticket = crud.record_service_ticket(
        session=session,
        customer_id=payload.customer_id,
        issue=payload.issue,
        notes=payload.notes,
        resolution=payload.resolution,
        parts=payload.parts,
        idempotency_key=payload.idempotency_key,
        actor_user_id=current_user.id,
    )
    # FR-016: alert when consumption dropped a SKU below its low-stock threshold.
    crossed = crud.pop_low_stock_crossed(session)
    if crossed:
        background_tasks.add_task(notify.notify_low_stock_bg, product_ids=list(crossed))
    return _to_public(session=session, ticket=ticket)


@router.get(
    "/{ticket_id}",
    response_model=ServiceTicketPublic,
    dependencies=[Depends(get_current_user)],
)
def read_service_ticket(
    *, session: SessionDep, ticket_id: uuid.UUID
) -> ServiceTicketPublic:
    ticket = crud.get_service_ticket(session=session, ticket_id=ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Service ticket not found")
    return _to_public(session=session, ticket=ticket)
