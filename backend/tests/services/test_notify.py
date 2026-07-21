"""Service tests for LINE + Viber + Telegram push notifications (FR-018, Task 2.7).

The single network seam ``app.services.notify._post`` is monkeypatched so no
real HTTP happens; tenacity's sleep is stubbed so retry tests run instantly.
"""

import logging
import uuid
from typing import Any

import httpx
import pytest
from sqlmodel import Session

from app.core.config import settings
from app.core.logging import configure_logging
from app.models import (
    NotificationChannel,
    NotificationEvent,
    NotificationLog,
    NotificationPreference,
    NotificationStatus,
    User,
    UserCreate,
    UserRole,
)
from app.services import notify
from tests.utils.utils import assert_no_financial_keys

LINE_TOKEN = "line-secret-token-xyz"
VIBER_TOKEN = "viber-secret-token-xyz"
TELEGRAM_TOKEN = "telegram-secret-token-xyz"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tenacity.nap.time.sleep", lambda *_: None)


@pytest.fixture(autouse=True)
def _tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LINE_CHANNEL_ACCESS_TOKEN", LINE_TOKEN)
    monkeypatch.setattr(settings, "VIBER_AUTH_TOKEN", VIBER_TOKEN)
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", TELEGRAM_TOKEN)


def _resp(status_code: int, json_body: dict[str, Any] | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=json_body if json_body is not None else {},
        request=httpx.Request("POST", "https://example.test"),
    )


def _recording_post(sent: list[Any]) -> Any:
    """A ``_post`` fake that records each call into ``sent`` and returns 200."""

    def fake_post(*_args: Any, **_kwargs: Any) -> httpx.Response:
        sent.append(1)
        return _resp(200)

    return fake_post


class _Auto:
    """Sentinel type distinguishing "caller didn't specify" (generate a
    fresh, unique value) from an explicit telegram_chat_id=None (no address
    at all, used by the not-enrolled test at line ~558). A fixed literal
    default would collide with User.telegram_chat_id's UNIQUE constraint
    (m031) the moment two tests in the same run both left it unset -- the
    shared `db` fixture is session-scoped and never rolls back a successful
    commit between tests."""


_AUTO_CHAT_ID = _Auto()


def _make_user(
    db: Session,
    *,
    role: UserRole = UserRole.BKK_ADMIN,
    line_user_id: str | None = "L-recipient",
    viber_user_id: str | None = "V-recipient",
    telegram_chat_id: str | None | _Auto = _AUTO_CHAT_ID,
) -> User:
    from app import crud
    from tests.utils.utils import random_email, random_lower_string

    user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=random_email(), password=random_lower_string(), role=role
        ),
    )
    if isinstance(telegram_chat_id, _Auto):
        telegram_chat_id = f"T-{uuid.uuid4().hex[:10]}"
    user.line_user_id = line_user_id
    user.viber_user_id = viber_user_id
    user.telegram_chat_id = telegram_chat_id
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _opt_in(
    db: Session,
    user: User,
    channel: NotificationChannel,
    event: NotificationEvent,
    *,
    enabled: bool = True,
) -> None:
    db.add(
        NotificationPreference(
            user_id=user.id, channel=channel, event_type=event, enabled=enabled
        )
    )
    db.commit()


# --- low-level send fns -------------------------------------------------------


def test_send_line_success_single_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_post(
        url: str, *, headers: dict[str, str], json: dict[str, Any]
    ) -> httpx.Response:
        calls.append({"url": url, "headers": headers, "json": json})
        return _resp(200)

    monkeypatch.setattr(notify, "_post", fake_post)
    notify.send_line(to="L-abc", text="hi")

    assert len(calls) == 1
    assert calls[0]["headers"]["Authorization"] == f"Bearer {LINE_TOKEN}"
    assert calls[0]["json"] == {
        "to": "L-abc",
        "messages": [{"type": "text", "text": "hi"}],
    }


