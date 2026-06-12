"""Guards in app/ensure_app_role.py — pure logic, no DB connection."""

import pytest

import app.ensure_app_role as ensure_app_role
from app.core.config import settings


def _forbid_create_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("create_engine must not be called")

    monkeypatch.setattr(ensure_app_role, "create_engine", _fail)


def test_invalid_role_name_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _forbid_create_engine(monkeypatch)
    monkeypatch.setattr(settings, "POSTGRES_APP_USER", 'bad"name')
    monkeypatch.setattr(settings, "POSTGRES_APP_PASSWORD", "secret")
    with pytest.raises(ValueError, match=r"POSTGRES_APP_USER must match"):
        ensure_app_role.main()


def test_user_set_but_empty_password_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _forbid_create_engine(monkeypatch)
    monkeypatch.setattr(settings, "POSTGRES_APP_USER", "castranova_app")
    monkeypatch.setattr(settings, "POSTGRES_APP_PASSWORD", "")
    with pytest.raises(ValueError, match=r"POSTGRES_APP_PASSWORD must be set"):
        ensure_app_role.main()


def test_unset_user_skips_without_connecting(monkeypatch: pytest.MonkeyPatch) -> None:
    _forbid_create_engine(monkeypatch)
    monkeypatch.setattr(settings, "POSTGRES_APP_USER", "")
    ensure_app_role.main()  # no-op: returns before touching the engine
