import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app import crud
from app.api.deps import AdminUser, CurrentUser, SessionDep, get_admin
from app.models import (
    OverrideState,
    PricingOverrideCreate,
    PricingOverrideDecision,
    PricingOverridePublic,
)
from app.services import notify

router = APIRouter(prefix="/pricing-overrides", tags=["pricing-overrides"])


@router.post("", response_model=PricingOverridePublic)
def create_pricing_override(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
    payload: PricingOverrideCreate,
) -> PricingOverridePublic:
    """Request a pricing override (FR-010). Staff request it mid-sale/ticket;
    AUTO_APPROVED within the configured deviation threshold, else PENDING — in
    which case admins are notified to decide."""
    override = crud.create_pricing_override(
        session=session,
        override_in=payload,
        created_by_user_id=current_user.id,
    )
    if override.state == OverrideState.PENDING:
        background_tasks.add_task(
            notify.notify_override_pending_bg, override_id=override.id
        )
    return PricingOverridePublic.model_validate(override)


@router.get(
    "",
    response_model=list[PricingOverridePublic],
    dependencies=[Depends(get_admin)],
)
def list_pricing_overrides(
    *,
    session: SessionDep,
    state: OverrideState | None = None,
    skip: Annotated[int, Query(ge=0, le=10_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[PricingOverridePublic]:
    """Admin queue of override requests, newest first (FR-010)."""
    rows = crud.list_pricing_overrides(
        session=session, state=state, skip=skip, limit=limit
    )
    return [PricingOverridePublic.model_validate(r) for r in rows]


@router.post(
    "/{override_id}/decide",
    response_model=PricingOverridePublic,
)
def decide_pricing_override(
    *,
    session: SessionDep,
    admin: AdminUser,
    override_id: uuid.UUID,
    payload: PricingOverrideDecision,
) -> PricingOverridePublic:
    """Admin approves or rejects a PENDING override (FR-010)."""
    override = crud.decide_pricing_override(
        session=session,
        override_id=override_id,
        decision=payload.decision,
        decided_by_user_id=admin.id,
    )
    return PricingOverridePublic.model_validate(override)
