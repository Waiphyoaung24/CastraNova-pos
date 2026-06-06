# Part 5.1 — Auth Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Each task is TDD: write the failing test, watch it fail, write minimal code, watch it pass, commit.

**Goal:** Harden authentication for CastraNova-POS by (a) rate-limiting `/login/access-token` to 5 attempts per 15 minutes and (b) adding a refresh-token flow that issues a hardened `httpOnly` / `secure` / `sameSite=lax` cookie, with a `/login/refresh-token` rotation endpoint and a `/login/logout` endpoint.

**Architecture:** JWTs gain a `type` claim (`"access"` vs `"refresh"`) so a long-lived refresh token can never be used as a bearer access token (the bearer boundary in `deps.get_current_user` rejects `type=="refresh"`). The refresh token is delivered only as an `httpOnly` cookie scoped to `/api/v1/login`; `/login/refresh-token` reads the cookie, validates it, rotates it, and mints a fresh short-lived access token. Rate limiting uses `slowapi` (already a dependency) via a shared `Limiter` in `app/core/limiter.py`, disabled by default in the test session and toggled on only inside the dedicated rate-limit test.

**Tech Stack:** FastAPI, SQLModel, PyJWT (`HS256`), `slowapi` (`>=0.1.9`), pytest. No new dependencies, no schema/migration changes (refresh tokens are stateless JWTs; no DB table).

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `backend/app/core/config.py` | Settings: refresh-token TTL, rate-limit toggle, secure-cookie flag | Modify |
| `backend/app/core/security.py` | JWT minting: `type` claim on access tokens, new `create_refresh_token`, cookie-name constant | Modify |
| `backend/app/core/limiter.py` | Shared `slowapi` `Limiter` + login-limit string | **Create** |
| `backend/app/models.py` | `TokenPayload` gains `type` field | Modify |
| `backend/app/api/deps.py` | Reject `type=="refresh"` tokens at the bearer boundary | Modify |
| `backend/app/main.py` | Register limiter on app state + 429 exception handler | Modify |
| `backend/app/api/routes/login.py` | Rate-limit decorator; set refresh cookie on login; `/login/refresh-token`; `/login/logout` | Modify |
| `backend/tests/conftest.py` | Session-autouse fixture disabling the limiter | Modify |
| `backend/tests/core/test_token_security.py` | Unit tests for token `type` claim + refresh minting | **Create** |
| `backend/tests/api/test_refresh_bearer_rejected.py` | Refresh token rejected as bearer | **Create** |
| `backend/tests/api/test_login_rate_limit.py` | 6th login → 429 | **Create** |
| `backend/tests/api/routes/test_auth_refresh.py` | Cookie issuance, refresh rotation, logout | **Create** |

---

## Task 1: Token `type` claim + refresh-token primitive

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/core/security.py`
- Modify: `backend/app/models.py` (`TokenPayload`)
- Test: `backend/tests/core/test_token_security.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/core/test_token_security.py
from datetime import timedelta

import jwt

from app.core import security
from app.core.config import settings


def test_access_token_carries_access_type():
    tok = security.create_access_token("user-1", expires_delta=timedelta(minutes=5))
    payload = jwt.decode(tok, settings.SECRET_KEY, algorithms=[security.ALGORITHM])
    assert payload["sub"] == "user-1"
    assert payload["type"] == "access"


def test_refresh_token_carries_refresh_type():
    tok = security.create_refresh_token("user-1", expires_delta=timedelta(minutes=5))
    payload = jwt.decode(tok, settings.SECRET_KEY, algorithms=[security.ALGORITHM])
    assert payload["sub"] == "user-1"
    assert payload["type"] == "refresh"


def test_refresh_cookie_name_constant():
    assert security.REFRESH_TOKEN_COOKIE_NAME == "refresh_token"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/core/test_token_security.py -v`
Expected: FAIL — `AttributeError: module 'app.core.security' has no attribute 'create_refresh_token'`.

- [ ] **Step 3a: Add settings.** In `backend/app/core/config.py`, after `ACCESS_TOKEN_EXPIRE_MINUTES` (line ~36) add:

```python
    # 60 minutes * 24 hours * 30 days = 30 days
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 30
    # Rate limiting is enabled by default; the test session disables it globally
    # and re-enables it only inside the dedicated rate-limit test.
    RATE_LIMIT_ENABLED: bool = True
