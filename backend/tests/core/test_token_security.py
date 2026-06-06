from datetime import timedelta

import jwt

from app.core import security
from app.core.config import settings


def test_access_token_carries_access_type():
    tok = security.create_access_token("user-1", expires_delta=timedelta(minutes=5))
    payload = jwt.decode(tok, settings.SECRET_KEY, algorithms=[security.ALGORITHM])
    assert payload["sub"] == "user-1"
    assert payload["type"] == "access"


def test_refresh_token_carries_refresh_type():
    tok = security.create_refresh_token("user-1", expires_delta=timedelta(minutes=5))
    payload = jwt.decode(tok, settings.SECRET_KEY, algorithms=[security.ALGORITHM])
    assert payload["sub"] == "user-1"
    assert payload["type"] == "refresh"


def test_refresh_cookie_name_constant():
    assert security.REFRESH_TOKEN_COOKIE_NAME == "refresh_token"
