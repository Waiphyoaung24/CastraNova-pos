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
REFRESH_RATE_LIMIT = "5/15 minutes"  # spec §6.2: auth endpoints
LOGOUT_RATE_LIMIT = "20/15 minutes"
PRICING_OVERRIDE_RATE_LIMIT = "30/hour"  # threshold-probe + queue-flood guard
SYNC_INGEST_RATE_LIMIT = "120/hour"  # above any legit 7-day-queue replay burst
