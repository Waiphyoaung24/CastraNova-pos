import json
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session
from starlette.concurrency import run_in_threadpool

from app import crud
from app.api.deps import CurrentUser, SessionDep, bind_rate_limit_identity
from app.core.config import settings
from app.core.limiter import (
    LINE_CONNECT_RATE_LIMIT,
    TELEGRAM_CONFIRM_RATE_LIMIT,
    TELEGRAM_CONNECT_RATE_LIMIT,
    TELEGRAM_TEST_RATE_LIMIT,
    limiter,
    user_or_remote_address,
)
from app.models import (
    LineConfirmOutcome,
    LineConnectResponse,
    Message,
    NotificationPreferencePublic,
    NotificationPreferencesUpdate,
    NotificationStatus,
    TelegramConfirmOutcome,
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


@router.post(
    "/telegram/connect",
    response_model=TelegramConnectResponse,
    dependencies=[Depends(bind_rate_limit_identity)],
)
@limiter.limit(TELEGRAM_CONNECT_RATE_LIMIT, key_func=user_or_remote_address)
def connect_telegram(
    *,
    request: Request,  # noqa: ARG001 — required by slowapi's rate-limit decorator
    session: SessionDep,
    current_user: CurrentUser,
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


@router.post(
    "/telegram/confirm",
    response_model=TelegramConfirmResult,
    dependencies=[Depends(bind_rate_limit_identity)],
)
@limiter.limit(TELEGRAM_CONFIRM_RATE_LIMIT, key_func=user_or_remote_address)
def confirm_telegram(
    *,
    request: Request,  # noqa: ARG001 — required by slowapi's rate-limit decorator
    session: SessionDep,
    current_user: CurrentUser,
    payload: TelegramConfirmRequest,
) -> TelegramConfirmResult:
    """Resolve a pending connect code against Telegram's getUpdates. The
    frontend polls this a few times after the user taps Start, rather than
    requiring an explicit "I've done it" click."""
    match = None
    try:
        for update in notify.get_telegram_updates_cached():
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
    outcome = crud.confirm_telegram_connect_code(
        session=session,
        user=current_user,
        code=payload.code,
        chat_id=chat_id,
        username=username,
    )
    if outcome is TelegramConfirmOutcome.CONNECTED:
        return TelegramConfirmResult(connected=True, telegram_username=username)
    if outcome is TelegramConfirmOutcome.CHAT_ALREADY_LINKED:
        return TelegramConfirmResult(
            connected=False,
            error=(
                "This Telegram account is already connected to another user. "
                "Disconnect it there first, or use a different Telegram account."
            ),
        )
    return TelegramConfirmResult(connected=False)


@router.delete("/telegram/disconnect", response_model=Message)
def disconnect_telegram(
    *, session: SessionDep, current_user: CurrentUser
) -> Message:
    crud.disconnect_telegram(session=session, user=current_user)
    return Message(message="Telegram disconnected")


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
        text="✅ CastraNova POS\nYour Telegram notifications are working.",
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


@router.post(
    "/line/connect",
    response_model=LineConnectResponse,
    dependencies=[Depends(bind_rate_limit_identity)],
)
@limiter.limit(LINE_CONNECT_RATE_LIMIT, key_func=user_or_remote_address)
def connect_line(
    *,
    request: Request,  # noqa: ARG001 — required by slowapi's rate-limit decorator
    session: SessionDep,
    current_user: CurrentUser,
) -> LineConnectResponse:
    """Mint a one-time code + a line.me deep link that opens a chat with the
    Official Account and pre-types the code, so the user only taps send.

    A plain add-friend link would fire a `follow` event carrying userId but no
    code, which cannot identify which POS user connected -- hence the
    prefilled-message round trip.

    Re-runnable: calling again mints a fresh code, so switching LINE accounts
    is one more tap, not a dead end.
    """
    if not settings.LINE_BOT_BASIC_ID:
        raise HTTPException(status_code=400, detail="LINE is not configured")
    record = crud.create_line_connect_code(session=session, user_id=current_user.id)
    # Percent-encode the basic ID: an unencoded '@' works but LINE deprecates
    # it. The code is [0-9a-f] so it needs no encoding, but quote() it anyway
    # rather than relying on that invariant holding forever.
    deep_link = (
        f"https://line.me/R/oaMessage/{quote(settings.LINE_BOT_BASIC_ID, safe='')}"
        f"/?{quote(record.code, safe='')}"
    )
    return LineConnectResponse(
        code=record.code,
        deep_link=deep_link,
        qr_code_data_uri=render_qr_png_data_uri(deep_link),
        expires_at=record.expires_at,
    )


@router.delete("/line/disconnect", response_model=Message)
def disconnect_line(*, session: SessionDep, current_user: CurrentUser) -> Message:
    crud.disconnect_line(session=session, user=current_user)
    return Message(message="LINE disconnected")


def _handle_line_event(*, session: Session, event: dict[str, Any]) -> None:
    """Process one LINE webhook event. Never raises: the caller must return
    200 even for events it ignores.

    Binds only on a text message from an individual user. A group or room
    source is ignored outright -- binding a group id would deliver a user's
    stock and pricing alerts into a group chat.
    """
    source = event.get("source") or {}
    line_user_id = source.get("userId")
    if source.get("type") != "user" or not line_user_id:
        return

    if event.get("type") == "unfollow":
        # The user blocked or removed the Official Account, so send_line can
        # no longer reach them -- but LINE returns 200 for pushes to a blocked
        # recipient, so nothing else would ever notice.
        crud.clear_line_user(session=session, line_user_id=line_user_id)
        return

    if event.get("type") != "message":
        return
    message = event.get("message") or {}
    if message.get("type") != "text":
        return

    code = (message.get("text") or "").strip()
    outcome = crud.confirm_line_connect_code(
        session=session, code=code, line_user_id=line_user_id
    )

    reply_token = event.get("replyToken")
    if not reply_token:
        return
    if outcome is LineConfirmOutcome.CONNECTED:
        text = "✅ CastraNova POS\nYour LINE account is now connected."
    elif outcome is LineConfirmOutcome.USER_ALREADY_LINKED:
        text = (
            "This LINE account is already connected to another CastraNova "
            "user. Disconnect it there first, then try again."
        )
    else:
        # PENDING: someone messaged the Official Account without a live code.
        # Staying silent is deliberate -- replying "invalid code" to arbitrary
        # text would confirm to a guesser that codes exist to be guessed.
        return

    try:
        notify.send_line_reply(reply_token=reply_token, text=text)
    except (notify.RetryableNotifyError, notify.PermanentNotifyError):
        # Best-effort, exactly like notify(): the bind already committed and
        # must not be rolled back because a courtesy message failed. Reply
        # tokens are single-use and short-lived, so there is nothing to retry.
        pass


@router.post("/line/webhook", response_model=Message)
async def line_webhook(*, request: Request, session: SessionDep) -> Message:
    """Receive LINE Messaging API events. Public and unauthenticated.

    The signature is the only gate, and deliberately the only gate: there is
    no rate limiter here because LINE posts from shared, rotating IPs, so an
    IP-keyed cap would drop legitimate events.

    Async purely to read the raw body -- the handler itself is sync DB work.
    """
    if not settings.LINE_CHANNEL_SECRET:
        raise HTTPException(status_code=503, detail="LINE is not configured")

    # Raw bytes, before any parsing. Verifying a re-serialized dict breaks the
    # HMAC -- this ordering is the whole point.
    body = await request.body()
    if not notify.verify_line_signature(
        body=body, signature=request.headers.get("x-line-signature")
    ):
        raise HTTPException(status_code=400, detail="invalid signature")

    try:
        payload = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid body") from None

    events = payload.get("events") if isinstance(payload, dict) else None
    if isinstance(events, list):
        for event in events:
            if isinstance(event, dict):
                # This route must be async to await the raw body, but the
                # handler is blocking DB work. Calling it directly would stall
                # the event loop for every other request in flight; every
                # other route in this file is sync and gets a worker thread
                # from FastAPI automatically. Sequential, not concurrent: two
                # events in one POST share a Session, which is not thread-safe.
                await run_in_threadpool(
                    _handle_line_event, session=session, event=event
                )

    # Always 200 past the signature gate, including for ignored events: a
    # non-200 makes LINE retry and eventually disable the webhook.
    return Message(message="ok")
