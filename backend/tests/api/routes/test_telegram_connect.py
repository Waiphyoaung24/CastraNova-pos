"""Route tests for the Telegram self-service connect flow (FR-018 follow-up).

connect mints a one-time code; confirm resolves it against a stubbed
getUpdates; test sends a one-off probe message. notify._post is monkeypatched
throughout, matching test_notify.py's convention -- no real HTTP happens.
"""

import re
import uuid
from datetime import timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.core.limiter import limiter
from app.models import NotificationLog, TelegramConnectCode, User, get_datetime_utc
from app.services import notify
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import random_email

PREFIX = settings.API_V1_STR


def _resp(status_code: int, json_body: dict[str, Any] | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=json_body if json_body is not None else {},
        request=httpx.Request("POST", "https://example.test"),
    )


@pytest.fixture
def user_and_headers(client: TestClient, db: Session) -> tuple[User, dict[str, str]]:
    email = random_email()
    headers = authentication_token_from_email(client=client, email=email, db=db)
    user = crud.get_user_by_email(session=db, email=email)
    assert user is not None
    return user, headers


# --- connect -------------------------------------------------------------------


def test_connect_mints_a_code_and_deep_link(
    client: TestClient, db: Session, user_and_headers: tuple[User, dict[str, str]]
) -> None:
    _user, headers = user_and_headers
    monkeypatch_username = "CastraNovaBot"
    settings.TELEGRAM_BOT_USERNAME = monkeypatch_username

    r = client.post(f"{PREFIX}/notifications/telegram/connect", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["code"]
    assert body["deep_link"] == f"https://t.me/{monkeypatch_username}?start={body['code']}"
    assert body["qr_code_data_uri"].startswith("data:image/png;base64,")

    row = db.exec(
        select(TelegramConnectCode).where(TelegramConnectCode.code == body["code"])
    ).first()
    assert row is not None
    assert row.consumed_at is None


def test_connect_code_is_unguessably_long(
    client: TestClient, user_and_headers: tuple[User, dict[str, str]]
) -> None:
    _user, headers = user_and_headers
    r = client.post(f"{PREFIX}/notifications/telegram/connect", headers=headers)
    assert r.status_code == 200, r.text
    # A short/sequential code would be guessable within the confirm TTL,
    # letting an attacker bind their own Telegram to someone else's account.
    assert len(r.json()["code"]) >= 20


def test_connect_code_only_uses_telegrams_allowed_start_parameter_charset(
    client: TestClient, user_and_headers: tuple[User, dict[str, str]]
) -> None:
    """Telegram's deep-link start parameter only allows [A-Za-z0-9_] -- any
    other character (e.g. secrets.token_urlsafe's '-') makes the client treat
    the whole parameter as invalid and drop it, so the user's Telegram just
    sends a bare "/start" with no code. parse_start_code would never find a
    match and confirm would hang forever."""
    r = client.post(f"{PREFIX}/notifications/telegram/connect", headers=user_and_headers[1])
    assert r.status_code == 200, r.text
    code = r.json()["code"]
    assert re.fullmatch(r"[A-Za-z0-9_]+", code), code


# --- confirm ---------------------------------------------------------------


def _stub_updates(monkeypatch: pytest.MonkeyPatch, *updates: dict[str, Any]) -> None:
    monkeypatch.setattr(notify, "get_telegram_updates", lambda: list(updates))


def _unique_chat_id() -> str:
    # A fresh value per call: the shared `db` fixture is session-scoped with
    # no rollback between tests, and User.telegram_chat_id is UNIQUE (m031),
    # so a literal reused across tests collides the moment a second test
    # tries to bind it.
    return str(uuid.uuid4().int)[:10]


def test_confirm_binds_chat_id_and_username_on_match(
    client: TestClient,
    db: Session,
    user_and_headers: tuple[User, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, headers = user_and_headers
    r_connect = client.post(f"{PREFIX}/notifications/telegram/connect", headers=headers)
    code = r_connect.json()["code"]
    chat_id = _unique_chat_id()

    _stub_updates(
        monkeypatch,
        {
            "update_id": 1,
            "message": {
                "chat": {"id": int(chat_id), "username": "winthiha"},
                "text": f"/start {code}",
            },
        },
    )

    r = client.post(
        f"{PREFIX}/notifications/telegram/confirm",
        headers=headers,
        json={"code": code},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"connected": True, "telegram_username": "winthiha"}

    db.expire_all()
    refreshed = crud.get_user_by_email(session=db, email=user.email)
    assert refreshed is not None
    assert refreshed.telegram_chat_id == chat_id
    assert refreshed.telegram_username == "winthiha"


def test_confirm_no_matching_update_yet_returns_not_connected(
    client: TestClient,
    user_and_headers: tuple[User, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _user, headers = user_and_headers
    r_connect = client.post(f"{PREFIX}/notifications/telegram/connect", headers=headers)
    code = r_connect.json()["code"]
    _stub_updates(monkeypatch)  # nobody has messaged the bot yet

    r = client.post(
        f"{PREFIX}/notifications/telegram/confirm",
        headers=headers,
        json={"code": code},
    )
    assert r.status_code == 200, r.text
    assert r.json()["connected"] is False


def test_confirm_wrong_code_returns_not_connected(
    client: TestClient,
    user_and_headers: tuple[User, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _user, headers = user_and_headers
    client.post(f"{PREFIX}/notifications/telegram/connect", headers=headers)
    _stub_updates(monkeypatch)

    r = client.post(
        f"{PREFIX}/notifications/telegram/confirm",
        headers=headers,
        json={"code": "not-a-real-code"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["connected"] is False


def test_confirm_expired_code_returns_not_connected_even_with_a_match(
    client: TestClient,
    db: Session,
    user_and_headers: tuple[User, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, headers = user_and_headers
    r_connect = client.post(f"{PREFIX}/notifications/telegram/connect", headers=headers)
    code = r_connect.json()["code"]

    row = db.exec(
        select(TelegramConnectCode).where(TelegramConnectCode.code == code)
    ).first()
    assert row is not None
    row.expires_at = get_datetime_utc() - timedelta(minutes=1)
    db.add(row)
    db.commit()

    _stub_updates(
        monkeypatch,
        {"message": {"chat": {"id": int(_unique_chat_id())}, "text": f"/start {code}"}},
    )
    r = client.post(
        f"{PREFIX}/notifications/telegram/confirm",
        headers=headers,
        json={"code": code},
    )
    assert r.status_code == 200, r.text
    assert r.json()["connected"] is False

    db.expire_all()
    refreshed = crud.get_user_by_email(session=db, email=user.email)
    assert refreshed is not None
    assert refreshed.telegram_chat_id is None


def test_confirm_is_single_use(
    client: TestClient,
    user_and_headers: tuple[User, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _user, headers = user_and_headers
    r_connect = client.post(f"{PREFIX}/notifications/telegram/connect", headers=headers)
    code = r_connect.json()["code"]
    _stub_updates(
        monkeypatch,
        {"message": {"chat": {"id": int(_unique_chat_id())}, "text": f"/start {code}"}},
    )

    r1 = client.post(
        f"{PREFIX}/notifications/telegram/confirm",
        headers=headers,
        json={"code": code},
    )
    assert r1.json()["connected"] is True

    r2 = client.post(
        f"{PREFIX}/notifications/telegram/confirm",
        headers=headers,
        json={"code": code},
    )
    assert r2.json()["connected"] is False


def test_confirm_cannot_be_completed_by_a_different_user(
    client: TestClient,
    db: Session,
    user_and_headers: tuple[User, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A code only binds to the account that minted it -- see the
    TelegramConnectCode docstring: this is an authentication boundary."""
    _owner, owner_headers = user_and_headers
    r_connect = client.post(
        f"{PREFIX}/notifications/telegram/connect", headers=owner_headers
    )
    code = r_connect.json()["code"]

    other_email = random_email()
    other_headers = authentication_token_from_email(
        client=client, email=other_email, db=db
    )
    _stub_updates(
        monkeypatch,
        {"message": {"chat": {"id": int(_unique_chat_id())}, "text": f"/start {code}"}},
    )
    r = client.post(
        f"{PREFIX}/notifications/telegram/confirm",
        headers=other_headers,
        json={"code": code},
    )
    assert r.status_code == 200, r.text
    assert r.json()["connected"] is False

    other_user = crud.get_user_by_email(session=db, email=other_email)
    assert other_user is not None
    assert other_user.telegram_chat_id is None


# --- test message ------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tenacity.nap.time.sleep", lambda *_: None)


def test_test_message_succeeds_when_connected(
    client: TestClient,
    db: Session,
    user_and_headers: tuple[User, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, headers = user_and_headers
    user.telegram_chat_id = f"T-{uuid.uuid4().hex[:10]}"
    db.add(user)
    db.commit()
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setattr(notify, "_post", lambda *a, **k: _resp(200, {"ok": True}))

    r = client.post(f"{PREFIX}/notifications/telegram/test", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "detail": None}

    # A user-initiated probe is not a real notify() event -- it must not
    # pollute the append-only weekly-review log. Scoped to this user (rather
    # than asserting the whole table is empty): the shared `db` fixture is
    # session-scoped, so other tests' real notify() fan-outs leave rows in
    # notificationlog for the whole run: this user is fresh, so any row
    # targeting them can only have come from this test's own action.
    assert db.exec(
        select(NotificationLog).where(NotificationLog.target_user_id == user.id)
    ).all() == []


def test_test_message_not_connected_is_a_client_error(
    client: TestClient, user_and_headers: tuple[User, dict[str, str]]
) -> None:
    _user, headers = user_and_headers
    r = client.post(f"{PREFIX}/notifications/telegram/test", headers=headers)
    assert r.status_code == 400, r.text


def test_test_message_surfaces_telegrams_description_never_the_token(
    client: TestClient,
    db: Session,
    user_and_headers: tuple[User, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, headers = user_and_headers
    user.telegram_chat_id = f"T-{uuid.uuid4().hex[:10]}"
    db.add(user)
    db.commit()
    token = "super-secret-bot-token"
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", token)
    monkeypatch.setattr(
        notify,
        "_post",
        lambda *a, **k: _resp(
            403, {"ok": False, "description": "Forbidden: bot was blocked by the user"}
        ),
    )

    r = client.post(f"{PREFIX}/notifications/telegram/test", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert body["detail"] == "Forbidden: bot was blocked by the user"
    assert token not in r.text


def test_test_message_rate_limited(
    client: TestClient,
    db: Session,
    user_and_headers: tuple[User, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, headers = user_and_headers
    user.telegram_chat_id = f"T-{uuid.uuid4().hex[:10]}"
    db.add(user)
    db.commit()
    monkeypatch.setattr(notify, "_post", lambda *a, **k: _resp(200, {"ok": True}))

    limiter.reset()
    limiter.enabled = True
    try:
        codes = [
            client.post(f"{PREFIX}/notifications/telegram/test", headers=headers).status_code
            for _ in range(10)
        ]
        assert all(c == 200 for c in codes)
        r11 = client.post(f"{PREFIX}/notifications/telegram/test", headers=headers)
        assert r11.status_code == 429
    finally:
        limiter.enabled = False
        limiter.reset()


# --- status --------------------------------------------------------------------


def test_status_not_connected(
    client: TestClient, user_and_headers: tuple[User, dict[str, str]]
) -> None:
    _user, headers = user_and_headers
    r = client.get(f"{PREFIX}/notifications/telegram/status", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "connected": False,
        "telegram_username": None,
        "delivery_failing": False,
        "last_error": None,
    }


def test_status_connected_shows_username(
    client: TestClient,
    db: Session,
    user_and_headers: tuple[User, dict[str, str]],
) -> None:
    user, headers = user_and_headers
    user.telegram_chat_id = f"T-{uuid.uuid4().hex[:10]}"
    user.telegram_username = "winthiha"
    db.add(user)
    db.commit()

    r = client.get(f"{PREFIX}/notifications/telegram/status", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["connected"] is True
    assert body["telegram_username"] == "winthiha"
    assert body["delivery_failing"] is False


def test_status_delivery_failing_when_latest_log_is_failed(
    client: TestClient,
    db: Session,
    user_and_headers: tuple[User, dict[str, str]],
) -> None:
    from app.models import NotificationChannel, NotificationEvent, NotificationStatus

    user, headers = user_and_headers
    user.telegram_chat_id = f"T-{uuid.uuid4().hex[:10]}"
    db.add(user)
    db.commit()
    db.add(
        NotificationLog(
            channel=NotificationChannel.TELEGRAM,
            event_type=NotificationEvent.LOW_STOCK,
            target_user_id=user.id,
            payload={},
            status=NotificationStatus.FAILED,
            attempts=4,
            last_error="bot was blocked by the user",
        )
    )
    db.commit()

    r = client.get(f"{PREFIX}/notifications/telegram/status", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["delivery_failing"] is True
    assert body["last_error"] == "bot was blocked by the user"


def test_status_not_failing_once_a_later_send_succeeds(
    client: TestClient,
    db: Session,
    user_and_headers: tuple[User, dict[str, str]],
) -> None:
    """A recovered binding (later SENT) must clear the warning -- only the
    MOST RECENT log for this user's Telegram channel matters, not "any
    failure ever"."""
    from datetime import timedelta

    from app.models import (
        NotificationChannel,
        NotificationEvent,
        NotificationStatus,
        get_datetime_utc,
    )

    user, headers = user_and_headers
    user.telegram_chat_id = f"T-{uuid.uuid4().hex[:10]}"
    db.add(user)
    db.commit()
    db.add(
        NotificationLog(
            channel=NotificationChannel.TELEGRAM,
            event_type=NotificationEvent.LOW_STOCK,
            target_user_id=user.id,
            payload={},
            status=NotificationStatus.FAILED,
            attempts=4,
            last_error="bot was blocked by the user",
            created_at=get_datetime_utc() - timedelta(minutes=5),
        )
    )
    db.add(
        NotificationLog(
            channel=NotificationChannel.TELEGRAM,
            event_type=NotificationEvent.LOW_STOCK,
            target_user_id=user.id,
            payload={},
            status=NotificationStatus.SENT,
            attempts=1,
            created_at=get_datetime_utc(),
        )
    )
    db.commit()

    r = client.get(f"{PREFIX}/notifications/telegram/status", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["delivery_failing"] is False
    assert body["last_error"] is None
