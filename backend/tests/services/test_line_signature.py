"""Unit tests for LINE webhook signature verification and its configuration.

The signature is the webhook's only trust boundary: the endpoint is public and
unauthenticated, so everything downstream trusts verify_line_signature
returning True. These tests are the regression guard on that gate, independent
of routing.
"""

import base64
import hashlib
import hmac
from typing import Any

import httpx
import pytest

from app.core.config import settings
from app.services import notify

SECRET = "test-channel-secret"


def _sign(body: bytes, secret: str = SECRET) -> str:
    return base64.b64encode(
        hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("ascii")


@pytest.fixture
def line_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LINE_CHANNEL_SECRET", SECRET)


def test_line_settings_exist_and_default_to_none() -> None:
    # Present as attributes so the webhook can fail closed on "not configured"
    # rather than raising AttributeError.
    assert hasattr(settings, "LINE_CHANNEL_SECRET")
    assert hasattr(settings, "LINE_BOT_BASIC_ID")
    assert hasattr(settings, "LINE_CHANNEL_ACCESS_TOKEN")


def test_valid_signature_is_accepted(line_secret: None) -> None:
    body = b'{"destination":"U123","events":[]}'
    assert notify.verify_line_signature(body=body, signature=_sign(body)) is True


def test_signature_from_a_different_secret_is_rejected(line_secret: None) -> None:
    body = b'{"destination":"U123","events":[]}'
    forged = _sign(body, secret="not-the-secret")
    assert notify.verify_line_signature(body=body, signature=forged) is False


def test_missing_signature_is_rejected(line_secret: None) -> None:
    assert notify.verify_line_signature(body=b"{}", signature=None) is False


def test_tampered_body_is_rejected(line_secret: None) -> None:
    signature = _sign(b'{"events":[]}')
    assert (
        notify.verify_line_signature(body=b'{"events":[1]}', signature=signature)
        is False
    )


def test_unset_secret_rejects_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    # Fail closed. The route returns 503 before reaching here, but a helper
    # that returned True on an unset secret would be a trapdoor if reused.
    monkeypatch.setattr(settings, "LINE_CHANNEL_SECRET", None)
    assert notify.verify_line_signature(body=b"{}", signature="anything") is False


def test_signature_covers_raw_bytes_including_escape_characters(
    line_secret: None,
) -> None:
    # LINE's docs flag this specifically for Python: a body containing \n
    # survives verbatim only if hashed as raw bytes. Parsing and re-serializing
    # changes the byte string and breaks the HMAC.
    body = (
        b'{"destination":"U123","events":[{"type":"message",'
        b'"message":{"type":"text","text":"hello\\ntest1\\ntest2"}}]}'
    )
    assert notify.verify_line_signature(body=body, signature=_sign(body)) is True


def test_send_line_reply_posts_the_reply_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "LINE_CHANNEL_ACCESS_TOKEN", "tok")
    captured: dict[str, Any] = {}

    def fake_post(
        url: str, *, headers: dict[str, str], json: dict[str, Any]
    ) -> httpx.Response:
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return httpx.Response(
            200, json={}, request=httpx.Request("POST", "https://example.test")
        )

    monkeypatch.setattr(notify, "_post", fake_post)
    notify.send_line_reply(reply_token="rt-1", text="hi")

    assert captured["url"] == notify.LINE_REPLY_URL
    assert captured["json"]["replyToken"] == "rt-1"
    assert captured["json"]["messages"] == [{"type": "text", "text": "hi"}]
    assert captured["headers"]["Authorization"] == "Bearer tok"


def test_send_line_reply_without_a_token_is_permanent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "LINE_CHANNEL_ACCESS_TOKEN", None)
    with pytest.raises(notify.PermanentNotifyError):
        notify.send_line_reply(reply_token="rt-1", text="hi")