def test_send_line_5xx_raises_retryable_single_raw_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The raw send is a single attempt now; retry lives in notify().
    attempts = {"n": 0}

    def fake_post(*_args: Any, **_kwargs: Any) -> httpx.Response:
        attempts["n"] += 1
        return _resp(503)

    monkeypatch.setattr(notify, "_post", fake_post)
    with pytest.raises(notify.RetryableNotifyError):
        notify.send_line(to="L-abc", text="hi")
    assert attempts["n"] == 1


def test_send_line_4xx_no_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = {"n": 0}

    def fake_post(*_args: Any, **_kwargs: Any) -> httpx.Response:
        attempts["n"] += 1
        return _resp(400)

    monkeypatch.setattr(notify, "_post", fake_post)
    with pytest.raises(notify.PermanentNotifyError):
        notify.send_line(to="L-abc", text="hi")
    assert attempts["n"] == 1


def test_send_telegram_success_single_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_post(
        url: str, *, headers: dict[str, str], json: dict[str, Any]
    ) -> httpx.Response:
        calls.append({"url": url, "headers": headers, "json": json})
        return _resp(200, {"ok": True})

    monkeypatch.setattr(notify, "_post", fake_post)
    notify.send_telegram(to="123456789", text="hi")

    assert len(calls) == 1
    # Telegram carries the bot token in the URL path, not a header.
    assert calls[0]["url"] == (
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    )
    assert calls[0]["json"] == {"chat_id": "123456789", "text": "hi"}


def test_send_telegram_5xx_raises_retryable_single_raw_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = {"n": 0}

    def fake_post(*_args: Any, **_kwargs: Any) -> httpx.Response:
        attempts["n"] += 1
        return _resp(503)

    monkeypatch.setattr(notify, "_post", fake_post)
    with pytest.raises(notify.RetryableNotifyError):
        notify.send_telegram(to="123456789", text="hi")
    assert attempts["n"] == 1


def test_send_telegram_429_is_retryable_not_permanent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Telegram signals rate limiting with HTTP 429 + retry_after. The generic
    _classify treats every 4xx as permanent, which would silently drop a merely
    throttled message — 429 must be retryable."""
    attempts = {"n": 0}

    def fake_post(*_args: Any, **_kwargs: Any) -> httpx.Response:
        attempts["n"] += 1
        return _resp(429, {"ok": False, "parameters": {"retry_after": 1}})

    monkeypatch.setattr(notify, "_post", fake_post)
    with pytest.raises(notify.RetryableNotifyError):
        notify.send_telegram(to="123456789", text="hi")
    assert attempts["n"] == 1


def test_send_telegram_4xx_no_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    # e.g. 403 "bot was blocked by the user" — never worth retrying.
    attempts = {"n": 0}

    def fake_post(*_args: Any, **_kwargs: Any) -> httpx.Response:
        attempts["n"] += 1
        return _resp(403, {"ok": False, "description": "bot was blocked"})

    monkeypatch.setattr(notify, "_post", fake_post)
    with pytest.raises(notify.PermanentNotifyError):
        notify.send_telegram(to="123456789", text="hi")
    assert attempts["n"] == 1


def test_send_telegram_transport_error_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_args: Any, **_kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(notify, "_post", boom)
    with pytest.raises(notify.RetryableNotifyError):
        notify.send_telegram(to="123456789", text="hi")


def test_configure_logging_suppresses_telegram_token_in_httpx_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Regression for C-2: httpx's own logger otherwise emits the full
    request URL — bot token and all — at INFO on every real send. This drives
    a real httpx.Client.send (via a MockTransport, no real network) so
    httpx's actual "HTTP Request: ..." log line fires, and asserts
    configure_logging() keeps the token out of every captured record."""
    configure_logging()
    caplog.set_level(logging.DEBUG)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True}, request=request)

    transport = httpx.MockTransport(handler)

    def fake_httpx_post(url: str, **kwargs: Any) -> httpx.Response:
        trust_env = kwargs.pop("trust_env", True)
        with httpx.Client(transport=transport, trust_env=trust_env) as client:
            return client.post(url, **kwargs)

    monkeypatch.setattr(httpx, "post", fake_httpx_post)
    notify.send_telegram(to="123456789", text="hi")

    messages = [r.getMessage() for r in caplog.records]
    assert not any(TELEGRAM_TOKEN in m for m in messages)


