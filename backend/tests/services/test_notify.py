"""Service tests for LINE + Viber push notifications (FR-018, Task 2.7).

The single network seam ``app.services.notify._post`` is monkeypatched so no
real HTTP happens; tenacity's sleep is stubbed so retry tests run instantly.
"""

import uuid
from typing import Any

import httpx
import pytest
from sqlmodel import Session

from app.core.config import settings
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

LINE_TOKEN = "line-secret-token-xyz"
VIBER_TOKEN = "viber-secret-token-xyz"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tenacity.nap.time.sleep", lambda *_: None)


@pytest.fixture(autouse=True)
def _tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LINE_CHANNEL_ACCESS_TOKEN", LINE_TOKEN)
    monkeypatch.setattr(settings, "VIBER_AUTH_TOKEN", VIBER_TOKEN)


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


def _make_user(
    db: Session,
    *,
    role: UserRole = UserRole.BKK_ADMIN,
    line_user_id: str | None = "L-recipient",
    viber_user_id: str | None = "V-recipient",
) -> User:
    from app import crud
    from tests.utils.utils import random_email, random_lower_string

    user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=random_email(), password=random_lower_string(), role=role
        ),
    )
    user.line_user_id = line_user_id
    user.viber_user_id = viber_user_id
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

    def fake_post(url: str, *, headers: dict[str, str], json: dict[str, Any]) -> httpx.Response:
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


def test_send_viber_status_zero_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, *, headers: dict[str, str], json: dict[str, Any]) -> httpx.Response:
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
    line_logs = [
        log for log in logs if log.channel == NotificationChannel.LINE
    ]
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
    _opt_in(db, user, NotificationChannel.LINE, NotificationEvent.PULL_SHORT, enabled=False)

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
    monkeypatch.setattr(
        notify, "_post", lambda *a, **k: _resp(200, {"status": 0})
    )
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

    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="C")
    )
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
