from fastapi import APIRouter

from app import crud
from app.api.deps import CurrentUser, SessionDep
from app.models import (
    NotificationPreferencePublic,
    NotificationPreferencesUpdate,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get(
    "/preferences", response_model=list[NotificationPreferencePublic]
)
def read_notification_preferences(
    *, session: SessionDep, current_user: CurrentUser
) -> list[NotificationPreferencePublic]:
    return crud.list_notification_preferences(session=session, user=current_user)


@router.patch(
    "/preferences", response_model=list[NotificationPreferencePublic]
)
def update_notification_preferences(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    payload: NotificationPreferencesUpdate,
) -> list[NotificationPreferencePublic]:
    return crud.upsert_notification_preferences(
        session=session,
        user=current_user,
        updates=payload.preferences,
    )
