"""Outbound LINE + Viber + Telegram push notifications (FR-018).

Outbound only. Each channel send runs 4 attempts / 3 retries with exponential
backoff (waits 1s, 5s, 25s) on transient failures (5xx / transport errors); 4xx
and Viber ``status != 0`` are permanent and never retried. Telegram's 429
(rate-limited) is the one 4xx treated as transient. ``notify`` is best-effort:
it never raises to its caller — every send outcome (including failures and
un-enrolled recipients) lands as one append-only ``notification_log`` row for
weekly admin review.

Tokens are read from settings and never logged. LINE and Viber send theirs in a
header; Telegram's bot token rides in the URL path instead, so the Telegram URL
must never reach a log or an exception message.
"""

import logging
import threading
import time
import uuid
from typing import Any

import httpx
from sqlmodel import Session, col, select
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app import crud
from app.core.config import settings
from app.core.db import engine
from app.models import (
    LineState,
    NotificationChannel,
    NotificationEvent,
    NotificationLog,
    NotificationPreference,
    NotificationStatus,
    PricingOverrideRequest,
    Product,
    Project,
    ProjectPull,
    ProjectPullLine,
    User,
    UserRole,
)

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
VIBER_SEND_URL = "https://chatapi.viber.com/pa/send_message"
# Telegram takes the bot token in the path, so the URL itself is a secret.
TELEGRAM_SEND_URL_TEMPLATE = "https://api.telegram.org/bot{token}/sendMessage"
TELEGRAM_GET_UPDATES_URL_TEMPLATE = "https://api.telegram.org/bot{token}/getUpdates"

_TIMEOUT = 10.0

# Read the NEWEST updates, not the oldest. With no offset, Telegram returns
# "updates starting with the earliest unconfirmed update" capped at limit
# (default and max 100). This module never confirms updates -- they leave the
# queue only by ageing out at 24h -- so once >100 unconfirmed updates pile up,
# a freshly-sent /start sits outside the window and connect silently fails.
# A negative offset reads from the end of the queue instead. It confirms
# nothing, so there is still no offset state to persist or coordinate across
# workers, which is the property the no-offset design was protecting.
_GET_UPDATES_WINDOW = 100

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


def send_telegram(*, to: str, text: str) -> None:
    """Push a text message via the Telegram Bot API (single raw attempt).

    ``to`` is the recipient's chat id — a bot cannot message a user until that
    user has messaged it first, so the id is captured out-of-band at enrollment.
    """
    if not settings.TELEGRAM_BOT_TOKEN:
        raise PermanentNotifyError("TELEGRAM_TOKEN not configured")
    url = TELEGRAM_SEND_URL_TEMPLATE.format(token=settings.TELEGRAM_BOT_TOKEN)
    try:
        response = _post(
            url,
            headers={"Content-Type": "application/json"},
            json={"chat_id": to, "text": text},
        )
    except httpx.TransportError as exc:
        # Deliberately not chaining the URL/exc text — it carries the token.
        raise RetryableNotifyError("transport error") from exc
    # Telegram rate-limits with 429 + retry_after. _classify would call that
    # permanent and drop a merely throttled message, so catch it first.
    if response.status_code == 429:
        raise RetryableNotifyError("HTTP 429 (rate limited)")
    _classify(response)


def send_telegram_test(*, to: str, text: str) -> tuple[bool, str | None]:
    """Send a one-off test message and report the outcome directly, instead
    of raising Retryable/PermanentNotifyError.

    This is a synchronous, user-initiated probe of an address -- not part of
    the ``notify()`` fan-out -- so there is no retry policy or append-only
    log entry to feed; the caller just wants a pass/fail with a reason.
    Returns ``(ok, detail)``, where ``detail`` is Telegram's own
    ``description`` field on failure. Never the request URL/token — that
    only ever rides in the URL path (see module docstring).
    """
    if not settings.TELEGRAM_BOT_TOKEN:
        return False, "Telegram is not configured"
    url = TELEGRAM_SEND_URL_TEMPLATE.format(token=settings.TELEGRAM_BOT_TOKEN)
    try:
        response = _post(
            url,
            headers={"Content-Type": "application/json"},
            json={"chat_id": to, "text": text},
        )
    except httpx.TransportError:
        return False, "Could not reach Telegram"
    if response.status_code // 100 == 2:
        return True, None
    detail: str | None = None
    try:
        detail = response.json().get("description")
    except ValueError:
        pass
    return False, detail or f"HTTP {response.status_code}"


