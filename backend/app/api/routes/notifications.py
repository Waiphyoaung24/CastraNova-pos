from fastapi import APIRouter, HTTPException, Request

from app import crud
from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.core.limiter import TELEGRAM_TEST_RATE_LIMIT, limiter
from app.models import (
    NotificationPreferencePublic,
    NotificationPreferencesUpdate,
    NotificationStatus,
    TelegramConfirmRequest,
    TelegramConfirmResult,
    TelegramConnectResponse,
    TelegramStatus,
    TelegramTestResult,
)
from app.services import notify
from app.services.barcode import render_qr_png_data_uri

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


@router.post("/telegram/connect", response_model=TelegramConnectResponse)
def connect_telegram(
    *, session: SessionDep, current_user: CurrentUser
) -> TelegramConnectResponse:
    """Mint a one-time code + t.me deep link. Re-runnable: calling again
    mints a fresh code, so switching Telegram accounts is one more tap, not a
    dead end."""
    record = crud.create_telegram_connect_code(session=session, user_id=current_user.id)
    deep_link = f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start={record.code}"
    return TelegramConnectResponse(
        code=record.code,
        deep_link=deep_link,
        qr_code_data_uri=render_qr_png_data_uri(deep_link),
        expires_at=record.expires_at,
    )


@router.post("/telegram/confirm", response_model=TelegramConfirmResult)
def confirm_telegram(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    payload: TelegramConfirmRequest,
) -> TelegramConfirmResult:
    """Resolve a pending connect code against Telegram's getUpdates. The
    frontend polls this a few times after the user taps Start, rather than
    requiring an explicit "I've done it" click."""
    match = None
    try:
        for update in notify.get_telegram_updates():
            parsed = notify.parse_start_code(update)
            if parsed is not None and parsed[2] == payload.code:
                match = parsed
                break
    except (notify.RetryableNotifyError, notify.PermanentNotifyError):
        # Treated the same as "no match yet" -- the frontend just polls
        # again; there is nothing actionable for the user to do differently.
        return TelegramConfirmResult(connected=False)

    if match is None:
        return TelegramConfirmResult(connected=False)

    chat_id, username, _ = match
    connected = crud.confirm_telegram_connect_code(
        session=session,
        user=current_user,
        code=payload.code,
        chat_id=chat_id,
        username=username,
    )
    return TelegramConfirmResult(
        connected=connected, telegram_username=username if connected else None
    )


@router.post("/telegram/test", response_model=TelegramTestResult)
@limiter.limit(TELEGRAM_TEST_RATE_LIMIT)
def test_telegram(
    *,
    request: Request,  # noqa: ARG001 — required by slowapi's rate-limit decorator
    current_user: CurrentUser,
) -> TelegramTestResult:
    """Send a one-off probe message to the current user's connected
    Telegram. Bypasses the notification-preference opt-in check on purpose:
    this tests the address, not an event subscription."""
    if not current_user.telegram_chat_id:
        raise HTTPException(status_code=400, detail="Telegram is not connected")
    ok, detail = notify.send_telegram_test(
        to=current_user.telegram_chat_id,
        text="CastraNova POS: this is a test notification.",
    )
    return TelegramTestResult(ok=ok, detail=detail)


@router.get("/telegram/status", response_model=TelegramStatus)
def get_telegram_status(
    *, session: SessionDep, current_user: CurrentUser
) -> TelegramStatus:
    """Connection state for the connect card: whether Telegram is bound, the
    display username (so a stale binding is visible), and whether the most
    recent send attempt failed (bot blocked, chat deleted)."""
    latest = crud.get_latest_telegram_notification_log(
        session=session, user_id=current_user.id
    )
    failing = bool(latest and latest.status == NotificationStatus.FAILED)
    return TelegramStatus(
        connected=bool(current_user.telegram_chat_id),
        telegram_username=current_user.telegram_username,
        delivery_failing=failing,
        last_error=latest.last_error if failing and latest else None,
    )
