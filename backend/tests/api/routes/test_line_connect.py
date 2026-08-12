"""Route tests for the LINE self-service connect flow.

connect mints a one-time code and renders the line.me deep link; disconnect
clears the binding. Neither route makes an outbound call, so unlike
test_telegram_connect.py there is nothing to monkeypatch. The webhook side
lives in test_line_webhook.py.
"""

import re
import uuid
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.core.limiter import limiter
from app.models import LineConnectCode, User, UserCreate
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import random_email, random_lower_string

PREFIX = settings.API_V1_STR
BASIC_ID = "@097shucy"


@pytest.fixture
def user_and_headers(client: TestClient, db: Session) -> tuple[User, dict[str, str]]:
    email = random_email()
    headers = authentication_token_from_email(client=client, email=email, db=db)
    user = crud.get_user_by_email(session=db, email=email)
    assert user is not None
    return user, headers


@pytest.fixture(autouse=True)
def line_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LINE_BOT_BASIC_ID", BASIC_ID)
    monkeypatch.setattr(settings, "LINE_CHANNEL_SECRET", "secret")
    monkeypatch.setattr(settings, "LINE_CHANNEL_ACCESS_TOKEN", "token")


# --- connect ---------------------------------------------------------------


def test_connect_mints_a_code_and_deep_link(
    client: TestClient,
    user_and_headers: tuple[User, dict[str, str]],
) -> None:
    _user, headers = user_and_headers
    r = client.post(f"{PREFIX}/notifications/line/connect", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    # 32 hex chars == 128 bits: the code is a bearer credential, because the
    # webhook that consumes it has no session to authenticate against.
    assert re.fullmatch(r"[0-9a-f]{32}", body["code"])
    assert body["qr_code_data_uri"].startswith("data:image/png;base64,")
    assert body["expires_at"]


def test_deep_link_percent_encodes_the_basic_id(
    client: TestClient,
    user_and_headers: tuple[User, dict[str, str]],
) -> None:
    # An unencoded '@' still works but LINE deprecates it. The deep link is
    # the entire enrollment entry point -- if it is malformed nothing else in
    # this feature ever runs.
    _user, headers = user_and_headers
    r = client.post(f"{PREFIX}/notifications/line/connect", headers=headers)
    body = r.json()
    assert body["deep_link"] == (
        f"https://line.me/R/oaMessage/{quote(BASIC_ID, safe='')}/?{body['code']}"
    )
    assert "%40097shucy" in body["deep_link"]
    assert "@" not in body["deep_link"]


def test_connect_without_configuration_is_a_400(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    user_and_headers: tuple[User, dict[str, str]],
) -> None:
    monkeypatch.setattr(settings, "LINE_BOT_BASIC_ID", None)
    _user, headers = user_and_headers
    r = client.post(f"{PREFIX}/notifications/line/connect", headers=headers)
    assert r.status_code == 400
    assert "not configured" in r.json()["detail"].lower()


def test_connect_requires_authentication(
    client: TestClient
) -> None:
    r = client.post(f"{PREFIX}/notifications/line/connect")
    assert r.status_code == 401


def test_connect_reaps_only_this_users_codes(
    client: TestClient,
    db: Session,
    user_and_headers: tuple[User, dict[str, str]],
) -> None:
    user, headers = user_and_headers
    other = crud.create_user(
        session=db,
        user_create=UserCreate(email=random_email(), password=random_lower_string()),
    )
    theirs = crud.create_line_connect_code(session=db, user_id=other.id)

    client.post(f"{PREFIX}/notifications/line/connect", headers=headers)
    client.post(f"{PREFIX}/notifications/line/connect", headers=headers)

    mine = db.exec(
        select(LineConnectCode).where(LineConnectCode.user_id == user.id)
    ).all()
    assert len(mine) == 1
    survived = db.exec(
        select(LineConnectCode).where(LineConnectCode.code == theirs.code)
    ).first()
    assert survived is not None


def test_connect_is_rate_limited_per_user(
    client: TestClient,
    user_and_headers: tuple[User, dict[str, str]],
) -> None:
    _user, headers = user_and_headers
    limiter.reset()
    limiter.enabled = True
    try:
        codes = [
            client.post(
                f"{PREFIX}/notifications/line/connect", headers=headers
            ).status_code
            for _ in range(20)
        ]
        assert all(c == 200 for c in codes)
        r21 = client.post(f"{PREFIX}/notifications/line/connect", headers=headers)
        assert r21.status_code == 429
    finally:
        limiter.enabled = False
        limiter.reset()


def test_one_users_limit_does_not_block_another_user(
    client: TestClient,
    db: Session,
    user_and_headers: tuple[User, dict[str, str]],
) -> None:
    """The half that actually proves per-user keying. Both users share a
    client IP here, so if the bucket were IP-keyed user B would 429 on user
    A's spending -- which is review finding M1 on /telegram/test, and exactly
    what a shop with every till behind one public IP would hit."""
    _user_a, headers_a = user_and_headers
    email_b = random_email()
    headers_b = authentication_token_from_email(client=client, email=email_b, db=db)

    limiter.reset()
    limiter.enabled = True
    try:
        for _ in range(20):
            client.post(f"{PREFIX}/notifications/line/connect", headers=headers_a)
        assert (
            client.post(
                f"{PREFIX}/notifications/line/connect", headers=headers_a
            ).status_code
            == 429
        )

        r_b = client.post(f"{PREFIX}/notifications/line/connect", headers=headers_b)
        assert r_b.status_code == 200, r_b.text
    finally:
        limiter.enabled = False
        limiter.reset()


# --- disconnect ------------------------------------------------------------


def test_disconnect_clears_the_binding_and_is_idempotent(
    client: TestClient, db: Session, user_and_headers: tuple[User, dict[str, str]]
) -> None:
    user, headers = user_and_headers
    user.line_user_id = f"U{uuid.uuid4().hex}"
    db.add(user)
    db.commit()

    first = client.delete(f"{PREFIX}/notifications/line/disconnect", headers=headers)
    assert first.status_code == 200
    db.refresh(user)
    assert user.line_user_id is None

    second = client.delete(f"{PREFIX}/notifications/line/disconnect", headers=headers)
    assert second.status_code == 200


def test_disconnect_requires_authentication(client: TestClient) -> None:
    r = client.delete(f"{PREFIX}/notifications/line/disconnect")
    assert r.status_code == 401


def test_disconnect_does_not_affect_another_user(
    client: TestClient, db: Session, user_and_headers: tuple[User, dict[str, str]]
) -> None:
    _user, headers = user_and_headers
    other_id = f"U{uuid.uuid4().hex}"
    other = crud.create_user(
        session=db,
        user_create=UserCreate(email=random_email(), password=random_lower_string()),
    )
    other.line_user_id = other_id
    db.add(other)
    db.commit()

    client.delete(f"{PREFIX}/notifications/line/disconnect", headers=headers)

    db.refresh(other)
    assert other.line_user_id == other_id