def get_telegram_updates() -> list[dict[str, Any]]:
    """Fetch pending Telegram updates (single raw attempt), WITHOUT
    acknowledging any of them.

    Deliberately never advances the update offset: Telegram retains
    unacknowledged updates for ~24h, so this trades an unbounded update
    backlog for having no poller and no offset state to persist or coordinate
    across workers.

    Reads the newest ``_GET_UPDATES_WINDOW`` updates via a negative offset --
    see that constant for why the default (oldest-first) window is a
    correctness bug here. Used to resolve enrollment codes sent via
    ``/start <code>`` -- see ``parse_start_code``.
    """
    if not settings.TELEGRAM_BOT_TOKEN:
        raise PermanentNotifyError("TELEGRAM_TOKEN not configured")
    url = TELEGRAM_GET_UPDATES_URL_TEMPLATE.format(token=settings.TELEGRAM_BOT_TOKEN)
    try:
        response = _post(
            url,
            headers={"Content-Type": "application/json"},
            json={"offset": -_GET_UPDATES_WINDOW},
        )
    except httpx.TransportError as exc:
        # Deliberately not chaining the URL/exc text — it carries the token.
        raise RetryableNotifyError("transport error") from exc
    # Telegram rate-limits with 429 + retry_after. _classify would call that
    # permanent and drop a merely-throttled poll, so catch it first.
    if response.status_code == 429:
        raise RetryableNotifyError("HTTP 429 (rate limited)")
    _classify(response)
    body: dict[str, Any] = response.json()
    return list(body.get("result", []))


# One client poll interval (TelegramConnectCard polls every 3s). Multiple
# staff connecting at once would otherwise each drive their own outbound call
# for byte-identical data: getUpdates returns the bot's whole pending queue,
# not a per-user view.
TELEGRAM_UPDATES_CACHE_TTL_SECONDS = 3.0

_updates_cache_lock = threading.Lock()
_updates_cache: tuple[float, list[dict[str, Any]]] | None = None


def get_telegram_updates_cached() -> list[dict[str, Any]]:
    """``get_telegram_updates`` behind a short TTL, collapsing concurrent
    pollers into one outbound call.

    The lock is required, not defensive: ``confirm_telegram`` is a sync ``def``
    so FastAPI runs it in a threadpool, and several threads per worker race
    this slot. It is deliberately held across the fetch -- that is what makes
    concurrent callers share one request rather than stampede. The cost is
    that a slow Telegram response blocks other threads in this worker for up
    to ``_TIMEOUT``; acceptable because the caller is a retrying poll.

    Failures are deliberately NOT cached: freezing a transient blip for the
    whole TTL would stall a legitimate connect. An empty result IS cached --
    "nothing yet" is the dominant response during a poll and is exactly the
    case worth collapsing.

    The cached payload holds chat ids and usernames. It stays in memory and
    must never be logged (the same discipline as the bot token itself).
    """
    global _updates_cache
    with _updates_cache_lock:
        now = time.monotonic()
        cached = _updates_cache
        if cached is not None and now - cached[0] < TELEGRAM_UPDATES_CACHE_TTL_SECONDS:
            return cached[1]
        updates = get_telegram_updates()
        _updates_cache = (now, updates)
        return updates


def reset_telegram_updates_cache() -> None:
    """Drop the cached window. Test seam -- production never needs this, since
    entries expire on their own."""
    global _updates_cache
    with _updates_cache_lock:
        _updates_cache = None


