"""Outbound LINE + Viber push notifications (FR-018).

Outbound only. Each channel send runs 4 attempts / 3 retries with exponential
backoff (waits 1s, 5s, 25s) on transient failures (5xx / transport errors); 4xx
and Viber ``status != 0`` are permanent and never retried. ``notify`` is
best-effort: it never raises to its caller — every send outcome (including
failures and un-enrolled recipients) lands as one append-only
``notification_log`` row for weekly admin review.

Tokens are read from settings and sent in headers; they are never logged.
"""

import logging
import uuid
from typing import Any

import httpx
from sqlalchemy import func
from sqlmodel import Session, col, select
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.core.db import engine
from app.models import (
    LineState,
    NotificationChannel,
    NotificationEvent,
    NotificationLog,
    NotificationPreference,
    NotificationStatus,
    PartBatch,
    Product,
    ProjectPull,
    ProjectPullLine,
    TrackingMode,
    Unit,
    UnitState,
    User,
    UserRole,
)

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
VIBER_SEND_URL = "https://chatapi.viber.com/pa/send_message"

_TIMEOUT = 10.0

logger = logging.getLogger(__name__)


class RetryableNotifyError(Exception):
    """A transient send failure (HTTP 5xx or transport error) — retry."""


class PermanentNotifyError(Exception):
    """A non-retryable send failure (HTTP 4xx or Viber status != 0)."""


def _post(url: str, *, headers: dict[str, str], json: dict[str, Any]) -> httpx.Response:
    """The single network seam — monkeypatched in tests."""
    return httpx.post(
        url, headers=headers, json=json, timeout=_TIMEOUT, trust_env=False
    )


def _classify(response: httpx.Response) -> None:
    """Raise on a non-2xx HTTP status: 5xx is retryable, 4xx is permanent."""
    if response.status_code >= 500:
        raise RetryableNotifyError(f"HTTP {response.status_code}")
    if response.status_code >= 400:
        raise PermanentNotifyError(f"HTTP {response.status_code}")


def send_line(*, to: str, text: str) -> None:
    """Push a text message via the LINE Messaging API (single raw attempt)."""
    if not settings.LINE_CHANNEL_ACCESS_TOKEN:
        raise PermanentNotifyError("LINE_TOKEN not configured")
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


def send_viber(*, to: str, text: str) -> None:
    """Push a text message via the Viber REST API (single raw attempt)."""
    if not settings.VIBER_AUTH_TOKEN:
        raise PermanentNotifyError("VIBER_TOKEN not configured")
    try:
        response = _post(
            VIBER_SEND_URL,
            headers={
                "X-Viber-Auth-Token": settings.VIBER_AUTH_TOKEN,
                "Content-Type": "application/json",
            },
            json={"receiver": to, "type": "text", "text": text},
        )
    except httpx.TransportError as exc:
        raise RetryableNotifyError("transport error") from exc
    _classify(response)
    # Viber returns 200 with a body status code; an explicit non-zero status is a
    # permanent failure. An absent key on a 200 is treated as success (status 0).
    status = response.json().get("status", 0)
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
    record exactly one append-only log row. Never raises a notify failure."""
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

            retryer = Retrying(
                stop=stop_after_attempt(4),
                wait=wait_exponential(multiplier=1, exp_base=5, max=25),
                retry=retry_if_exception_type(RetryableNotifyError),
                reraise=True,
            )
            try:
                retryer(send_fn, to=address, text=text)
            except (RetryableNotifyError, PermanentNotifyError) as exc:
                logs.append(
                    NotificationLog(
                        channel=channel,
                        event_type=event_type,
                        target_user_id=user.id,
                        payload=payload,
                        status=NotificationStatus.FAILED,
                        attempts=int(retryer.statistics.get("attempt_number", 1)),
                        last_error=str(exc)[:1024],
                    )
                )
            else:
                logs.append(
                    NotificationLog(
                        channel=channel,
                        event_type=event_type,
                        target_user_id=user.id,
                        payload=payload,
                        status=NotificationStatus.SENT,
                        attempts=int(retryer.statistics.get("attempt_number", 1)),
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
    if event_type == NotificationEvent.LOW_STOCK:
        return (
            f"Low stock: {payload.get('sku')} — {payload.get('on_hand')} left "
            f"(min {payload.get('min_stock_level')})."
        )
    # Never push a raw payload (may carry financial fields). Each new event must
    # add an explicit, safe template here.
    raise NotImplementedError(f"No render template for {event_type!r}")


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


def _on_hand(session: Session, product: Product) -> int:
    if product.tracking_mode == TrackingMode.QUANTITY:
        total = session.exec(
            select(func.coalesce(func.sum(PartBatch.remaining_qty), 0)).where(
                PartBatch.product_id == product.id
            )
        ).one()
        return int(total)
    count = session.exec(
        select(func.count()).where(
            Unit.product_id == product.id,
            Unit.current_state == UnitState.IN_STOCK,
        )
    ).one()
    return int(count)


def notify_low_stock(
    *, session: Session, product_ids: list[uuid.UUID]
) -> list[NotificationLog]:
    """Notify every user opted into LOW_STOCK that a SKU dropped below its
    threshold (FR-016). Re-checks on-hand < threshold per product to guard
    against a replenishment between the consuming commit and dispatch; recipients
    are any-role users with an enabled LOW_STOCK preference (opt-in driven)."""
    recipients = list(
        session.exec(
            select(User)
            .join(
                NotificationPreference,
                col(NotificationPreference.user_id) == col(User.id),
            )
            .where(
                NotificationPreference.event_type == NotificationEvent.LOW_STOCK,
                col(NotificationPreference.enabled).is_(True),
            )
            .distinct()
        ).all()
    )

    logs: list[NotificationLog] = []
    for product_id in product_ids:
        product = session.get(Product, product_id)
        if product is None:
            continue
        threshold = product.default_min_stock_level
        if threshold is None:
            continue
        on_hand = _on_hand(session, product)
        if on_hand >= threshold:
            continue  # replenished since the crossing — no longer low
        payload: dict[str, Any] = {
            "product_id": str(product.id),
            "sku": product.sku,
            "on_hand": on_hand,
            "min_stock_level": threshold,
        }
        logs.extend(
            notify(
                session=session,
                event_type=NotificationEvent.LOW_STOCK,
                recipients=recipients,
                payload=payload,
            )
        )
    return logs


def notify_low_stock_bg(*, product_ids: list[uuid.UUID]) -> None:
    """BackgroundTasks entrypoint for low-stock alerts. Opens its OWN session
    and can never raise out of the background task (best-effort)."""
    try:
        with Session(engine) as session:
            notify_low_stock(session=session, product_ids=product_ids)
    except Exception:  # noqa: BLE001 — belt: best-effort, swallow + log
        logger.exception("notify_low_stock_bg failed for product_ids=%s", product_ids)


def notify_pull_short_bg(*, pull_id: uuid.UUID) -> None:
    """BackgroundTasks entrypoint: notify off the request hot path.

    Opens its OWN session (the request session is closed once the response is
    sent) and can never raise out of the background task — a notify failure must
    not affect the already-committed fulfill.
    """
    try:
        with Session(engine) as session:
            pull = session.get(ProjectPull, pull_id)
            if pull is None:
                return
            notify_pull_short(session=session, pull=pull)
    except Exception:  # noqa: BLE001 — belt: best-effort, swallow + log
        logger.exception("notify_pull_short_bg failed for pull_id=%s", pull_id)
