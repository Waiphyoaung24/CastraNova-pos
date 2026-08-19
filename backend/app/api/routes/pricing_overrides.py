import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request

from app import crud
from app.api.deps import AdminUser, CurrentUser, SessionDep, get_admin, is_admin
from app.core.limiter import (
    PRICING_OVERRIDE_POLL_RATE_LIMIT,
    PRICING_OVERRIDE_RATE_LIMIT,
    limiter,
)
from app.models import (
    OverrideState,
    PricingOverrideCreate,
    PricingOverrideDecision,
    PricingOverridePublic,
    PricingOverridesPublic,
)
from app.services import notify

router = APIRouter(prefix="/pricing-overrides", tags=["pricing-overrides"])


@router.post("", response_model=PricingOverridePublic)
@limiter.limit(PRICING_OVERRIDE_RATE_LIMIT)
def create_pricing_override(
    *,
    request: Request,  # noqa: ARG001 — required by slowapi's rate-limit decorator
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
    product = crud.get_product(session=session, product_id=override.product_id)
    return PricingOverridePublic.model_validate(
        override, update={"product_sku": product.sku if product else ""}
    )


@router.get(
    "",
    response_model=PricingOverridesPublic,
    dependencies=[Depends(get_admin)],
)
def list_pricing_overrides(
    *,
    session: SessionDep,
    state: OverrideState | None = None,
    skip: Annotated[int, Query(ge=0, le=10_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> PricingOverridesPublic:
    """Admin queue of override requests, newest first (FR-010)."""
    rows = crud.list_pricing_overrides(
        session=session, state=state, skip=skip, limit=limit
    )
    data = []
    for row in rows:
        product = crud.get_product(session=session, product_id=row.product_id)
        data.append(
            PricingOverridePublic.model_validate(
                row, update={"product_sku": product.sku if product else ""}
            )
        )
    return PricingOverridesPublic(
        data=data, count=crud.count_pricing_overrides(session=session, state=state)
    )


@router.get("/{override_id}", response_model=PricingOverridePublic)
@limiter.limit(PRICING_OVERRIDE_POLL_RATE_LIMIT)
def get_pricing_override(
    *,
    request: Request,  # noqa: ARG001 — required by slowapi's rate-limit decorator
    session: SessionDep,
    current_user: CurrentUser,
    override_id: uuid.UUID,
) -> PricingOverridePublic:
    """Read one override request (FR-010). The requester polls this while their
    request is PENDING; admins may read any. Anyone else gets 403."""
    override = crud.get_pricing_override(session=session, override_id=override_id)
    if not override:
        # 404 before the permission check is deliberate: ids are non-guessable
        # UUIDv4s, so existence disclosure to a non-creator is a non-issue here
        # (contrast users.py, which checks privilege first on enumerable targets).
        raise HTTPException(status_code=404, detail="Override request not found")
    if override.created_by_user_id != current_user.id and not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    product = crud.get_product(session=session, product_id=override.product_id)
    return PricingOverridePublic.model_validate(
        override, update={"product_sku": product.sku if product else ""}
    )


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
    product = crud.get_product(session=session, product_id=override.product_id)
    return PricingOverridePublic.model_validate(
        override, update={"product_sku": product.sku if product else ""}
    )