def test_get_telegram_updates_returns_result_and_never_sends_an_offset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_post(
        url: str, *, headers: dict[str, str], json: dict[str, Any]
    ) -> httpx.Response:
        calls.append({"url": url, "headers": headers, "json": json})
        return _resp(200, {"ok": True, "result": [{"update_id": 1}]})

    monkeypatch.setattr(notify, "_post", fake_post)
    result = notify.get_telegram_updates()

    assert result == [{"update_id": 1}]
    assert calls[0]["url"] == f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    # Never acknowledging updates (no poller, no offset state) means the
    # request must never carry an offset -- Telegram would stop re-sending
    # already-seen updates the moment one is.
    assert "offset" not in calls[0]["json"]


def test_get_telegram_updates_5xx_raises_retryable_single_raw_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = {"n": 0}

    def fake_post(*_args: Any, **_kwargs: Any) -> httpx.Response:
        attempts["n"] += 1
        return _resp(503)

    monkeypatch.setattr(notify, "_post", fake_post)
    with pytest.raises(notify.RetryableNotifyError):
        notify.get_telegram_updates()
    assert attempts["n"] == 1


def test_get_telegram_updates_429_is_retryable_not_permanent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(*_args: Any, **_kwargs: Any) -> httpx.Response:
        return _resp(429, {"ok": False, "parameters": {"retry_after": 1}})

    monkeypatch.setattr(notify, "_post", fake_post)
    with pytest.raises(notify.RetryableNotifyError):
        notify.get_telegram_updates()


def test_get_telegram_updates_4xx_no_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(*_args: Any, **_kwargs: Any) -> httpx.Response:
        return _resp(401, {"ok": False, "description": "Unauthorized"})

    monkeypatch.setattr(notify, "_post", fake_post)
    with pytest.raises(notify.PermanentNotifyError):
        notify.get_telegram_updates()


def test_get_telegram_updates_transport_error_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_args: Any, **_kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(notify, "_post", boom)
    with pytest.raises(notify.RetryableNotifyError):
        notify.get_telegram_updates()


def test_get_telegram_updates_unset_token_raises_permanent_no_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", None)
    calls: list[Any] = []
    monkeypatch.setattr(notify, "_post", lambda *a, **k: calls.append(1))
    with pytest.raises(notify.PermanentNotifyError):
        notify.get_telegram_updates()
    assert calls == []


def test_get_telegram_updates_never_logs_the_token_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notify, "_post", lambda *a, **k: _resp(500))
    try:
        notify.get_telegram_updates()
    except notify.RetryableNotifyError as exc:
        assert TELEGRAM_TOKEN not in str(exc)
    else:
        pytest.fail("expected RetryableNotifyError")


def test_parse_start_code_extracts_chat_id_username_and_code() -> None:
    update = {
        "update_id": 123456,
        "message": {
            "chat": {"id": 847392015, "username": "winthiha", "type": "private"},
            "text": "/start A7X2K9examplecode",
        },
    }
    assert notify.parse_start_code(update) == (
        "847392015",
        "winthiha",
        "A7X2K9examplecode",
    )


def test_parse_start_code_handles_missing_username() -> None:
    update = {"message": {"chat": {"id": 1}, "text": "/start CODE123"}}
    assert notify.parse_start_code(update) == ("1", None, "CODE123")


@pytest.mark.parametrize(
    "update",
    [
        {"update_id": 1},  # no message at all
        {"message": {"chat": {"id": 1}, "text": "just chatting"}},  # not /start
        {"message": {"chat": {"id": 1}, "text": "/start"}},  # no code after it
        {"message": {"text": "/start CODE"}},  # no chat
        {"message": {"chat": {}, "text": "/start CODE"}},  # chat has no id
    ],
)
def test_parse_start_code_ignores_unrelated_messages(update: dict[str, Any]) -> None:
    assert notify.parse_start_code(update) is None


