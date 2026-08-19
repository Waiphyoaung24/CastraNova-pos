"""Desired runtime-role grants are reconciled after every migration run."""

from unittest.mock import MagicMock

import pytest

import app.reconcile_app_role_grants as reconcile
from app.core.config import settings


def _forbid_create_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("create_engine must not be called")

    monkeypatch.setattr(reconcile, "create_engine", _fail)


def test_unset_user_skips_without_connecting(monkeypatch: pytest.MonkeyPatch) -> None:
    _forbid_create_engine(monkeypatch)
    monkeypatch.setattr(settings, "POSTGRES_APP_USER", "")

    reconcile.main()


def test_invalid_role_name_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _forbid_create_engine(monkeypatch)
    monkeypatch.setattr(settings, "POSTGRES_APP_USER", 'bad"name')

    with pytest.raises(ValueError, match=r"POSTGRES_APP_USER must match"):
        reconcile.main()


def test_reconciles_privileges_and_discovers_ledgers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statements: set[str] = set()
    connection = MagicMock()

    def execute(statement: object) -> MagicMock:
        sql = str(statement)
        statements.add(sql)
        result = MagicMock()
        if "reject_ledger_mutation" in sql:
            result.scalars.return_value = iter(
                ("public.unitmovement", "public.futureledger")
            )
        return result

    connection.execute.side_effect = execute
    engine = MagicMock()
    engine.begin.return_value.__enter__.return_value = connection
    monkeypatch.setattr(reconcile, "create_engine", lambda _uri: engine)
    monkeypatch.setattr(settings, "POSTGRES_APP_USER", "castranova_app")

    reconcile.main()

    assert {
        'GRANT USAGE ON SCHEMA public TO "castranova_app"',
        'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO "castranova_app"',
        'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "castranova_app"',
        'REVOKE DELETE ON ALL TABLES IN SCHEMA public FROM "castranova_app"',
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE "
        'ON TABLES TO "castranova_app"',
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON "
        'SEQUENCES TO "castranova_app"',
        'GRANT DELETE ON "user" TO "castranova_app"',
        'REVOKE ALL ON alembic_version FROM "castranova_app"',
        'REVOKE UPDATE, DELETE ON public.unitmovement FROM "castranova_app"',
        'REVOKE UPDATE, DELETE ON public.futureledger FROM "castranova_app"',
    } <= statements
