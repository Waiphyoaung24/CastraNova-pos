import logging

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy.exc import IntegrityError
from starlette.middleware.cors import CORSMiddleware

from app.api.main import api_router
from app.core.config import settings
from app.core.limiter import limiter

logger = logging.getLogger(__name__)


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


if settings.SENTRY_DSN and settings.ENVIRONMENT != "local":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]


@app.exception_handler(IntegrityError)
async def integrity_error_handler(
    request: Request, _exc: IntegrityError
) -> JSONResponse:
    # Sanitized boundary for IntegrityErrors that escape crud's explicit
    # catches (programming bugs / raw SQL). Domain conflicts (PRD §10) are
    # raised by crud as informative HTTPException(409)s and never reach here.
    # Full detail goes to logs/Sentry; the client gets no schema internals.
    logger.exception(
        "Unhandled IntegrityError on %s %s", request.method, request.url.path
    )
    return JSONResponse(
        status_code=409, content={"detail": "Conflicting or invalid data."}
    )

# Set all CORS enabled origins
if settings.all_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.all_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix=settings.API_V1_STR)