def parse_start_code(update: dict[str, Any]) -> tuple[str, str | None, str] | None:
    """If ``update`` is a Telegram ``/start <code>`` message, return
    ``(chat_id, username, code)``; otherwise None (any other message shape —
    no text, a different command, no chat — is simply not ours to handle)."""
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    text = message.get("text")
    if not isinstance(text, str) or not text.startswith("/start "):
        return None
    code = text.removeprefix("/start ").strip()
    if not code:
        return None
    chat = message.get("chat")
    if not isinstance(chat, dict) or "id" not in chat:
        return None
    return (str(chat["id"]), chat.get("username"), code)


# Map a channel to (send fn, address attribute on User).
_CHANNELS: dict[NotificationChannel, tuple[Any, str]] = {
    NotificationChannel.LINE: (send_line, "line_user_id"),
    NotificationChannel.VIBER: (send_viber, "viber_user_id"),
    NotificationChannel.TELEGRAM: (send_telegram, "telegram_chat_id"),
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


def _clean(value: Any) -> str:
    """A payload value as display text; None and blank strings become ""."""
    return "" if value is None else str(value).strip()


def _field(*candidates: Any) -> str:
    """The first candidate carrying display text, else "unknown". This is what
    guarantees a message never renders the string "None"."""
    for candidate in candidates:
        text = _clean(candidate)
        if text:
            return text
    return "unknown"


def _describe(name: Any, code: Any, fallback: Any) -> str:
    """ "name (code)", degrading to whichever one is present, then to an id.

    A row named in a payload can be deleted between the send and the render,
    so every label needs a floor.
    """
    label, extra = _clean(name), _clean(code)
    if label and extra:
        return f"{label} ({extra})"
    return _field(label, extra, fallback)


def _render_text(*, event_type: NotificationEvent, payload: dict[str, Any]) -> str:
    """Render one plain-text message. Sent without parse_mode, so emoji and
    newlines render but markup does not.

    Ids are payload-only: they stay in the append-only log for audit, but a
    UUID means nothing to someone reading this on their phone.
    """
    if event_type == NotificationEvent.PULL_SHORT:
        project = _describe(
            payload.get("project_name"),
            payload.get("project_code"),
            payload.get("project_id"),
        )
        return (
            "⚠️ Project pull came up short\n"
            f"Project: {project}\n"
            f"Lines short: {_field(payload.get('short_line_count'))}"
        )
    if event_type == NotificationEvent.PULL_FULFILLED:
        project = _describe(
            payload.get("project_name"),
            payload.get("project_code"),
            payload.get("project_id"),
        )
        return f"✅ Project pull fulfilled\nProject: {project}"
    if event_type == NotificationEvent.LOW_STOCK:
        item = _describe(
            payload.get("model_name"),
            payload.get("sku"),
            payload.get("product_id"),
        )
        return (
            "📉 Low stock\n"
            f"Item: {item}\n"
            f"On hand: {_field(payload.get('on_hand'))} "
            f"(minimum {_field(payload.get('min_stock_level'))})"
        )
    if event_type == NotificationEvent.OVERRIDE_PENDING:
        # deviation_pct is a percentage, not a raw price — safe to surface.
        item = _describe(
            payload.get("model_name"),
            payload.get("sku"),
            payload.get("override_id"),
        )
        return (
            "🔔 Pricing override needs approval\n"
            f"Item: {item}\n"
            f"Deviation: {_field(payload.get('deviation_pct'))}%"
        )
    if event_type == NotificationEvent.SYNC_REVIEW_PENDING:
        # Counts only — SyncReviewItem.payload is the raw held mutation and
        # carries prices. Ids and payload fields stay in the append-only log.
        total = int(payload.get("total") or 0)
        stale = int(payload.get("stale") or 0)
        conflict = int(payload.get("conflict") or 0)
        head = (
            "⚠️ 1 offline action needs review"
            if total == 1
            else f"⚠️ {total} offline actions need review"
        )
        parts: list[str] = []
        if conflict:
            parts.append(f"{conflict} conflict" + ("" if conflict == 1 else "s"))
        if stale:
            # "stale" is an adjective here — never pluralized.
            parts.append(f"{stale} stale")
        return f"{head}\n{', '.join(parts)}" if parts else head
    # Never push a raw payload (may carry financial fields). Each new event must
    # add an explicit, safe template here.
    raise NotImplementedError(f"No render template for {event_type!r}")


def notify_pull_short(*, session: Session, pull: ProjectPull) -> list[NotificationLog]:
    """Notify every BKK_ADMIN of a SHORT project pull (FR-018, Flow D)."""
    recipients = list(
        session.exec(select(User).where(User.role == UserRole.BKK_ADMIN)).all()
    )
    lines = session.exec(
        select(ProjectPullLine).where(ProjectPullLine.project_pull_id == pull.id)
    ).all()
    short_line_count = sum(1 for ln in lines if ln.line_state == LineState.SHORT)
    project = session.get(Project, pull.project_id)
    payload: dict[str, Any] = {
        "pull_id": str(pull.id),
        "project_id": str(pull.project_id),
        "project_name": project.name if project else None,
        "project_code": project.code if project else None,
        "customer_id": str(pull.customer_id),
        "short_line_count": short_line_count,
    }
    return notify(
        session=session,
        event_type=NotificationEvent.PULL_SHORT,
        recipients=recipients,
        payload=payload,
    )


def notify_pull_fulfilled(
    *, session: Session, pull: ProjectPull
) -> list[NotificationLog]:
    """Notify every BKK_ADMIN that a project pull was fully fulfilled (FR-018)."""
    recipients = list(
        session.exec(select(User).where(User.role == UserRole.BKK_ADMIN)).all()
    )
    project = session.get(Project, pull.project_id)
    payload: dict[str, Any] = {
        "pull_id": str(pull.id),
        "project_id": str(pull.project_id),
        "project_name": project.name if project else None,
        "project_code": project.code if project else None,
        "customer_id": str(pull.customer_id),
    }
    return notify(
        session=session,
        event_type=NotificationEvent.PULL_FULFILLED,
        recipients=recipients,
        payload=payload,
    )


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
        on_hand = crud._on_hand(session, product)
        if on_hand >= threshold:
            continue  # replenished since the crossing — no longer low
        payload: dict[str, Any] = {
            "product_id": str(product.id),
            "sku": product.sku,
            "model_name": product.model_name,
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


def notify_override_pending(
    *, session: Session, override: PricingOverrideRequest
) -> list[NotificationLog]:
    """Notify every BKK_ADMIN that a pricing override needs a decision (FR-010)."""
    recipients = list(
        session.exec(select(User).where(User.role == UserRole.BKK_ADMIN)).all()
    )
    product = session.get(Product, override.product_id)
    payload: dict[str, Any] = {
        "override_id": str(override.id),
        "sku": product.sku if product else None,
        "model_name": product.model_name if product else None,
        "deviation_pct": str(override.deviation_pct),
    }
    return notify(
        session=session,
        event_type=NotificationEvent.OVERRIDE_PENDING,
        recipients=recipients,
        payload=payload,
    )


def notify_override_pending_bg(*, override_id: uuid.UUID) -> None:
    """BackgroundTasks entrypoint for override-pending alerts. Opens its OWN
    session and never raises out of the background task (best-effort)."""
    try:
        with Session(engine) as session:
            override = session.get(PricingOverrideRequest, override_id)
            if override is None:
                return
            notify_override_pending(session=session, override=override)
    except Exception:  # noqa: BLE001 — belt: best-effort, swallow + log
        logger.exception(
            "notify_override_pending_bg failed for override_id=%s", override_id
        )


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


def notify_pull_fulfilled_bg(*, pull_id: uuid.UUID) -> None:
    """BackgroundTasks entrypoint: notify off the request hot path.

    Opens its OWN session and can never raise out of the background task — a
    notify failure must not affect the already-committed fulfill.
    """
    try:
        with Session(engine) as session:
            pull = session.get(ProjectPull, pull_id)
            if pull is None:
                return
            notify_pull_fulfilled(session=session, pull=pull)
    except Exception:  # noqa: BLE001 — belt: best-effort, swallow + log
        logger.exception("notify_pull_fulfilled_bg failed for pull_id=%s", pull_id)