```

In the same file, add a computed property next to `all_cors_origins` (after the `all_cors_origins` property block, ~line 49):

```python
    @computed_field  # type: ignore[prop-decorator]
    @property
    def cookie_secure(self) -> bool:
        # Secure cookies require HTTPS; disable only for local dev over http.
        return self.ENVIRONMENT != "local"
```

- [ ] **Step 3b: Add the `type` claim + refresh minting.** In `backend/app/core/security.py`, replace `create_access_token` and add the new constant + function:

```python
ALGORITHM = "HS256"

REFRESH_TOKEN_COOKIE_NAME = "refresh_token"


def create_access_token(subject: str | Any, expires_delta: timedelta) -> str:
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode = {"exp": expire, "sub": str(subject), "type": "access"}
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token(subject: str | Any, expires_delta: timedelta) -> str:
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode = {"exp": expire, "sub": str(subject), "type": "refresh"}
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt
```

- [ ] **Step 3c: Add `type` to `TokenPayload`.** In `backend/app/models.py`, in the `TokenPayload` class (~line 1664):

```python
# Contents of JWT token
class TokenPayload(SQLModel):
    sub: str | None = None
    type: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/core/test_token_security.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/config.py backend/app/core/security.py backend/app/models.py backend/tests/core/test_token_security.py
git commit -m "feat(auth): add JWT type claim + refresh-token primitive (Part 5.1)"
```

---

## Task 2: Reject refresh tokens at the bearer boundary

**Files:**
- Modify: `backend/app/api/deps.py` (`get_current_user`)
- Test: `backend/tests/api/test_refresh_bearer_rejected.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/api/test_refresh_bearer_rejected.py
from datetime import timedelta

import jwt
from fastapi.testclient import TestClient

from app.core import security
from app.core.config import settings


def test_refresh_token_rejected_as_bearer(client: TestClient) -> None:
    login = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={
            "username": settings.FIRST_SUPERUSER,
            "password": settings.FIRST_SUPERUSER_PASSWORD,
        },
    )
    access = login.json()["access_token"]
    sub = jwt.decode(access, settings.SECRET_KEY, algorithms=[security.ALGORITHM])["sub"]
    refresh = security.create_refresh_token(sub, expires_delta=timedelta(minutes=5))

    r = client.post(
        f"{settings.API_V1_STR}/login/test-token",
        headers={"Authorization": f"Bearer {refresh}"},
    )
    assert r.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/api/test_refresh_bearer_rejected.py -v`
Expected: FAIL — returns 200 (refresh token currently accepted as bearer).

- [ ] **Step 3: Implement.** In `backend/app/api/deps.py`, inside `get_current_user`, immediately after `token_data = TokenPayload(**payload)` and its `except` block (after line ~40), add the type check before the `user = session.get(...)` line:

```python
    if token_data.type == "refresh":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/api/test_refresh_bearer_rejected.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/deps.py backend/tests/api/test_refresh_bearer_rejected.py
git commit -m "feat(auth): reject refresh-typed JWTs at the bearer boundary (Part 5.1)"
```

---

## Task 3: Rate-limit `/login/access-token` (5 per 15 minutes)

**Files:**
- Create: `backend/app/core/limiter.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/routes/login.py`
- Modify: `backend/tests/conftest.py`
- Test: `backend/tests/api/test_login_rate_limit.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/api/test_login_rate_limit.py
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.limiter import limiter


@pytest.fixture
def rate_limit_on():
    limiter.reset()
    limiter.enabled = True
    yield
    limiter.enabled = False
    limiter.reset()


def test_sixth_login_attempt_is_rate_limited(
    client: TestClient, rate_limit_on: None
) -> None:
    url = f"{settings.API_V1_STR}/login/access-token"
    data = {"username": "nobody@example.com", "password": "wrongpass"}

    codes = [client.post(url, data=data).status_code for _ in range(5)]
    assert all(c == 400 for c in codes)

    r6 = client.post(url, data=data)
    assert r6.status_code == 429
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/api/test_login_rate_limit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.limiter'`.

- [ ] **Step 3a: Create the shared limiter.**

```python
# backend/app/core/limiter.py
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

limiter = Limiter(key_func=get_remote_address, enabled=settings.RATE_LIMIT_ENABLED)

# FR / spec §5.1: brute-force protection on login.
LOGIN_RATE_LIMIT = "5/15 minutes"
```

- [ ] **Step 3b: Wire the limiter into the app.** In `backend/app/main.py`, add imports near the top:

