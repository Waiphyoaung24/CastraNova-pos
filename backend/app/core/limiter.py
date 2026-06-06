from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

limiter = Limiter(key_func=get_remote_address, enabled=settings.RATE_LIMIT_ENABLED)

# spec §5.1: brute-force protection on login.
LOGIN_RATE_LIMIT = "5/15 minutes"