def test_send_viber_status_zero_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_post(
        url: str, *, headers: dict[str, str], json: dict[str, Any]
    ) -> httpx.Response:
        calls.append({"url": url, "headers": headers, "json": json})
        return _resp(200, {"status": 0})

    monkeypatch.setattr(notify, "_post", fake_post)
    notify.send_viber(to="V-abc", text="hello")
    assert len(calls) == 1
    assert calls[0]["headers"]["X-Viber-Auth-Token"] == VIBER_TOKEN
    assert calls[0]["json"] == {"receiver": "V-abc", "type": "text", "text": "hello"}


def test_send_viber_nonzero_status_permanent_no_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = {"n": 0}

    def fake_post(*_args: Any, **_kwargs: Any) -> httpx.Response:
        attempts["n"] += 1
        return _resp(200, {"status": 3, "status_message": "bad"})

    monkeypatch.setattr(notify, "_post", fake_post)
    with pytest.raises(notify.PermanentNotifyError):
        notify.send_viber(to="V-abc", text="hello")
    assert attempts["n"] == 1


# --- orchestrator: notify() ---------------------------------------------------


def test_notify_line_success_one_sent_log(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(notify, "_post", lambda *a, **k: _resp(200))
    user = _make_user(db)
    _opt_in(db, user, NotificationChannel.LINE, NotificationEvent.PULL_SHORT)

    logs = notify.notify(
        session=db,
        event_type=NotificationEvent.PULL_SHORT,
        recipients=[user],
        payload={"k": "v"},
    )
    line_logs = [log for log in logs if log.channel == NotificationChannel.LINE]
    assert len(line_logs) == 1
    log = line_logs[0]
    assert log.status == NotificationStatus.SENT
    assert log.attempts == 1
    assert log.target_user_id == user.id
    # persisted
    fetched = db.get(NotificationLog, log.id)
    assert fetched is not None and fetched.status == NotificationStatus.SENT


def test_notify_line_5xx_failed_log_attempts_four_no_token(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[Any] = []

    def fake_post(*_args: Any, **_kwargs: Any) -> httpx.Response:
        sent.append(1)
        return _resp(503)

    monkeypatch.setattr(notify, "_post", fake_post)
    user = _make_user(db)
    _opt_in(db, user, NotificationChannel.LINE, NotificationEvent.PULL_SHORT)

    logs = notify.notify(
        session=db,
        event_type=NotificationEvent.PULL_SHORT,
        recipients=[user],
        payload={},
    )
    line_logs = [log for log in logs if log.channel == NotificationChannel.LINE]
    assert len(line_logs) == 1
    log = line_logs[0]
    assert log.status == NotificationStatus.FAILED
    # 4 attempts / 3 retries (waits 1s, 5s, 25s).
    assert log.attempts == 4
    assert len(sent) == 4
    assert log.last_error
    assert LINE_TOKEN not in (log.last_error or "")


def test_notify_opt_out_no_send_no_log(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[Any] = []
    monkeypatch.setattr(notify, "_post", _recording_post(sent))
    user = _make_user(db)
    # explicit disabled LINE pref + no VIBER pref at all
    _opt_in(
        db, user, NotificationChannel.LINE, NotificationEvent.PULL_SHORT, enabled=False
    )

    logs = notify.notify(
        session=db,
        event_type=NotificationEvent.PULL_SHORT,
        recipients=[user],
        payload={},
    )
    assert logs == []
    assert sent == []


def test_notify_opted_in_but_no_address_failed_not_enrolled(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[Any] = []
    monkeypatch.setattr(notify, "_post", _recording_post(sent))
    user = _make_user(db, line_user_id=None)
    _opt_in(db, user, NotificationChannel.LINE, NotificationEvent.PULL_SHORT)

    logs = notify.notify(
        session=db,
        event_type=NotificationEvent.PULL_SHORT,
        recipients=[user],
        payload={},
    )
    line_logs = [log for log in logs if log.channel == NotificationChannel.LINE]
    assert len(line_logs) == 1
    log = line_logs[0]
    assert log.status == NotificationStatus.FAILED
    assert log.attempts == 0
    assert "not enrolled" in (log.last_error or "")
    assert sent == []  # no send attempted


def test_notify_one_log_per_attempted_recipient_channel(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(notify, "_post", lambda *a, **k: _resp(200, {"status": 0}))
    user = _make_user(db)
    _opt_in(db, user, NotificationChannel.LINE, NotificationEvent.PULL_SHORT)
    _opt_in(db, user, NotificationChannel.VIBER, NotificationEvent.PULL_SHORT)

    logs = notify.notify(
        session=db,
        event_type=NotificationEvent.PULL_SHORT,
        recipients=[user],
        payload={},
    )
    channels = sorted(log.channel.value for log in logs)
    assert channels == ["LINE", "VIBER"]
    assert all(log.status == NotificationStatus.SENT for log in logs)


def test_notify_never_raises_on_transport_error(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: Any, **_kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(notify, "_post", boom)
    user = _make_user(db)
    _opt_in(db, user, NotificationChannel.LINE, NotificationEvent.PULL_SHORT)

    logs = notify.notify(
        session=db,
        event_type=NotificationEvent.PULL_SHORT,
        recipients=[user],
        payload={},
    )
    line_logs = [log for log in logs if log.channel == NotificationChannel.LINE]
    assert len(line_logs) == 1
    assert line_logs[0].status == NotificationStatus.FAILED


def test_notify_concurrent_attempts_not_clobbered(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two concurrent notify() calls — one persistently-5xx, one success — must
    each log their own attempt count (regression for the shared-statistics
    race fixed by the per-call Retrying controller)."""
    import threading

    fail_user = _make_user(db, line_user_id="L-fail")
    ok_user = _make_user(db, line_user_id="L-ok")
    _opt_in(db, fail_user, NotificationChannel.LINE, NotificationEvent.PULL_SHORT)
    _opt_in(db, ok_user, NotificationChannel.LINE, NotificationEvent.PULL_SHORT)

    start = threading.Barrier(2)
    seen_threads: set[int] = set()
    lock = threading.Lock()

    def fake_post(*_args: Any, **kwargs: Any) -> httpx.Response:
        # Sync both threads on each thread's first send so the calls interleave;
        # a shared attempt counter would then clobber across the two notify()s.
        tid = threading.get_ident()
        with lock:
            first = tid not in seen_threads
            seen_threads.add(tid)
        if first:
            start.wait(timeout=5)
        if kwargs["json"]["to"] == fail_user.line_user_id:
            return _resp(503)
        return _resp(200)

    monkeypatch.setattr(notify, "_post", fake_post)

    results: dict[str, list[NotificationLog]] = {}

    def run(key: str, user: User) -> None:
        from app.core.db import engine as _engine

        with Session(_engine) as s:
            results[key] = notify.notify(
                session=s,
                event_type=NotificationEvent.PULL_SHORT,
                recipients=[user],
                payload={},
            )

    t_fail = threading.Thread(target=run, args=("fail", fail_user))
    t_ok = threading.Thread(target=run, args=("ok", ok_user))
    t_fail.start()
    t_ok.start()
    t_fail.join(timeout=10)
    t_ok.join(timeout=10)

    fail_log = next(
        log for log in results["fail"] if log.channel == NotificationChannel.LINE
    )
    ok_log = next(
        log for log in results["ok"] if log.channel == NotificationChannel.LINE
    )
    assert fail_log.status == NotificationStatus.FAILED
    assert fail_log.attempts == 4  # not clobbered by the concurrent success
    assert ok_log.status == NotificationStatus.SENT
    assert ok_log.attempts == 1


def test_send_line_unset_token_raises_permanent_no_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[Any] = []
    monkeypatch.setattr(notify, "_post", _recording_post(sent))
    monkeypatch.setattr(settings, "LINE_CHANNEL_ACCESS_TOKEN", "")
    with pytest.raises(notify.PermanentNotifyError):
        notify.send_line(to="L-abc", text="hi")
    assert sent == []  # fail-fast: no outbound call


def test_send_viber_unset_token_raises_permanent_no_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[Any] = []
    monkeypatch.setattr(notify, "_post", _recording_post(sent))
    monkeypatch.setattr(settings, "VIBER_AUTH_TOKEN", None)
    with pytest.raises(notify.PermanentNotifyError):
        notify.send_viber(to="V-abc", text="hi")
    assert sent == []


def test_send_telegram_unset_token_raises_permanent_no_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[Any] = []
    monkeypatch.setattr(notify, "_post", _recording_post(sent))
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "")
    with pytest.raises(notify.PermanentNotifyError):
        notify.send_telegram(to="123456789", text="hi")
    # fail-fast: an empty token would otherwise build a bot//sendMessage URL
    assert sent == []


# --- orchestrator: Telegram ---------------------------------------------------


def test_notify_telegram_success_one_sent_log(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(notify, "_post", lambda *a, **k: _resp(200, {"ok": True}))
    user = _make_user(db)
    _opt_in(db, user, NotificationChannel.TELEGRAM, NotificationEvent.PULL_SHORT)

    logs = notify.notify(
        session=db,
        event_type=NotificationEvent.PULL_SHORT,
        recipients=[user],
        payload={"k": "v"},
    )
    tg_logs = [log for log in logs if log.channel == NotificationChannel.TELEGRAM]
    assert len(tg_logs) == 1
    assert tg_logs[0].status == NotificationStatus.SENT
    assert tg_logs[0].attempts == 1
    assert tg_logs[0].target_user_id == user.id


def test_notify_telegram_5xx_retries_and_never_logs_the_token(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bot token rides in the URL, so a failure path must not echo it into
    last_error (which is stored and shown to admins)."""
    sent: list[Any] = []

    def fake_post(*_args: Any, **_kwargs: Any) -> httpx.Response:
        sent.append(1)
        return _resp(503)

    monkeypatch.setattr(notify, "_post", fake_post)
    user = _make_user(db)
    _opt_in(db, user, NotificationChannel.TELEGRAM, NotificationEvent.PULL_SHORT)

    logs = notify.notify(
        session=db,
        event_type=NotificationEvent.PULL_SHORT,
        recipients=[user],
        payload={},
    )
    tg_logs = [log for log in logs if log.channel == NotificationChannel.TELEGRAM]
    assert len(tg_logs) == 1
    assert tg_logs[0].status == NotificationStatus.FAILED
    assert tg_logs[0].attempts == 4  # 4 attempts / 3 retries
    assert len(sent) == 4
    assert TELEGRAM_TOKEN not in (tg_logs[0].last_error or "")


def test_notify_telegram_opted_in_but_no_chat_id_failed_not_enrolled(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[Any] = []
    monkeypatch.setattr(notify, "_post", _recording_post(sent))
    user = _make_user(db, telegram_chat_id=None)
    _opt_in(db, user, NotificationChannel.TELEGRAM, NotificationEvent.PULL_SHORT)

    logs = notify.notify(
        session=db,
        event_type=NotificationEvent.PULL_SHORT,
        recipients=[user],
        payload={},
    )
    tg_logs = [log for log in logs if log.channel == NotificationChannel.TELEGRAM]
    assert len(tg_logs) == 1
    assert tg_logs[0].status == NotificationStatus.FAILED
    assert tg_logs[0].attempts == 0
    assert "not enrolled" in (tg_logs[0].last_error or "")
    assert sent == []


# --- notify_pull_short helper -------------------------------------------------


def test_notify_pull_short_targets_bkk_admins_with_pref(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import crud
    from app.models import (
        CustomerCreate,
        LineState,
        ProductCreate,
        ProjectCreate,
        ProjectPull,
        ProjectPullLine,
        ProjectPullState,
        SaleLineKind,
        TrackingMode,
    )

    monkeypatch.setattr(notify, "_post", lambda *a, **k: _resp(200))
    admin = _make_user(db, role=UserRole.BKK_ADMIN)
    _opt_in(db, admin, NotificationChannel.LINE, NotificationEvent.PULL_SHORT)
    # a staff user opted in must NOT receive (role gate)
    staff = _make_user(db, role=UserRole.YGN_STAFF)
    _opt_in(db, staff, NotificationChannel.LINE, NotificationEvent.PULL_SHORT)

    customer = crud.create_customer(session=db, customer_in=CustomerCreate(name="C"))
    project = crud.create_project(
        session=db,
        project_in=ProjectCreate(
            code=f"P-{uuid.uuid4().hex[:8]}", name="P", customer_id=customer.id
        ),
    )
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"NS-{uuid.uuid4().hex[:8]}",
            model_name="Part",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb="10.00",
            repair_price_thb="2.00",
        ),
    )
    pull = ProjectPull(
        project_id=project.id,
        customer_id=customer.id,
        state=ProjectPullState.SHORT,
        created_by_user_id=admin.id,
    )
    db.add(pull)
    db.commit()
    db.refresh(pull)
    line = ProjectPullLine(
        project_pull_id=pull.id,
        line_kind=SaleLineKind.PART,
        product_id=product.id,
        requested_qty=5,
        fulfilled_qty=3,
        line_state=LineState.SHORT,
    )
    db.add(line)
    db.commit()

    logs = notify.notify_pull_short(session=db, pull=pull)
    targets = {log.target_user_id for log in logs}
    assert admin.id in targets
    assert staff.id not in targets
    assert all(log.event_type == NotificationEvent.PULL_SHORT for log in logs)
    sample = next(log for log in logs if log.target_user_id == admin.id)
    assert sample.payload["short_line_count"] == 1
    assert sample.payload["pull_id"] == str(pull.id)
    assert sample.payload["project_name"] == project.name
    assert sample.payload["project_code"] == project.code


# --- notify_pull_fulfilled helper (FR-018) ------------------------------------


def test_notify_pull_fulfilled_targets_bkk_admins_with_pref(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import crud
    from app.models import (
        CustomerCreate,
        ProjectCreate,
        ProjectPull,
        ProjectPullState,
    )

    monkeypatch.setattr(notify, "_post", lambda *a, **k: _resp(200))
    admin = _make_user(db, role=UserRole.BKK_ADMIN)
    _opt_in(db, admin, NotificationChannel.LINE, NotificationEvent.PULL_FULFILLED)
    # a staff user opted in must NOT receive (role gate)
    staff = _make_user(db, role=UserRole.YGN_STAFF)
    _opt_in(db, staff, NotificationChannel.LINE, NotificationEvent.PULL_FULFILLED)

    customer = crud.create_customer(session=db, customer_in=CustomerCreate(name="C"))
    project = crud.create_project(
        session=db,
        project_in=ProjectCreate(
            code=f"P-{uuid.uuid4().hex[:8]}", name="P", customer_id=customer.id
        ),
    )
    pull = ProjectPull(
        project_id=project.id,
        customer_id=customer.id,
        state=ProjectPullState.FULFILLED,
        created_by_user_id=admin.id,
    )
    db.add(pull)
    db.commit()
    db.refresh(pull)

    logs = notify.notify_pull_fulfilled(session=db, pull=pull)
    targets = {log.target_user_id for log in logs}
    assert admin.id in targets
    assert staff.id not in targets
    assert all(log.event_type == NotificationEvent.PULL_FULFILLED for log in logs)
    sample = next(log for log in logs if log.target_user_id == admin.id)
    assert sample.payload["pull_id"] == str(pull.id)
    assert sample.payload["project_name"] == project.name
    assert sample.payload["project_code"] == project.code
    # FR-018 requires the FULFILLED push carry NO financial fields.
    assert_no_financial_keys(sample.payload)


# --- message copy (2026-07-22 friendlier messages) ----------------------------


def test_render_text_pull_short_is_labeled_lines() -> None:
    text = notify._render_text(
        event_type=NotificationEvent.PULL_SHORT,
        payload={
            "pull_id": "the-pull-id",
            "project_id": "the-project-id",
            "project_name": "Riverside Tower",
            "project_code": "PRJ-001",
            "short_line_count": 2,
        },
    )
    assert text == (
        "⚠️ Project pull came up short\n"
        "Project: Riverside Tower (PRJ-001)\n"
        "Lines short: 2"
    )
    # ids are payload-only now
    assert "the-pull-id" not in text


def test_render_text_pull_fulfilled_names_the_project() -> None:
    text = notify._render_text(
        event_type=NotificationEvent.PULL_FULFILLED,
        payload={
            "pull_id": "the-pull-id",
            "project_id": "the-project-id",
            "project_name": "Riverside Tower",
            "project_code": "PRJ-001",
        },
    )
    assert text == "✅ Project pull fulfilled\nProject: Riverside Tower (PRJ-001)"
    assert "the-pull-id" not in text


def test_render_text_low_stock_names_the_product() -> None:
    text = notify._render_text(
        event_type=NotificationEvent.LOW_STOCK,
        payload={
            "product_id": "the-product-id",
            "sku": "SKU-1234",
            "model_name": "12mm Copper Elbow",
            "on_hand": 3,
            "min_stock_level": 10,
        },
    )
    assert text == (
        "📉 Low stock\nItem: 12mm Copper Elbow (SKU-1234)\nOn hand: 3 (minimum 10)"
    )


def test_render_text_override_pending_names_the_product() -> None:
    text = notify._render_text(
        event_type=NotificationEvent.OVERRIDE_PENDING,
        payload={
            "override_id": "the-override-id",
            "sku": "SKU-1234",
            "model_name": "12mm Copper Elbow",
            "deviation_pct": "12.5",
        },
    )
    assert text == (
        "🔔 Pricing override needs approval\n"
        "Item: 12mm Copper Elbow (SKU-1234)\n"
        "Deviation: 12.5%"
    )
    assert "the-override-id" not in text


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        (
            NotificationEvent.PULL_SHORT,
            {"project_id": "the-project-id", "short_line_count": 2},
        ),
        (NotificationEvent.PULL_FULFILLED, {"project_id": "the-project-id"}),
        (
            NotificationEvent.LOW_STOCK,
            {"product_id": "the-product-id", "on_hand": 3, "min_stock_level": 10},
        ),
        (
            NotificationEvent.OVERRIDE_PENDING,
            {"override_id": "the-override-id", "deviation_pct": "12.5"},
        ),
    ],
)
def test_render_text_falls_back_to_id_when_row_is_gone(
    event_type: NotificationEvent, payload: dict[str, object]
) -> None:
    """A deleted Project/Product leaves the name keys absent. The label must
    degrade to the id and must never render the string "None"."""
    text = notify._render_text(event_type=event_type, payload=payload)
    assert "None" not in text
    assert "unknown" not in text
    fallback = (
        payload.get("project_id")
        or payload.get("product_id")
        or payload.get("override_id")
    )
    assert str(fallback) in text


def test_render_text_never_renders_none_for_missing_quantities() -> None:
    """Every key absent — the last line of defence against "None" reaching a
    user's phone."""
    for event_type in (
        NotificationEvent.PULL_SHORT,
        NotificationEvent.PULL_FULFILLED,
        NotificationEvent.LOW_STOCK,
        NotificationEvent.OVERRIDE_PENDING,
    ):
        text = notify._render_text(event_type=event_type, payload={})
        assert "None" not in text


def test_render_text_still_rejects_an_unknown_event() -> None:
    """Every new event must add an explicit, safe template — never a raw dump."""
    with pytest.raises(NotImplementedError):
        notify._render_text(
            event_type="not-an-event",  # type: ignore[arg-type]
            payload={"retail_price_thb": "999.00"},
        )
