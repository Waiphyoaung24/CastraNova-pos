from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

# WARNING: get_remote_address reads request.client.host (the TCP peer). Behind a
# reverse proxy (Traefik in this project) the peer is the proxy container, not the
# end user, so the limit becomes effectively global. Before production deploy
# (Part 5.4), configure proxy-header handling (e.g. uvicorn --forwarded-allow-ips
# / ProxyHeadersMiddleware) or a key_func that trusts X-Forwarded-For only from
# the known proxy. Do NOT parse X-Forwarded-For without a trusted-proxy list.
limiter = Limiter(key_func=get_remote_address, enabled=settings.RATE_LIMIT_ENABLED)

LOGIN_RATE_LIMIT = "5/15 minutes"  # spec §5.1: brute-force protection on login
REFRESH_RATE_LIMIT = "5/15 minutes"  # spec §6.2: auth endpoints
LOGOUT_RATE_LIMIT = "20/15 minutes"
PRICING_OVERRIDE_RATE_LIMIT = "30/hour"  # threshold-probe + queue-flood guard
SYNC_INGEST_RATE_LIMIT = "120/hour"  # above any legit 7-day-queue replay burst
