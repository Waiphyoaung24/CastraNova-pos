"""Report exports (FR-017, Task 3.5). .pdf/.xlsx on the 3 admin reports return
the right media type + non-empty bytes; staff are forbidden."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import export

PREFIX = settings.API_V1_STR
PDF = export.PDF_MEDIA_TYPE
XLSX = export.XLSX_MEDIA_TYPE


def _month() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.year:04d}-{now.month:02d}"


def test_export_service_renders_bytes() -> None:
    headers = ["A", "B"]
    rows = [["1", "2"], ["3", "4"]]
    pdf = export.render_table_pdf(title="T", headers=headers, rows=rows)
    xlsx = export.render_table_xlsx(title="T", headers=headers, rows=rows)
    assert pdf.startswith(b"%PDF")
    assert xlsx[:2] == b"PK"  # zip magic (xlsx is a zip)


def test_export_service_handles_empty_rows() -> None:
    pdf = export.render_table_pdf(title="T", headers=["A", "B"], rows=[])
    assert pdf.startswith(b"%PDF")


def test_channel_margin_exports(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    month = _month()
    for suffix, media in ((".pdf", PDF), (".xlsx", XLSX)):
        r = client.get(
            f"{PREFIX}/reports/channel-margin{suffix}?month={month}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith(media)
        assert len(r.content) > 0
        assert "attachment" in r.headers["content-disposition"]


def test_override_exceptions_exports(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    month = _month()
    for suffix, media in ((".pdf", PDF), (".xlsx", XLSX)):
        r = client.get(
            f"{PREFIX}/reports/override-exceptions{suffix}?month={month}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith(media)
        assert len(r.content) > 0


def test_holding_period_exports(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    for suffix, media in ((".pdf", PDF), (".xlsx", XLSX)):
        r = client.get(
            f"{PREFIX}/reports/holding-period{suffix}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith(media)
        assert len(r.content) > 0


def test_report_exports_staff_forbidden(
    client: TestClient, staff_token_headers: dict[str, str]
) -> None:
    month = _month()
    for path in (
        f"/reports/channel-margin.pdf?month={month}",
        f"/reports/channel-margin.xlsx?month={month}",
        f"/reports/override-exceptions.pdf?month={month}",
        "/reports/holding-period.xlsx",
    ):
        r = client.get(f"{PREFIX}{path}", headers=staff_token_headers)
        assert r.status_code == 403, path
