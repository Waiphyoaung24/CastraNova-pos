"""A DB IntegrityError that escapes crud must surface as a sanitized 409,
never a raw 500 leaking constraint/table names (hardening spec §4.1.1).

Domain 409s raised explicitly by crud (PRD §10: "already sold by ...") are NOT
covered by this handler and keep their informative payloads.
"""

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.main import app


def test_integrity_error_returns_sanitized_409() -> None:
    # tags= is required because the app's custom_generate_unique_id reads tags[0].
    @app.get("/_test/integrity-boom", include_in_schema=False, tags=["_test"])
    def _boom() -> None:  # pragma: no cover - exercised via TestClient
        raise IntegrityError(
            statement="INSERT INTO secret_table ...",
            params=None,
            orig=Exception('violates check constraint "ck_secret_internal"'),
        )

    try:
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/_test/integrity-boom")
        assert r.status_code == 409
        assert r.json() == {"detail": "Conflicting or invalid data."}
        body = r.text.lower()
        assert "secret_table" not in body
        assert "ck_secret_internal" not in body
    finally:
        app.router.routes = [
            rt
            for rt in app.router.routes
            if getattr(rt, "path", "") != "/_test/integrity-boom"
        ]
