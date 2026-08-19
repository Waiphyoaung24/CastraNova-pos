from collections.abc import Generator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlmodel import Session

from app.core import security
from app.core.config import settings
from app.core.db import engine
from app.models import TokenPayload, User, UserRole

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token"
)


def get_db() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_db)]
TokenDep = Annotated[str, Depends(reusable_oauth2)]


# A token the server cannot resolve to a valid, active user is an
# AUTHENTICATION failure -> 401 (with WWW-Authenticate: Bearer) so clients
# re-authenticate. 401 is reserved here for exactly that; 403 stays for an
# authenticated user who lacks a role (see get_admin), and route-level resource
# lookups keep their own 404s. This includes the stale-token case (valid
# signature, subject no longer a user): still an auth failure, not a 404.
_CREDENTIALS_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(session: SessionDep, token: TokenDep) -> User:
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
    except (InvalidTokenError, ValidationError):
        raise _CREDENTIALS_EXC
    # Only access-typed tokens may act as bearer credentials (rejects refresh
    # tokens and any token missing a type claim).
    if token_data.type != "access":
        raise _CREDENTIALS_EXC
    user = session.get(User, token_data.sub)
    if not user:
        raise _CREDENTIALS_EXC
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_current_active_superuser(current_user: CurrentUser) -> User:
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="The user doesn't have enough privileges"
        )
    return current_user


def is_admin(user: User) -> bool:
    """A superuser OR an explicit BKK_ADMIN is treated as admin everywhere."""
    return user.is_superuser or user.role == UserRole.BKK_ADMIN


def get_admin(current_user: CurrentUser) -> User:
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Admin only")
    return current_user


AdminUser = Annotated[User, Depends(get_admin)]


def bind_rate_limit_identity(request: Request, current_user: CurrentUser) -> None:
    """Stash the authenticated user's id where the limiter's key_func can read
    it (see ``core.limiter.user_or_remote_address``).

    Needed because ``get_remote_address`` keys on the client IP, and staff at
    one site share a public IP -- an IP-keyed limit sized for one user's poll
    would 429 the second person to connect. slowapi's key_func only receives
    the Request, hence the handoff through ``request.state``. FastAPI resolves
    dependencies before invoking the endpoint that slowapi's decorator wraps,
    so this always runs first.
    """
    request.state.rate_limit_key = str(current_user.id)
