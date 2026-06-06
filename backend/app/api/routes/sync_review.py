import uuid

from fastapi import APIRouter, Depends

from app import crud
from app.api.deps import AdminUser, SessionDep, get_admin, get_current_user
from app.models import (
    SyncReviewItemCreate,
    SyncReviewItemPublic,
    SyncReviewItemStaffPublic,
    SyncReviewResolve,
    SyncReviewState,
)

router = APIRouter(prefix="/sync-review", tags=["sync-review"])


@router.post(
    "",
    response_model=SyncReviewItemStaffPublic,
    dependencies=[Depends(get_current_user)],
)
def ingest_sync_review_item(
    *,
    session: SessionDep,
    data: SyncReviewItemCreate,
) -> SyncReviewItemStaffPublic:
    """Report a STALE/CONFLICT offline mutation for review (FR-021). Any
    authenticated device may ingest; idempotent on idempotency_key."""
    item = crud.create_sync_review_item(session=session, data=data)
    return SyncReviewItemStaffPublic.model_validate(item)


@router.get(
    "",
    response_model=list[SyncReviewItemPublic],
    dependencies=[Depends(get_admin)],
)
def list_sync_review_items(
    *,
    session: SessionDep,
    state: SyncReviewState | None = None,
) -> list[SyncReviewItemPublic]:
    """Admin review queue, optionally filtered by state (FR-021)."""
    items = crud.list_sync_review_items(session=session, state=state)
    return [SyncReviewItemPublic.model_validate(i) for i in items]


@router.post("/{item_id}/resolve", response_model=SyncReviewItemPublic)
def resolve_sync_review_item(
    *,
    session: SessionDep,
    admin: AdminUser,
    item_id: uuid.UUID,
    body: SyncReviewResolve,
) -> SyncReviewItemPublic:
    """Admin resolves or discards a PENDING review item (FR-021)."""
    item = crud.resolve_sync_review_item(
        session=session,
        item_id=item_id,
        admin_id=admin.id,
        new_state=body.state,
        note=body.note,
    )
    return SyncReviewItemPublic.model_validate(item)
