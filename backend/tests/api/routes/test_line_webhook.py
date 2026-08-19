"""Route tests for the LINE webhook.

This endpoint is public and unauthenticated -- its only gate is the HMAC
signature over the raw request body -- so the signature tests here are the
security regression suite, not a formality. notify.send_line_reply is
monkeypatched throughout; no real HTTP happens.
"""

import base64
import hashlib
import hmac
import json
import logging
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.models import User, UserCreate
from app.services import notify
from tests.utils.utils import random_email, random_lower_string

PREFIX = settings.API_V1_STR
SECRET = "test-channel-secret"
URL = f"{PREFIX}/notifications/line/webhook"


@pytest.fixture(autouse=True)
def line_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LINE_CHANNEL_SECRET", SECRET)
    monkeypatch.setattr(settings, "LINE_CHANNEL_ACCESS_TOKEN", "token")


@pytest.fixture(autouse=True)
def replies(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    sent: list[dict[str, str]] = []

    def fake_reply(*, reply_token: str, text: str) -> None:
        sent.append({"reply_token": reply_token, "text": text})

    monkeypatch.setattr(notify, "send_line_reply", fake_reply)
    return sent


def _create_user(db: Session) -> User:
    return crud.create_user(
        session=db,
        user_create=UserCreate(email=random_email(), password=random_lower_string()),
    )


def _line_id() -> str:
    return f"U{uuid.uuid4().hex}"


def _bind(db: Session, line_user_id: str) -> User:
    user = _create_user(db)
    user.line_user_id = line_user_id
    db.add(user)
    db.commit()
    return user


def _post(
    client: TestClient, payload: dict[str, Any], *, secret: str = SECRET
) -> Response:
    body = json.dumps(payload).encode("utf-8")
    signature = base64.b64encode(
        hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("ascii")
    return client.post(
        URL,
        content=body,
        headers={
            "x-line-signature": signature,
            "Content-Type": "application/json",
        },
    )


def _message_event(
    text: str, line_user_id: str, reply_token: str = "rt-1"
) -> dict[str, Any]:
    return {
        "type": "message",
        "replyToken": reply_token,
        "source": {"type": "user", "userId": line_user_id},
        "message": {"type": "text", "text": text},
    }


# --- signature: the trust boundary -----------------------------------------


def test_valid_signature_is_accepted(client: TestClient) -> None:
    r = _post(client, {"destination": "U1", "events": []})
    assert r.status_code == 200


def test_invalid_signature_is_rejected_and_binds_nothing(
    client: TestClient, db: Session
) -> None:
    user = _create_user(db)
    record = crud.create_line_connect_code(session=db, user_id=user.id)
    r = _post(
        client,
        {"events": [_message_event(record.code, _line_id())]},
        secret="wrong-secret",
    )
    assert r.status_code == 400
    db.refresh(user)
    assert user.line_user_id is None


def test_missing_signature_header_is_rejected(client: TestClient) -> None:
    r = client.post(URL, content=b'{"events":[]}')
    assert r.status_code == 400


def test_unset_secret_fails_closed_with_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "LINE_CHANNEL_SECRET", None)
    r = _post(client, {"events": []})
    assert r.status_code == 503


def test_body_is_never_logged(
    client: TestClient,
    db: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The body carries LINE userIds. Same discipline as the Telegram bot token.
    user = _create_user(db)
    record = crud.create_line_connect_code(session=db, user_id=user.id)
    line_id = _line_id()
    with caplog.at_level(logging.DEBUG):
        _post(client, {"events": [_message_event(record.code, line_id)]})
    combined = "\n".join(r.getMessage() for r in caplog.records)
    assert line_id not in combined
    assert record.code not in combined


# --- binding ---------------------------------------------------------------


def test_happy_path_binds_the_line_user_id(
    client: TestClient, db: Session, replies: list
) -> None:
    user = _create_user(db)
    record = crud.create_line_connect_code(session=db, user_id=user.id)
    line_id = _line_id()
    r = _post(client, {"events": [_message_event(record.code, line_id)]})
    assert r.status_code == 200
    db.refresh(user)
    assert user.line_user_id == line_id
    assert replies and replies[0]["reply_token"] == "rt-1"


def test_a_forged_code_binds_nobody(
    client: TestClient, db: Session, replies: list
) -> None:
    user = _create_user(db)
    crud.create_line_connect_code(session=db, user_id=user.id)
    r = _post(
        client, {"events": [_message_event(uuid.uuid4().hex, _line_id())]}
    )
    assert r.status_code == 200
    db.refresh(user)
    assert user.line_user_id is None
    # Silence is deliberate: replying "invalid code" to arbitrary text would
    # confirm to a guesser that codes exist to be guessed.
    assert replies == []


def test_a_consumed_code_does_not_bind_twice(
    client: TestClient, db: Session
) -> None:
    # LINE redelivers webhooks; this replay path is routine, not theoretical.
    first_user = _create_user(db)
    record = crud.create_line_connect_code(session=db, user_id=first_user.id)
    _post(client, {"events": [_message_event(record.code, _line_id())]})

    second_id = _line_id()
    r = _post(client, {"events": [_message_event(record.code, second_id)]})
    assert r.status_code == 200
    db.refresh(first_user)
    assert first_user.line_user_id != second_id


def test_a_group_source_never_binds(
    client: TestClient, db: Session
) -> None:
    # Binding a group id would deliver a user's stock and pricing alerts into
    # a group chat.
    user = _create_user(db)
    record = crud.create_line_connect_code(session=db, user_id=user.id)
    event = _message_event(record.code, _line_id())
    event["source"] = {"type": "group", "groupId": "G123"}
    r = _post(client, {"events": [event]})
    assert r.status_code == 200
    db.refresh(user)
    assert user.line_user_id is None


def test_two_events_in_one_post_are_both_processed(
    client: TestClient, db: Session
) -> None:
    first, second = _create_user(db), _create_user(db)
    code_one = crud.create_line_connect_code(session=db, user_id=first.id)
    code_two = crud.create_line_connect_code(session=db, user_id=second.id)
    id_one, id_two = _line_id(), _line_id()
    r = _post(
        client,
        {
            "events": [
                _message_event(code_one.code, id_one, reply_token="rt-a"),
                _message_event(code_two.code, id_two, reply_token="rt-b"),
            ]
        },
    )
    assert r.status_code == 200
    db.refresh(first)
    db.refresh(second)
    assert first.line_user_id == id_one
    assert second.line_user_id == id_two


def test_non_message_events_are_ignored_but_still_200(
    client: TestClient, replies: list
) -> None:
    # A non-200 makes LINE retry and eventually disable the webhook entirely,
    # which would break enrollment for everyone.
    for event_type in ("follow", "join", "leave", "postback"):
        r = _post(
            client,
            {
                "events": [
                    {
                        "type": event_type,
                        "replyToken": "rt-x",
                        "source": {"type": "user", "userId": "U999"},
                    }
                ]
            },
        )
        assert r.status_code == 200, event_type
    assert replies == []


def test_a_sticker_message_is_ignored(client: TestClient, replies: list) -> None:
    event = {
        "type": "message",
        "replyToken": "rt-1",
        "source": {"type": "user", "userId": "U999"},
        "message": {"type": "sticker", "packageId": "1"},
    }
    r = _post(client, {"events": [event]})
    assert r.status_code == 200
    assert replies == []


def test_a_cross_bound_line_account_is_refused_and_told_why(
    client: TestClient, db: Session, replies: list
) -> None:
    shared = _line_id()
    _bind(db, shared)
    latecomer = _create_user(db)
    record = crud.create_line_connect_code(session=db, user_id=latecomer.id)

    r = _post(client, {"events": [_message_event(record.code, shared)]})
    assert r.status_code == 200
    db.refresh(latecomer)
    assert latecomer.line_user_id is None
    assert replies and "already connected" in replies[0]["text"].lower()


def test_a_failed_reply_does_not_roll_back_the_bind(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The reply is best-effort, exactly like notify().
    def boom(*, reply_token: str, text: str) -> None:  # noqa: ARG001
        raise notify.PermanentNotifyError("HTTP 400")

    monkeypatch.setattr(notify, "send_line_reply", boom)
    user = _create_user(db)
    record = crud.create_line_connect_code(session=db, user_id=user.id)
    line_id = _line_id()
    r = _post(client, {"events": [_message_event(record.code, line_id)]})
    assert r.status_code == 200
    db.refresh(user)
    assert user.line_user_id == line_id


# --- unfollow --------------------------------------------------------------


def test_unfollow_clears_the_binding(
    client: TestClient, db: Session
) -> None:
    # send_line reports SENT even when the user has blocked the Official
    # Account -- LINE returns 200 regardless. Clearing on unfollow turns that
    # silent failure into an accurate "Not connected" in the UI.
    line_id = _line_id()
    user = _bind(db, line_id)
    r = _post(
        client,
        {
            "events": [
                {"type": "unfollow", "source": {"type": "user", "userId": line_id}}
            ]
        },
    )
    assert r.status_code == 200
    db.refresh(user)
    assert user.line_user_id is None


def test_unfollow_for_an_unknown_user_is_a_no_op(
    client: TestClient
) -> None:
    r = _post(
        client,
        {
            "events": [
                {
                    "type": "unfollow",
                    "source": {"type": "user", "userId": _line_id()},
                }
            ]
        },
    )
    assert r.status_code == 200


# --- hostile / malformed payloads ------------------------------------------
#
# Everything below reaches the handler with a VALID signature, so the trust
# boundary has already been passed. These guard the always-200 contract: an
# unhandled exception here is a 5xx, and repeated 5xx makes LINE disable the
# webhook for every user.


@pytest.mark.parametrize(
    "event",
    [
        pytest.param({"type": "message", "source": "not-a-dict"}, id="source-str"),
        pytest.param({"type": "message", "source": []}, id="source-list"),
        pytest.param({"type": "message", "source": 7}, id="source-int"),
        pytest.param(
            {
                "type": "message",
                "source": {"type": "user", "userId": "U1"},
                "message": "not-a-dict",
            },
            id="message-str",
        ),
        pytest.param(
            {
                "type": "message",
                "source": {"type": "user", "userId": "U1"},
                "message": [],
            },
            id="message-list",
        ),
        pytest.param(
            {
                "type": "message",
                "source": {"type": "user", "userId": ["not", "a", "string"]},
                "message": {"type": "text", "text": "x"},
            },
            id="userid-list",
        ),
        pytest.param(
            {
                "type": "message",
                "source": {"type": "user", "userId": "U1"},
                "message": {"type": "text", "text": 12345},
            },
            id="text-int",
        ),
        pytest.param({"type": "message"}, id="no-source"),
        pytest.param({}, id="empty-event"),
    ],
)
def test_malformed_events_never_500(
    client: TestClient, event: dict[str, Any]
) -> None:
    # `or {}` would substitute a default only for FALSY values, so a truthy
    # non-dict sails through and raises AttributeError on .get().
    r = _post(client, {"events": [event]})
    assert r.status_code == 200, f"{event} produced {r.status_code}"


def test_a_malformed_event_does_not_discard_the_rest_of_the_batch(
    client: TestClient, db: Session
) -> None:
    # LINE batches events. If one bad event unwound the loop, the good events
    # delivered alongside it would be silently lost -- and LINE would not
    # redeliver, because it got its 200.
    user = _create_user(db)
    record = crud.create_line_connect_code(session=db, user_id=user.id)
    line_id = _line_id()
    r = _post(
        client,
        {
            "events": [
                {"type": "message", "source": "not-a-dict"},
                _message_event(record.code, line_id),
            ]
        },
    )
    assert r.status_code == 200
    db.refresh(user)
    assert user.line_user_id == line_id


def test_events_not_a_list_is_ignored(client: TestClient) -> None:
    r = _post(client, {"events": {"not": "a list"}})
    assert r.status_code == 200


def test_a_non_object_payload_is_ignored(client: TestClient) -> None:
    body = "[1, 2, 3]"
    signature = base64.b64encode(
        hmac.new(SECRET.encode("utf-8"), body.encode(), hashlib.sha256).digest()
    ).decode("ascii")
    r = client.post(
        URL,
        content=body.encode(),
        headers={"x-line-signature": signature, "Content-Type": "application/json"},
    )
    assert r.status_code == 200


def test_unparseable_json_with_a_valid_signature_is_a_400(
    client: TestClient,
) -> None:
    body = b"{not json at all"
    signature = base64.b64encode(
        hmac.new(SECRET.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("ascii")
    r = client.post(
        URL,
        content=body,
        headers={"x-line-signature": signature, "Content-Type": "application/json"},
    )
    assert r.status_code == 400


# --- unauthenticated resource use ------------------------------------------


def test_an_oversized_body_is_rejected_without_buffering(client: TestClient) -> None:
    # The route is unauthenticated AND deliberately unthrottled, so without a
    # size cap an attacker with no valid signature can make the server buffer
    # an arbitrarily large payload, repeatedly.
    from app.api.routes.notifications import MAX_LINE_WEBHOOK_BODY_BYTES

    oversized = b"a" * (MAX_LINE_WEBHOOK_BODY_BYTES + 1)
    r = client.post(
        URL,
        content=oversized,
        headers={
            "x-line-signature": "irrelevant-we-should-not-get-that-far",
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 413


def test_a_normal_sized_body_still_works(client: TestClient, db: Session) -> None:
    # The cap must not clip real traffic: a full batch of events is small.
    user = _create_user(db)
    record = crud.create_line_connect_code(session=db, user_id=user.id)
    line_id = _line_id()
    r = _post(client, {"events": [_message_event(record.code, line_id)]})
    assert r.status_code == 200
    db.refresh(user)
    assert user.line_user_id == line_id
