import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from app import crud
from app.api.deps import CurrentUser, SessionDep, get_admin, get_current_user
from app.models import (
    ProjectPull,
    ProjectPullCreate,
    ProjectPullFulfill,
    ProjectPullLinePublic,
    ProjectPullPublic,
    ProjectPullState,
)
from app.services import notify

router = APIRouter(prefix="/project-pulls", tags=["project-pulls"])


def _to_public(*, session: SessionDep, pull: ProjectPull) -> ProjectPullPublic:
    lines = crud.list_project_pull_lines(session=session, pull_id=pull.id)
    return ProjectPullPublic(
        id=pull.id,
        project_id=pull.project_id,
        customer_id=pull.customer_id,
        state=pull.state,
        admin_notes=pull.admin_notes,
        created_by_user_id=pull.created_by_user_id,
        created_at=pull.created_at,
        fulfilled_at=pull.fulfilled_at,
        fulfilled_by_user_id=pull.fulfilled_by_user_id,
        cancelled_at=pull.cancelled_at,
        cancelled_by_user_id=pull.cancelled_by_user_id,
        lines=[ProjectPullLinePublic.model_validate(ln) for ln in lines],
    )


@router.post("", response_model=ProjectPullPublic, dependencies=[Depends(get_admin)])
def create_project_pull(
    *, session: SessionDep, current_user: CurrentUser, payload: ProjectPullCreate
) -> ProjectPullPublic:
    pull = crud.create_project_pull(
        session=session, pull_in=payload, created_by_user_id=current_user.id
    )
    return _to_public(session=session, pull=pull)


@router.get(
    "",
    response_model=list[ProjectPullPublic],
    dependencies=[Depends(get_current_user)],
)
def read_project_pulls(
    *,
    session: SessionDep,
    state: ProjectPullState | None = None,
    skip: Annotated[int, Query(ge=0, le=10_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[ProjectPullPublic]:
    pulls = crud.list_project_pulls(
        session=session, state=state, skip=skip, limit=limit
    )
    return [_to_public(session=session, pull=p) for p in pulls]


@router.get(
    "/{pull_id}",
    response_model=ProjectPullPublic,
    dependencies=[Depends(get_current_user)],
)
def read_project_pull(
    *, session: SessionDep, pull_id: uuid.UUID
) -> ProjectPullPublic:
    pull = crud.get_project_pull(session=session, pull_id=pull_id)
    if not pull:
        raise HTTPException(status_code=404, detail="Project pull not found")
    return _to_public(session=session, pull=pull)


# Fulfill is intentionally open to staff + admin per the 5.3 role matrix
# (create/cancel are admin-only, already gated above).
# Shared-team access (recorded decision D3, hardening spec 2026-06-11): any
# authenticated staff/admin may act on any project pull — the ~5-person
# warehouse team works shifts over shared objects (PRD §5). Ownership scoping
# was considered and rejected. No derived financials are exposed on this
# surface.
@router.post(
    "/{pull_id}/fulfill",
    response_model=ProjectPullPublic,
    dependencies=[Depends(get_current_user)],
)
def fulfill_project_pull(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
    pull_id: uuid.UUID,
    payload: ProjectPullFulfill,
) -> ProjectPullPublic:
    pull = crud.fulfill_project_pull(
        session=session,
        pull_id=pull_id,
        fulfill_lines=payload.lines,
        actor_user_id=current_user.id,
    )
    # FR-018: notify BKK admins on a SHORT settlement. Dispatched to a background
    # task (its own session, swallows errors) so outbound HTTP + retries never
    # block the request or turn a successful fulfill into a 500.
    if pull.state == ProjectPullState.SHORT:
        background_tasks.add_task(notify.notify_pull_short_bg, pull_id=pull.id)
    # FR-016: alert when fulfillment dropped a SKU below its low-stock threshold.
    crossed = crud.pop_low_stock_crossed(session)
    if crossed:
        background_tasks.add_task(notify.notify_low_stock_bg, product_ids=list(crossed))
    return _to_public(session=session, pull=pull)


@router.post(
    "/{pull_id}/cancel",
    response_model=ProjectPullPublic,
    dependencies=[Depends(get_admin)],
)
def cancel_project_pull(
    *, session: SessionDep, current_user: CurrentUser, pull_id: uuid.UUID
) -> ProjectPullPublic:
    pull = crud.cancel_project_pull(
        session=session, pull_id=pull_id, actor_user_id=current_user.id
    )
    return _to_public(session=session, pull=pull)