```python
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.limiter import limiter
```

After `app = FastAPI(...)` is constructed (after the `FastAPI(...)` block, ~line 24), register the limiter:

```python
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
```

- [ ] **Step 3c: Decorate the login route.** In `backend/app/api/routes/login.py`:

Add `Request` to the FastAPI import and import the limiter:

```python
from fastapi import APIRouter, Depends, HTTPException, Request
...
from app.core.limiter import LOGIN_RATE_LIMIT, limiter
```

Replace the `login_access_token` signature and decorator (the `request: Request` param is **required** by slowapi — the `@router.post` decorator stays above `@limiter.limit`):

```python
@router.post("/login/access-token")
@limiter.limit(LOGIN_RATE_LIMIT)
def login_access_token(
    request: Request,
    session: SessionDep,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
```

(Leave the function body unchanged for this task — the refresh cookie is added in Task 4.)

- [ ] **Step 3d: Disable the limiter for the test session.** In `backend/tests/conftest.py`, add a session-autouse fixture (near the top, after the `db` fixture):

```python
@pytest.fixture(autouse=True, scope="session")
def _disable_login_rate_limit() -> Generator[None, None, None]:
    # The suite logs in many times across fixtures; a global 5/15min limit would
    # break unrelated tests. Disable here; the rate-limit test re-enables locally.
    from app.core.limiter import limiter

    original = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original
```

