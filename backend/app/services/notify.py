"""Outbound LINE + Viber push notifications (FR-018).

Outbound only. Each channel send retries 3x with exponential backoff (1s, 5s,
25s) on transient failures (5xx / transport errors); 4xx and Viber ``status != 0``
are permanent and never retried. ``notify`` is best-effort: it never raises to
its caller — every send outcome (including failures and un-enrolled recipients)
lands as one append-only ``notification_log`` row for weekly admin review.

Tokens are read from settings and sent in headers; they are never logged.
"""

import uuid
from typing import Any

import httpx
from sqlmodel import Session, select
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.models import (
    LineState,
    NotificationChannel,
    NotificationEvent,
    NotificationLog,
    NotificationPreference,
    NotificationStatus,
    ProjectPull,
    ProjectPullLine,
    User,
    UserRole,
)

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
VIBER_SEND_URL = "https://chatapi.viber.com/pa/send_message"

_TIMEOUT = 10.0


class RetryableNotifyError(Exception):
    """A transient send failure (HTTP 5xx or transport error) — retry."""


class PermanentNotifyError(Exception):
    """A non-retryable send failure (HTTP 4xx or Viber status != 0)."""


def _post(url: str, *, headers: dict[str, str], json: dict[str, Any]) -> httpx.Response:
    """The single network seam — monkeypatched in tests."""
    return httpx.post(url, headers=headers, json=json, timeout=_TIMEOUT)


def _classify(response: httpx.Response) -> None:
    """Raise on a non-2xx HTTP status: 5xx is retryable, 4xx is permanent."""
    if response.status_code >= 500:
        raise RetryableNotifyError(f"HTTP {response.status_code}")
    if response.status_code >= 400:
        raise PermanentNotifyError(f"HTTP {response.status_code}")


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, exp_base=5, max=25),
    retry=retry_if_exception_type((RetryableNotifyError, httpx.TransportError)),
    reraise=True,
)
def send_line(*, to: str, text: str) -> None:
    """Push a text message via the LINE Messaging API."""
    try:
        response = _post(
            LINE_PUSH_URL,
            headers={
                "Authorization": f"Bearer {settings.LINE_CHANNEL_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            json={"to": to, "messages": [{"type": "text", "text": text}]},
        )
    except httpx.TransportError as exc:
        raise RetryableNotifyError("transport error") from exc
    _classify(response)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, exp_base=5, max=25),
    retry=retry_if_exception_type((RetryableNotifyError, httpx.TransportError)),
    reraise=True,
)
def send_viber(*, to: str, text: str) -> None:
    """Push a text message via the Viber REST API."""
    try:
        response = _post(
            VIBER_SEND_URL,
            headers={
                "X-Viber-Auth-Token": settings.VIBER_AUTH_TOKEN or "",
                "Content-Type": "application/json",
            },
            json={"receiver": to, "type": "text", "text": text},
        )
    except httpx.TransportError as exc:
        raise RetryableNotifyError("transport error") from exc
    _classify(response)
    # Viber returns 200 with a body status code; non-zero is a permanent failure.
    status = response.json().get("status")
    if status != 0:
        raise PermanentNotifyError(f"viber status {status}")


# Map a channel to (send fn, address attribute on User).
_CHANNELS: dict[NotificationChannel, tuple[Any, str]] = {
    NotificationChannel.LINE: (send_line, "line_user_id"),
    NotificationChannel.VIBER: (send_viber, "viber_user_id"),
}


def _is_opted_in(
    *,
    session: Session,
    user_id: uuid.UUID,
    channel: NotificationChannel,
    event_type: NotificationEvent,
) -> bool:
    pref = session.exec(
        select(NotificationPreference).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.channel == channel,
            NotificationPreference.event_type == event_type,
        )
    ).first()
    return bool(pref and pref.enabled)


def notify(
    *,
    session: Session,
    event_type: NotificationEvent,
    recipients: list[User],
    payload: dict[str, Any],
) -> list[NotificationLog]:
    """Best-effort fan-out: for each opted-in (recipient, channel), send and
    record exactly one append-only log row. Never raises."""
    text = _render_text(event_type=event_type, payload=payload)
    logs: list[NotificationLog] = []

    for user in recipients:
        for channel, (send_fn, address_attr) in _CHANNELS.items():
            if not _is_opted_in(
                session=session,
                user_id=user.id,
                channel=channel,
                event_type=event_type,
            ):
                continue  # not opted in -> no send, no log

            address = getattr(user, address_attr)
            if not address:
                logs.append(
                    NotificationLog(
                        channel=channel,
                        event_type=event_type,
                        target_user_id=user.id,
                        payload=payload,
                        status=NotificationStatus.FAILED,
                        attempts=0,
                        last_error=(
                            f"{channel.value} recipient id not set (not enrolled)"
                        ),
                    )
                )
                continue

            try:
                send_fn(to=address, text=text)
            except Exception as exc:
                attempts = int(send_fn.statistics.get("attempt_number", 1))
                logs.append(
                    NotificationLog(
                        channel=channel,
                        event_type=event_type,
                        target_user_id=user.id,
                        payload=payload,
                        status=NotificationStatus.FAILED,
                        attempts=attempts,
                        last_error=str(exc)[:1024],
                    )
                )
            else:
                attempts = int(send_fn.statistics.get("attempt_number", 1))
                logs.append(
                    NotificationLog(
                        channel=channel,
                        event_type=event_type,
                        target_user_id=user.id,
                        payload=payload,
                        status=NotificationStatus.SENT,
                        attempts=attempts,
                    )
                )

    for log in logs:
        session.add(log)
    session.commit()
    for log in logs:
        session.refresh(log)
    return logs


def _render_text(*, event_type: NotificationEvent, payload: dict[str, Any]) -> str:
    if event_type == NotificationEvent.PULL_SHORT:
        return (
            f"Project pull {payload.get('pull_id')} settled SHORT "
            f"({payload.get('short_line_count')} line(s) short)."
        )
    return f"{event_type.value}: {payload}"


def notify_pull_short(
    *, session: Session, pull: ProjectPull
) -> list[NotificationLog]:
    """Notify every BKK_ADMIN of a SHORT project pull (FR-018, Flow D)."""
    recipients = list(
        session.exec(select(User).where(User.role == UserRole.BKK_ADMIN)).all()
    )
    lines = session.exec(
        select(ProjectPullLine).where(ProjectPullLine.project_pull_id == pull.id)
    ).all()
    short_line_count = sum(1 for ln in lines if ln.line_state == LineState.SHORT)
    payload: dict[str, Any] = {
        "pull_id": str(pull.id),
        "project_id": str(pull.project_id),
        "customer_id": str(pull.customer_id),
        "short_line_count": short_line_count,
    }
    return notify(
        session=session,
        event_type=NotificationEvent.PULL_SHORT,
        recipients=recipients,
        payload=payload,
    )
