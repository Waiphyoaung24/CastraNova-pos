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
