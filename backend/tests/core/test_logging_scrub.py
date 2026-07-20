import logging

from app.core.logging import configure_logging, scrub_telegram_token_from_event

TOKEN = "123456:ABC-secret-DEF"


def test_httpx_info_is_suppressed(caplog):
    configure_logging()
    caplog.set_level(logging.DEBUG)
    httpx_logger = logging.getLogger("httpx")

    httpx_logger.info(
        "HTTP Request: POST https://api.telegram.org/bot%s/sendMessage \"HTTP/1.1 200 OK\"",
        TOKEN,
    )
    httpx_logger.warning("something actually went wrong")

    messages = [r.getMessage() for r in caplog.records]
    assert not any(TOKEN in m for m in messages)
    assert any("something actually went wrong" in m for m in messages)


def test_scrub_telegram_token_redacts_url():
    event = {
        "breadcrumbs": [
            {"data": {"url": f"https://api.telegram.org/bot{TOKEN}/sendMessage"}}
        ]
    }
    scrubbed = scrub_telegram_token_from_event(event, {})  # type: ignore[arg-type]
    url = scrubbed["breadcrumbs"][0]["data"]["url"]
    assert TOKEN not in url
    assert "api.telegram.org/bot<redacted>" in url


def test_scrub_telegram_token_handles_nested_lists():
    event = {
        "extra": {
            "urls": [
                f"https://api.telegram.org/bot{TOKEN}/getUpdates",
                "https://example.com/unrelated",
            ]
        }
    }
    scrubbed = scrub_telegram_token_from_event(event, {})  # type: ignore[arg-type]
    urls = scrubbed["extra"]["urls"]
    assert TOKEN not in urls[0]
    assert "api.telegram.org/bot<redacted>" in urls[0]
    assert urls[1] == "https://example.com/unrelated"


def test_scrub_telegram_token_passthrough_without_telegram_url():
    event = {"message": "no telegram url here"}
    assert scrub_telegram_token_from_event(event, {}) == event  # type: ignore[arg-type]
