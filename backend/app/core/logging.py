"""Centralized logging configuration (M-7) and Sentry token scrubbing (C-2).

Configuring logging here — instead of as an import-time side effect scattered
across entrypoints — is what lets us reliably suppress httpx's own logger,
which otherwise emits the full request URL (including the Telegram bot token
that rides in the URL path, see services/notify.py) at INFO on every call.
"""

import logging
import re
from typing import Any

from sentry_sdk.types import Breadcrumb, BreadcrumbHint, Event, Hint

_TELEGRAM_TOKEN_RE = re.compile(r"(api\.telegram\.org/bot)[^/\s]+")


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO)
    # httpx logs "HTTP Request: <method> <url> ..." at INFO, and the Telegram
    # URL carries the bot token in its path — never let that reach a log record.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _scrub(value: Any) -> Any:
    """Shape-based redaction — works regardless of which token is currently
    configured (or rotated mid-process)."""
    if isinstance(value, str):
        return _TELEGRAM_TOKEN_RE.sub(r"\1<redacted>", value)
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def scrub_telegram_token_from_event(event: Event, _hint: Hint) -> Event:
    """Sentry ``before_send`` hook — redacts any Telegram bot token found in
    a URL anywhere in the event."""
    return _scrub(event)  # type: ignore[no-any-return]


def scrub_telegram_token_from_breadcrumb(
    crumb: Breadcrumb, _hint: BreadcrumbHint
) -> Breadcrumb:
    """Sentry ``before_breadcrumb`` hook — same redaction, for breadcrumbs
    (Sentry's httpx integration records the request URL here)."""
    return _scrub(crumb)  # type: ignore[no-any-return]