(`Generator` is already imported at the top of `conftest.py`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/api/test_login_rate_limit.py -v`
Expected: PASS.

Then confirm no regression in existing login tests:
Run: `cd backend && uv run pytest tests/api/routes/test_login.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/limiter.py backend/app/main.py backend/app/api/routes/login.py backend/tests/conftest.py backend/tests/api/test_login_rate_limit.py
git commit -m "feat(auth): rate-limit login to 5/15min via slowapi (Part 5.1)"
```

---

## Task 4: Refresh cookie issuance + `/login/refresh-token` + `/login/logout`

**Files:**
- Modify: `backend/app/api/routes/login.py`
- Test: `backend/tests/api/routes/test_auth_refresh.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/api/routes/test_auth_refresh.py
from fastapi.testclient import TestClient

from app.core import security
from app.core.config import settings

LOGIN = f"{settings.API_V1_STR}/login/access-token"
REFRESH = f"{settings.API_V1_STR}/login/refresh-token"
LOGOUT = f"{settings.API_V1_STR}/login/logout"
TEST_TOKEN = f"{settings.API_V1_STR}/login/test-token"


def _login(client: TestClient):
    return client.post(
        LOGIN,
        data={
            "username": settings.FIRST_SUPERUSER,
            "password": settings.FIRST_SUPERUSER_PASSWORD,
        },
    )


def test_login_sets_httponly_refresh_cookie(client: TestClient) -> None:
    r = _login(client)
    assert r.status_code == 200
    assert r.json()["access_token"]
    set_cookie = r.headers.get("set-cookie", "").lower()
    assert security.REFRESH_TOKEN_COOKIE_NAME in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie


def test_refresh_returns_working_access_token(client: TestClient) -> None:
    login = _login(client)
    assert login.cookies.get(security.REFRESH_TOKEN_COOKIE_NAME)
    # TestClient persists the cookie and replays it to the scoped path.
    r = client.post(REFRESH)
    assert r.status_code == 200
    access = r.json()["access_token"]
    me = client.post(TEST_TOKEN, headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200


def test_refresh_without_cookie_returns_401(client: TestClient) -> None:
    client.cookies.clear()
    r = client.post(REFRESH)
    assert r.status_code == 401


def test_logout_clears_refresh_cookie(client: TestClient) -> None:
    _login(client)
    r = client.post(LOGOUT)
    assert r.status_code == 200
    set_cookie = r.headers.get("set-cookie", "").lower()
    assert security.REFRESH_TOKEN_COOKIE_NAME in set_cookie
    assert 'refresh_token=""' in set_cookie or "max-age=0" in set_cookie
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/api/routes/test_auth_refresh.py -v`
Expected: FAIL — login sets no cookie; `/login/refresh-token` and `/login/logout` return 404.

- [ ] **Step 3a: Add imports + cookie helper.** In `backend/app/api/routes/login.py`, extend imports:

```python
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
...
from app.models import Message, NewPassword, Token, TokenPayload, User, UserPublic, UserUpdate
```

Add a module-level helper after `router = APIRouter(tags=["login"])`:

```python
def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=security.REFRESH_TOKEN_COOKIE_NAME,
        value=token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path=f"{settings.API_V1_STR}/login",
    )
```

- [ ] **Step 3b: Set the cookie on login.** Update `login_access_token` to take a `response: Response` param and set the refresh cookie before returning (keep the Task 3 rate-limit decorator and `request: Request` param):

```python
@router.post("/login/access-token")
@limiter.limit(LOGIN_RATE_LIMIT)
def login_access_token(
    request: Request,
    response: Response,
    session: SessionDep,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    """
    OAuth2 compatible token login, get an access token for future requests
    """
    user = crud.authenticate(
        session=session, email=form_data.username, password=form_data.password
    )
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    elif not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    refresh_token = security.create_refresh_token(
        user.id,
        expires_delta=timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES),
    )
    _set_refresh_cookie(response, refresh_token)
    return Token(
        access_token=security.create_access_token(
            user.id, expires_delta=access_token_expires
        )
    )
```

- [ ] **Step 3c: Add the refresh + logout endpoints.** Add after `login_access_token` (before `test_token`):

```python
@router.post("/login/refresh-token")
def refresh_access_token(
    request: Request, response: Response, session: SessionDep
) -> Token:
    """
    Exchange a valid refresh cookie for a new access token (and rotate the cookie).
    """
    token = request.cookies.get(security.REFRESH_TOKEN_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Missing refresh token")
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
    except (InvalidTokenError, ValidationError):
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    if token_data.type != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    user = session.get(User, token_data.sub)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    new_refresh = security.create_refresh_token(
        user.id,
        expires_delta=timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES),
    )
    _set_refresh_cookie(response, new_refresh)
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return Token(
        access_token=security.create_access_token(
            user.id, expires_delta=access_token_expires
        )
    )


@router.post("/login/logout")
def logout(response: Response) -> Message:
    """
    Clear the refresh cookie.
    """
    response.delete_cookie(
        key=security.REFRESH_TOKEN_COOKIE_NAME,
        path=f"{settings.API_V1_STR}/login",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    return Message(message="Logged out")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/api/routes/test_auth_refresh.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/login.py backend/tests/api/routes/test_auth_refresh.py
git commit -m "feat(auth): refresh-token cookie flow + rotate/logout endpoints (Part 5.1)"
```

---

## Task 5: Verification — full suite, lint, types, SDK note

**Files:** none (verification only).

- [ ] **Step 1: Run the full backend suite**

Run: `cd backend && uv run pytest -q`
Expected: all green. If `test_login_rate_limit` interferes with other tests, confirm the conftest `_disable_login_rate_limit` autouse fixture is present and the local `rate_limit_on` fixture restores `limiter.enabled = False`.

- [ ] **Step 2: Lint + type-check**

Run: `cd backend && uv run ruff check . && uv run mypy app`
Expected: clean. (Fix any unused-import / annotation issues introduced by the new code.)

- [ ] **Step 3: Regenerate the frontend SDK (new endpoints changed OpenAPI)**

Run: `cd frontend && bun run generate-client`
Expected: `src/client/` regenerates with `refresh_access_token` + `logout` operations. Commit the regenerated client. *(If the dev stack/openapi is unavailable in this environment, defer this to Part 5.3 frontend work and note it in the PR — no frontend screen consumes these endpoints yet.)*

- [ ] **Step 4: Commit any regen / fixups**

```bash
git add -A
git commit -m "chore(sdk): regenerate client for refresh-token endpoints (Part 5.1)"
```

---

## Definition of Done

- 6th login attempt within the window returns **429** (slowapi), and the limiter does not affect the rest of the suite.
- Successful login sets an `httpOnly`, `SameSite=lax` refresh cookie (`Secure` in non-local envs).
- `/login/refresh-token` exchanges a valid refresh cookie for a working access token and rotates the cookie; missing/invalid/non-refresh cookie → 401.
- A refresh token presented as a bearer `Authorization` header is rejected (403) at `get_current_user`.
- `/login/logout` clears the cookie.
- Full backend suite green; `ruff` + `mypy` clean.

---

## Review gate (CLAUDE.md §5)

Auth/security change → before the PR, run `superpowers:requesting-code-review` **plus** the ECC `ecc:security-reviewer` agent (belt-and-suspenders on auth). This change does **not** touch stock movements / ledgers / money, so `ecc:database-reviewer` is not required.
