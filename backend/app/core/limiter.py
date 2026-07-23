from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

# get_remote_address reads request.client.host (the TCP peer). Behind Traefik
# that peer is the proxy container, so uvicorn must resolve X-Forwarded-For into
# request.client first: compose.yml sets FORWARDED_ALLOW_IPS=* on the backend
# service (safe — no published ports, only Traefik can reach it). Do NOT parse
# X-Forwarded-For here without a trusted-proxy list.
limiter = Limiter(key_func=get_remote_address, enabled=settings.RATE_LIMIT_ENABLED)

LOGIN_RATE_LIMIT = "5/15 minutes"  # spec §5.1: brute-force protection on login
REFRESH_RATE_LIMIT = "60/15 minutes"  # cap is shop-global (keyed on the proxy IP
# in prod), and every active device needs >=1 refresh per 15min access-token
# lifetime. The refresh credential is a signed httponly 12h JWT, not a
# guessable secret, so a tight cap buys little brute-force protection while
# risking a shop-wide forced logout once refreshes start 429ing.
LOGOUT_RATE_LIMIT = "20/15 minutes"
PRICING_OVERRIDE_RATE_LIMIT = "30/hour"  # threshold-probe + queue-flood guard
# Polling read for FR-010: the sale screen polls each pending override every
# ~4s, so this is sized well above legitimate cadence, as a flood backstop.
PRICING_OVERRIDE_POLL_RATE_LIMIT = "120/minute"
SYNC_INGEST_RATE_LIMIT = "120/hour"  # above any legit 7-day-queue replay burst
TELEGRAM_TEST_RATE_LIMIT = "10/hour"  # it's a real outbound send to Telegram's API


def user_or_remote_address(request: Request) -> str:
    """Per-user rate-limit key, falling back to the client IP.

    The fallback is deliberate: if a route ever loses its
    ``bind_rate_limit_identity`` dependency, the limit degrades to today's
    IP-keyed behaviour rather than raising or -- worse -- silently keying every
    request in the process to one shared bucket.
    """
    key: str | None = getattr(request.state, "rate_limit_key", None)
    return key or get_remote_address(request)


# Both keyed per user (see user_or_remote_address), not per IP. As with every
# limit in this module the buckets are per-process and the container runs 4
# workers, so real ceilings are up to 4x these numbers -- they are
# runaway-loop guards, not precise quotas. What actually bounds outbound
# Telegram traffic is the TTL cache in services/notify.py.
TELEGRAM_CONNECT_RATE_LIMIT = "20/hour"  # a deliberate tap that renders a QR PNG
TELEGRAM_CONFIRM_RATE_LIMIT = "60/minute"  # 3x the client's 20/min poll rate
