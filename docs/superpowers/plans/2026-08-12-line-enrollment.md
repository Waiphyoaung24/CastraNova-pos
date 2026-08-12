# LINE Enrollment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user bind their LINE account to their POS account, so LINE notification preferences can actually deliver.

**Architecture:** A user taps Connect, the backend mints a 128-bit single-use code and renders a `line.me/R/oaMessage` deep link that opens a chat with the code pre-typed. The user taps send; LINE POSTs a webhook to a public, unauthenticated endpoint whose only gate is an HMAC-SHA256 signature over the raw request body. The webhook resolves the code to a user, binds `line_user_id`, and replies in-chat. The connect card polls the existing preferences query — there is no `/line/status` endpoint.

**Tech Stack:** FastAPI, SQLModel, Alembic, psycopg3, stdlib `hmac`/`hashlib`/`base64` (no `line-bot-sdk`), React + TanStack Query, `@hey-api/openapi-ts`.

**Spec:** `docs/superpowers/specs/2026-08-10-line-enrollment-design.md` — Part 1 and §6 Addendum. Read both before starting. Section references below (§1.3, §6.2, …) point there.

## Global Constraints

- **Branch:** `chore/viber-removal`. Part 0 (Viber removal) is already committed here. One PR into `dev` (§6.3). Never push to `master`.
- **Alembic head is `b2c3d4e5f6a8` (m038).** The new migration is `m039`, revision `c4d5e6f7a8b0`, `down_revision = 'b2c3d4e5f6a8'`. Verify with `alembic heads` before writing it — several worktrees add migrations concurrently.
- **The connect code is a bearer credential (§1.3).** The LINE webhook has no session, so whoever echoes the code back gets bound. `secrets.token_hex(16)` (128 bits), single-use via `FOR UPDATE` check-then-set, 10-minute TTL. **None of these three may be relaxed.**
- **Verify the signature over raw body bytes, before any parsing** (§1.5.1). Re-serializing a parsed dict changes the byte string and breaks the HMAC — LINE's docs call this out specifically for Python because of escape characters like `\n`.
- **Never log the webhook request body.** It carries `userId`s. Same discipline as the Telegram bot token.
- **Always return 200 on a valid signature**, including for ignored events. A non-200 makes LINE retry and eventually disable the webhook.
- **No new dependencies.** `line-bot-sdk` is explicitly excluded; signature verification is ~6 lines of stdlib.
- **Do not modify any Telegram code path.** Zero files under the Telegram flow change. `TelegramConnectCard` is not refactored into a shared component.
- **mypy strict** is on — annotate everything. **biome** (not ESLint/Prettier) for frontend lint.
- **All DB access goes through `crud.py`.** Routes never call `session.exec` directly.
- **Webhook URL (already registered in the LINE console):** `https://castranova-api.nexuslab.asia/api/v1/notifications/line/webhook`
- **Bot basic ID:** `@097shucy` (public — it appears in the deep link). Channel ID `2011081609`.
- Run backend tests with `bash scripts/test.sh` or `pytest` **inside the container**. `docker compose up` serves stale code — tests are not in the image. Use `docker compose watch`.
- Playwright: always set `E2E_SKIP_DB_RESET=1` unless a full dev-DB reset was explicitly requested.

---

## File Structure

**Create:**

| File | Responsibility |
|---|---|
| `backend/app/alembic/versions/c4d5e6f7a8b0_m039_line_enrollment.py` | `lineconnectcode` table, `uq_user_line_user_id`, DELETE grant |
| `backend/tests/api/routes/test_line_connect.py` | connect + disconnect route tests |
| `backend/tests/api/routes/test_line_webhook.py` | webhook signature + binding + unfollow tests |
| `backend/tests/services/test_line_signature.py` | signature helper unit tests |
| `frontend/src/components/notifications/LineConnectCard.tsx` | connect/disconnect UI, polls preferences |

**Modify:**

| File | Change |
|---|---|
| `backend/app/core/config.py` | `LINE_CHANNEL_SECRET`, `LINE_BOT_BASIC_ID` |
| `backend/app/core/limiter.py` | `LINE_CONNECT_RATE_LIMIT` |
| `backend/app/models.py` | `LineConnectCode`, `LineConnectResponse`, `LineConfirmOutcome`, `User.line_user_id` unique |
| `backend/app/crud.py` | 4 new functions, none modified |
| `backend/app/services/notify.py` | `verify_line_signature`, `send_line_reply`, `LINE_REPLY_URL` |
| `backend/app/api/routes/notifications.py` | 3 new routes appended, none modified |
| `frontend/src/routes/_layout/notifications.tsx` | render `<LineConnectCard />` |
| `compose.dokploy.yml` | 3 LINE env vars into `backend.environment` (§6.2) |
| `.env.example` | 2 new placeholders |
| `CLAUDE.md` | status line |

---

## Task 1: Configuration and production env wiring

Splits from Task 2 because the `compose.dokploy.yml` gap is independently reviewable and independently *wrong today* — `LINE_CHANNEL_ACCESS_TOKEN` has never reached production (§6.2).

**Files:**
- Modify: `backend/app/core/config.py:112-118`
- Modify: `backend/app/core/limiter.py:46-47`
- Modify: `compose.dokploy.yml:90-91`
- Modify: `.env.example:54`
- Test: `backend/tests/services/test_line_signature.py`

**Interfaces:**
- Consumes: nothing
- Produces: `settings.LINE_CHANNEL_SECRET: str | None`, `settings.LINE_BOT_BASIC_ID: str | None`, `LINE_CONNECT_RATE_LIMIT: str`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/services/test_line_signature.py`:

```python
"""Unit tests for LINE webhook signature verification and its configuration.

The signature is the webhook's only trust boundary (spec §1.5), so these
tests are the regression guard on the gate itself, independent of routing.
"""

from app.core.config import settings


def test_line_settings_exist_and_default_to_none() -> None:
    # Present as attributes so the webhook can fail closed on "not configured"
    # rather than raising AttributeError.
    assert hasattr(settings, "LINE_CHANNEL_SECRET")
    assert hasattr(settings, "LINE_BOT_BASIC_ID")
    assert hasattr(settings, "LINE_CHANNEL_ACCESS_TOKEN")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend pytest tests/services/test_line_signature.py -v`
Expected: FAIL — `AssertionError` on `LINE_CHANNEL_SECRET`.

- [ ] **Step 3: Add the settings**

In `backend/app/core/config.py`, replace the LINE/Telegram token block:

```python
    # Outbound push notification tokens (FR-018). None in dev/test; the LINE
    # and Telegram clients are mocked in tests. Never log these.
    # TELEGRAM_BOT_TOKEN goes in the request URL, not a header — see notify.py.
    LINE_CHANNEL_ACCESS_TOKEN: str | None = None
    # Webhook HMAC key. SECRET -- never log it, and never return it from an
    # endpoint. Unset means the webhook fails closed with 503 (spec §1.1).
    LINE_CHANNEL_SECRET: str | None = None
    # The Official Account's basic ID, e.g. "@097shucy". Public, not secret --
    # it is percent-encoded into the connect deep link the user opens.
    LINE_BOT_BASIC_ID: str | None = None
    TELEGRAM_BOT_TOKEN: str | None = None
```

- [ ] **Step 4: Add the rate limit constant**

In `backend/app/core/limiter.py`, below `TELEGRAM_CONFIRM_RATE_LIMIT`:

```python
# Keyed per user (see user_or_remote_address), like the Telegram limits above.
# Same shape as TELEGRAM_CONNECT_RATE_LIMIT: a deliberate tap that renders a
# QR PNG. LINE has no confirm endpoint -- the card polls the preferences query
# it was going to refetch anyway -- so there is no confirm limit to match.
LINE_CONNECT_RATE_LIMIT = "20/hour"
```

- [ ] **Step 5: Thread the settings into production**

In `compose.dokploy.yml`, in `backend.environment`, after the `TELEGRAM_*` lines:

```yaml
      - LINE_CHANNEL_ACCESS_TOKEN=${LINE_CHANNEL_ACCESS_TOKEN}
      - LINE_CHANNEL_SECRET=${LINE_CHANNEL_SECRET}
      - LINE_BOT_BASIC_ID=${LINE_BOT_BASIC_ID}
```

`backend.environment` is an allowlist — a setting absent here never reaches the container no matter what `config.py` declares or the Dokploy panel holds. `LINE_CHANNEL_ACCESS_TOKEN` was missing, which is why production has never had a LINE token (§6.2). Do **not** add these to `prestart.environment`; prestart runs migrations and needs no LINE config.

In `.env.example`, under `LINE_CHANNEL_ACCESS_TOKEN=`:

```
LINE_CHANNEL_SECRET=
LINE_BOT_BASIC_ID=
```

- [ ] **Step 6: Run test to verify it passes**

Run: `docker compose exec backend pytest tests/services/test_line_signature.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/core/config.py backend/app/core/limiter.py \
        compose.dokploy.yml .env.example \
        backend/tests/services/test_line_signature.py
git commit -m "feat(notifications): LINE enrollment settings + prod env wiring

LINE_CHANNEL_ACCESS_TOKEN was declared in config.py but never added to
compose.dokploy.yml's backend.environment allowlist, so production has
never had a LINE token. Adds it alongside the two new settings."
```

---

## Task 2: Model and migration m039

**Files:**
- Modify: `backend/app/models.py` (after `TelegramConnectCode`, and `User.line_user_id`)
- Create: `backend/app/alembic/versions/c4d5e6f7a8b0_m039_line_enrollment.py`
- Test: `backend/tests/services/test_line_enrollment.py`

**Interfaces:**
- Consumes: Task 1's settings (not directly — this task is DB-only)
- Produces:
  - `LineConnectCode` table model with fields `id: uuid.UUID`, `user_id: uuid.UUID`, `code: str`, `expires_at: datetime`, `consumed_at: datetime | None`
  - `LineConfirmOutcome` enum with members `CONNECTED`, `PENDING`, `USER_ALREADY_LINKED`
  - `LineConnectResponse` schema with `code: str`, `deep_link: str`, `qr_code_data_uri: str`, `expires_at: datetime`
  - DB constraint `uq_user_line_user_id`

- [ ] **Step 1: Confirm the migration head**

Run: `docker compose exec backend alembic heads`
Expected: `b2c3d4e5f6a8 (head)`. If it differs, use the actual head as `down_revision`.

- [ ] **Step 2: Write the failing test**

Create `backend/tests/services/test_line_enrollment.py`:

```python
"""Model-level tests for LINE enrollment (spec §1.2).

Mirrors tests/services/test_telegram_enrollment.py.
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.models import LineConnectCode, User, get_datetime_utc
from tests.utils.utils import random_email, random_lower_string


def _user(db: Session, line_user_id: str | None = None) -> User:
    user = User(
        email=random_email(),
        hashed_password=random_lower_string(),
        line_user_id=line_user_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_line_user_id_is_unique_across_users(db: Session) -> None:
    shared = f"U{uuid.uuid4().hex}"
    _user(db, line_user_id=shared)
    with pytest.raises(IntegrityError):
        _user(db, line_user_id=shared)
    db.rollback()


def test_multiple_users_may_have_a_null_line_user_id(db: Session) -> None:
    # Postgres UNIQUE never treats NULL = NULL, so the constraint must not
    # block un-enrolled users -- which is every user until they connect.
    first = _user(db)
    second = _user(db)
    assert first.line_user_id is None
    assert second.line_user_id is None


def test_line_connect_code_round_trips(db: Session) -> None:
    user = _user(db)
    record = LineConnectCode(
        user_id=user.id,
        code=uuid.uuid4().hex,
        expires_at=get_datetime_utc() + timedelta(minutes=10),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    assert record.consumed_at is None
    assert record.user_id == user.id
```

- [ ] **Step 3: Run test to verify it fails**

Run: `docker compose exec backend pytest tests/services/test_line_enrollment.py -v`
Expected: FAIL — `ImportError: cannot import name 'LineConnectCode'`.

- [ ] **Step 4: Add the model and schemas**

In `backend/app/models.py`, mark `line_user_id` unique (it sits in the `User` table body alongside `telegram_chat_id`):

```python
    line_user_id: str | None = Field(default=None, max_length=128, unique=True)
```

After the `TelegramConnectCode` class, add:

```python
class LineConnectCode(SQLModel, table=True):
    """A short-lived, single-use code binding a LINE chat message back to the
    user who requested it.

    Deliberately a separate table from TelegramConnectCode rather than a
    `channel` column on it: altering the working Telegram table is the only
    migration that could regress the working Telegram path. ~12 duplicated
    lines buys that isolation.

    This code carries MORE weight than its Telegram counterpart. Telegram's
    confirm is authenticated -- it filters on `user_id == current_user.id`, so
    a leaked code alone cannot bind an account. The LINE webhook has no
    session at all: whoever echoes the code back gets bound to `user_id`. The
    code alone IS the identity. Unguessable (secrets.token_hex(16), 128 bits),
    single-use (consumed_at set atomically under FOR UPDATE) and short-lived
    (10 minutes) are therefore load-bearing security properties, not defaults
    to be relaxed for convenience.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id", nullable=False, index=True)
    code: str = Field(unique=True, index=True, max_length=32)
    expires_at: datetime = Field(sa_type=DateTime(timezone=True))  # type: ignore
    consumed_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
```

Next to `TelegramConnectResponse` / `TelegramConfirmOutcome`, add:

```python
class LineConnectResponse(SQLModel):
    code: str
    deep_link: str
    qr_code_data_uri: str
    expires_at: datetime


class LineConfirmOutcome(str, enum.Enum):
    """Why a webhook bind attempt ended. Internal only -- the webhook never
    returns this to a client, because its client is the LINE Platform, which
    must always see 200 (spec §1.5.3). It decides the in-chat reply text."""

    CONNECTED = "CONNECTED"
    # Unknown, expired, or already-consumed code. Also the ordinary case where
    # someone just messages the Official Account without a code at all.
    PENDING = "PENDING"
    # This LINE account already backs a different POS user (UNIQUE
    # line_user_id). Terminal for this attempt; the code is NOT consumed, so
    # the user can unlink there and retry within the TTL.
    USER_ALREADY_LINKED = "USER_ALREADY_LINKED"
```

- [ ] **Step 5: Write the migration**

Create `backend/app/alembic/versions/c4d5e6f7a8b0_m039_line_enrollment.py`:

```python
"""m039 line enrollment

Self-service LINE connect flow (spec §1.2):
- lineconnectcode -- the one-time-code table binding a LINE chat message back
  to the user who requested it. See the LineConnectCode model docstring: the
  webhook has no session, so the code alone is the identity. The DB only
  enforces uniqueness; unguessability, single use and TTL are application-layer.
- UNIQUE(user.line_user_id) -- a LINE account can only ever be bound to one
  POS user. This is a security requirement, not a nicety: without it two staff
  can bind the same LINE account and cross-feed each other's stock and pricing
  notifications. Safe to add outright because nothing has ever written the
  column -- every row is NULL -- and it only gets riskier the longer it waits.
  Multiple NULLs are unaffected; Postgres UNIQUE never treats NULL = NULL.
- GRANT DELETE on lineconnectcode. create_line_connect_code reaps the caller's
  prior codes, and m026's DEFAULT PRIVILEGES only cover SELECT, INSERT, UPDATE.
  m034 had to add this for telegramconnectcode after the fact; doing it here
  avoids repeating that miss.

Revision ID: c4d5e6f7a8b0
Revises: b2c3d4e5f6a8
Create Date: 2026-08-12 00:00:00.000000

"""
import os
import re

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes

# revision identifiers, used by Alembic.
revision = 'c4d5e6f7a8b0'
down_revision = 'b2c3d4e5f6a8'
branch_labels = None
depends_on = None


def _role():
    """Return the quoted app role if configured and existing, else None.

    Copied verbatim from m034/m037 -- these migrations are standalone by
    convention and do not import from each other.
    """
    role = os.environ.get("POSTGRES_APP_USER", "")
    if not role:
        return None  # role not configured — grant is a no-op (e.g. CI without env)
    # The role name is interpolated into the GRANT statement below —
    # guard against injection via a malicious/typo'd env value.
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", role):
        raise RuntimeError("POSTGRES_APP_USER must match [a-z][a-z0-9_]{0,62}")
    conn = op.get_bind()
    exists = conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}
    ).scalar()
    if not exists:
        return None
    return f'"{role}"'


def upgrade() -> None:
    op.create_unique_constraint(
        'uq_user_line_user_id', 'user', ['line_user_id']
    )
    op.create_table(
        'lineconnectcode',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column(
            'code', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False
        ),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_lineconnectcode_user_id'),
        'lineconnectcode',
        ['user_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_lineconnectcode_code'),
        'lineconnectcode',
        ['code'],
        unique=True,
    )
    q = _role()
    if q is not None:
        op.execute(f"GRANT DELETE ON lineconnectcode TO {q}")


def downgrade() -> None:
    op.drop_index(
        op.f('ix_lineconnectcode_code'), table_name='lineconnectcode'
    )
    op.drop_index(
        op.f('ix_lineconnectcode_user_id'), table_name='lineconnectcode'
    )
    op.drop_table('lineconnectcode')
    op.drop_constraint('uq_user_line_user_id', 'user', type_='unique')
```

- [ ] **Step 6: Apply and round-trip the migration**

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend alembic downgrade -1
docker compose exec backend alembic upgrade head
```

Expected: all three succeed. The downgrade proves the drop path works before it is ever needed in anger.

- [ ] **Step 7: Run test to verify it passes**

Run: `docker compose exec backend pytest tests/services/test_line_enrollment.py -v`
Expected: 3 passed

- [ ] **Step 8: Commit**

```bash
git add backend/app/models.py backend/app/alembic/versions/c4d5e6f7a8b0_m039_line_enrollment.py \
        backend/tests/services/test_line_enrollment.py
git commit -m "feat(notifications): LineConnectCode table + unique line_user_id (m039)"
```

---

## Task 3: crud functions

**Files:**
- Modify: `backend/app/crud.py` (append after `disconnect_telegram`)
- Test: `backend/tests/services/test_line_enrollment.py` (append)

**Interfaces:**
- Consumes: `LineConnectCode`, `LineConfirmOutcome` from Task 2
- Produces:
  - `create_line_connect_code(*, session: Session, user_id: uuid.UUID) -> LineConnectCode`
  - `confirm_line_connect_code(*, session: Session, code: str, line_user_id: str) -> LineConfirmOutcome` — **no `user` argument**, by design (§1.3)
  - `disconnect_line(*, session: Session, user: User) -> None`
  - `clear_line_user(*, session: Session, line_user_id: str) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/services/test_line_enrollment.py`:

```python
from app import crud
from app.models import LineConfirmOutcome


def test_create_mints_a_128_bit_code(db: Session) -> None:
    user = _user(db)
    record = crud.create_line_connect_code(session=db, user_id=user.id)
    # 32 hex chars == 128 bits. The code is a bearer credential (spec §1.3);
    # shortening it is a security regression, not a cosmetic one.
    assert len(record.code) == 32
    assert all(c in "0123456789abcdef" for c in record.code)
    assert record.consumed_at is None
    assert record.expires_at > get_datetime_utc()


def test_create_reaps_this_users_prior_codes(db: Session) -> None:
    user = _user(db)
    first = crud.create_line_connect_code(session=db, user_id=user.id)
    second = crud.create_line_connect_code(session=db, user_id=user.id)
    remaining = db.exec(
        select(LineConnectCode).where(LineConnectCode.user_id == user.id)
    ).all()
    assert [r.code for r in remaining] == [second.code]
    assert first.code != second.code


def test_create_does_not_reap_another_users_codes(db: Session) -> None:
    mine, theirs = _user(db), _user(db)
    theirs_code = crud.create_line_connect_code(session=db, user_id=theirs.id)
    crud.create_line_connect_code(session=db, user_id=mine.id)
    still_there = db.exec(
        select(LineConnectCode).where(LineConnectCode.code == theirs_code.code)
    ).first()
    assert still_there is not None


def test_confirm_binds_the_line_user_id(db: Session) -> None:
    user = _user(db)
    record = crud.create_line_connect_code(session=db, user_id=user.id)
    line_id = f"U{uuid.uuid4().hex}"
    outcome = crud.confirm_line_connect_code(
        session=db, code=record.code, line_user_id=line_id
    )
    assert outcome is LineConfirmOutcome.CONNECTED
    db.refresh(user)
    assert user.line_user_id == line_id


def test_confirm_is_single_use(db: Session) -> None:
    user = _user(db)
    record = crud.create_line_connect_code(session=db, user_id=user.id)
    crud.confirm_line_connect_code(
        session=db, code=record.code, line_user_id=f"U{uuid.uuid4().hex}"
    )
    second = crud.confirm_line_connect_code(
        session=db, code=record.code, line_user_id=f"U{uuid.uuid4().hex}"
    )
    assert second is LineConfirmOutcome.PENDING


def test_confirm_rejects_an_unknown_code(db: Session) -> None:
    # The LINE analogue of Telegram's "a different user cannot confirm" test,
    # which cannot exist here because the webhook has no session (spec §1.3).
    outcome = crud.confirm_line_connect_code(
        session=db, code=uuid.uuid4().hex, line_user_id=f"U{uuid.uuid4().hex}"
    )
    assert outcome is LineConfirmOutcome.PENDING


def test_confirm_rejects_an_expired_code(db: Session) -> None:
    user = _user(db)
    record = crud.create_line_connect_code(session=db, user_id=user.id)
    record.expires_at = get_datetime_utc() - timedelta(seconds=1)
    db.add(record)
    db.commit()
    outcome = crud.confirm_line_connect_code(
        session=db, code=record.code, line_user_id=f"U{uuid.uuid4().hex}"
    )
    assert outcome is LineConfirmOutcome.PENDING
    db.refresh(user)
    assert user.line_user_id is None


def test_confirm_refuses_a_line_account_bound_elsewhere(db: Session) -> None:
    shared = f"U{uuid.uuid4().hex}"
    _user(db, line_user_id=shared)
    latecomer = _user(db)
    record = crud.create_line_connect_code(session=db, user_id=latecomer.id)
    outcome = crud.confirm_line_connect_code(
        session=db, code=record.code, line_user_id=shared
    )
    assert outcome is LineConfirmOutcome.USER_ALREADY_LINKED
    db.refresh(latecomer)
    assert latecomer.line_user_id is None


def test_a_refused_cross_bind_does_not_consume_the_code(db: Session) -> None:
    # The user can unlink the other account and retry within the TTL, so
    # burning the code here would strand them (spec §1.9).
    shared = f"U{uuid.uuid4().hex}"
    _user(db, line_user_id=shared)
    latecomer = _user(db)
    record = crud.create_line_connect_code(session=db, user_id=latecomer.id)
    crud.confirm_line_connect_code(
        session=db, code=record.code, line_user_id=shared
    )
    db.refresh(record)
    assert record.consumed_at is None


def test_disconnect_clears_only_the_binding(db: Session) -> None:
    user = _user(db, line_user_id=f"U{uuid.uuid4().hex}")
    crud.disconnect_line(session=db, user=user)
    db.refresh(user)
    assert user.line_user_id is None


def test_clear_line_user_unbinds_by_line_id(db: Session) -> None:
    line_id = f"U{uuid.uuid4().hex}"
    user = _user(db, line_user_id=line_id)
    crud.clear_line_user(session=db, line_user_id=line_id)
    db.refresh(user)
    assert user.line_user_id is None


def test_clear_line_user_is_a_no_op_for_an_unknown_id(db: Session) -> None:
    crud.clear_line_user(session=db, line_user_id=f"U{uuid.uuid4().hex}")
```

Add `select` and `LineConnectCode` to the file's imports:

```python
from sqlmodel import Session, select
from app.models import LineConfirmOutcome, LineConnectCode, User, get_datetime_utc
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec backend pytest tests/services/test_line_enrollment.py -v`
Expected: FAIL — `AttributeError: module 'app.crud' has no attribute 'create_line_connect_code'`

- [ ] **Step 3: Implement the crud functions**

Append to `backend/app/crud.py` after `disconnect_telegram`:

```python
def create_line_connect_code(
    *, session: Session, user_id: uuid.UUID
) -> LineConnectCode:
    """Mint a one-time, ~10-minute code for the LINE connect deep link.

    See LineConnectCode's docstring: the LINE webhook has no session, so this
    code alone is the identity. token_hex gives 32 lowercase hex characters --
    128 bits of entropy and exactly the code column's max_length=32.

    Hex is the right charset here for a reason the Telegram version doesn't
    face: this code travels through a URL query string AND is typed into a
    chat message as literal text. [0-9a-f] is unambiguous in both. Do NOT
    switch to token_urlsafe or base64 -- '-', '_', '+', '/' and '=' invite
    either URL-encoding surprises or chat-client autoformatting.

    Mirrors create_telegram_connect_code, including the FOR UPDATE lock and
    the same-transaction reap.
    """
    # Serialize concurrent mints for the same user on their User row: without
    # this, two overlapping connects can each miss the other's not-yet-visible
    # code and leave two live rows. Locking the parent (not the code rows)
    # covers the no-prior-rows case, where there is nothing else to lock.
    session.exec(select(User).where(User.id == user_id).with_for_update()).one()
    # Reap this user's prior codes in the same transaction, so the table stays
    # bounded at ~1 row per user who has ever connected without introducing a
    # scheduler (the stack has none). A superseded code was already unusable
    # the moment this call minted a fresh one.
    for stale in session.exec(
        select(LineConnectCode).where(LineConnectCode.user_id == user_id)
    ).all():
        session.delete(stale)

    record = LineConnectCode(
        user_id=user_id,
        code=secrets.token_hex(16),
        expires_at=get_datetime_utc() + timedelta(minutes=10),
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def confirm_line_connect_code(
    *, session: Session, code: str, line_user_id: str
) -> LineConfirmOutcome:
    """Validate and atomically consume a pending connect code, binding
    `line_user_id` to the user who minted it.

    Takes NO `user` argument, unlike confirm_telegram_connect_code. That is
    not an oversight -- it is the whole security model. The LINE webhook is
    unauthenticated, so there is no current_user to filter on; the code is
    looked up by value alone and whoever presents it gets bound to its owner.
    Everything protecting this reduces to the code's 128 bits, its single use,
    and its 10-minute TTL (spec §1.3).

    FOR UPDATE makes the consumed_at check-then-set atomic against a racing
    second delivery of the same code -- LINE retries webhooks, so this race is
    routine, not theoretical.

    Returns PENDING for anything the caller should silently ignore (no such
    code, expired, already consumed, orphaned owner) and USER_ALREADY_LINKED
    for the one case worth an in-chat explanation.
    """
    record = session.exec(
        select(LineConnectCode)
        .where(LineConnectCode.code == code)
        .with_for_update()
    ).first()
    if record is None or record.consumed_at is not None:
        return LineConfirmOutcome.PENDING
    if record.expires_at < get_datetime_utc():
        return LineConfirmOutcome.PENDING

    user = session.exec(select(User).where(User.id == record.user_id)).first()
    if user is None:
        return LineConfirmOutcome.PENDING

    # Checked up front for a clear answer in the common case; the
    # IntegrityError below still backstops a racing bind between here and
    # commit. Deliberately does NOT consume the code -- the user can unlink
    # the other account and retry within the TTL.
    incumbent = session.exec(
        select(User).where(
            User.line_user_id == line_user_id, User.id != user.id
        )
    ).first()
    if incumbent is not None:
        return LineConfirmOutcome.USER_ALREADY_LINKED

    record.consumed_at = get_datetime_utc()
    session.add(record)
    user.line_user_id = line_user_id
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        # Lost the race: someone bound this LINE account between the check
        # above and the commit. The rollback also discards consumed_at, so the
        # code stays usable if the winner later unlinks.
        session.rollback()
        return LineConfirmOutcome.USER_ALREADY_LINKED
    return LineConfirmOutcome.CONNECTED


def disconnect_line(*, session: Session, user: User) -> None:
    """Clear the binding only. Preferences and notificationlog rows survive --
    the log is append-only and the preferences are the user's settings, not a
    property of the binding."""
    user.line_user_id = None
    session.add(user)
    session.commit()


def clear_line_user(*, session: Session, line_user_id: str) -> None:
    """Unbind by LINE user id rather than by POS user -- the caller is the
    `unfollow` webhook branch, which knows only the LINE side (spec §1.6).

    A no-op for an unknown id: unfollow fires for people who never connected.
    """
    user = session.exec(
        select(User).where(User.line_user_id == line_user_id)
    ).first()
    if user is None:
        return
    user.line_user_id = None
    session.add(user)
    session.commit()
```

Add to `crud.py`'s import from `app.models`: `LineConfirmOutcome`, `LineConnectCode`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec backend pytest tests/services/test_line_enrollment.py -v`
Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/crud.py backend/tests/services/test_line_enrollment.py
git commit -m "feat(notifications): crud for LINE connect codes

confirm_line_connect_code deliberately takes no user argument: the LINE
webhook is unauthenticated, so the code alone is the identity."
```

---

## Task 4: Signature verification and the in-chat reply sender

**Files:**
- Modify: `backend/app/services/notify.py`
- Test: `backend/tests/services/test_line_signature.py` (append)

**Interfaces:**
- Consumes: `settings.LINE_CHANNEL_SECRET`, `settings.LINE_CHANNEL_ACCESS_TOKEN` from Task 1
- Produces:
  - `verify_line_signature(*, body: bytes, signature: str | None) -> bool`
  - `send_line_reply(*, reply_token: str, text: str) -> None`
  - `LINE_REPLY_URL: str`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/services/test_line_signature.py`. **Move these imports
to the top of the file, above the existing `from app.core.config import settings`
line** — ruff's E402 rejects imports after module-level code:

```python
import base64
import hashlib
import hmac
from typing import Any

import httpx
import pytest

from app.core.config import settings
from app.services import notify

SECRET = "test-channel-secret"


def _sign(body: bytes, secret: str = SECRET) -> str:
    return base64.b64encode(
        hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("ascii")


@pytest.fixture
def line_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LINE_CHANNEL_SECRET", SECRET)


def test_valid_signature_is_accepted(line_secret: None) -> None:
    body = b'{"destination":"U123","events":[]}'
    assert notify.verify_line_signature(body=body, signature=_sign(body)) is True


def test_signature_from_a_different_secret_is_rejected(line_secret: None) -> None:
    body = b'{"destination":"U123","events":[]}'
    forged = _sign(body, secret="not-the-secret")
    assert notify.verify_line_signature(body=body, signature=forged) is False


def test_missing_signature_is_rejected(line_secret: None) -> None:
    assert notify.verify_line_signature(body=b"{}", signature=None) is False


def test_tampered_body_is_rejected(line_secret: None) -> None:
    signature = _sign(b'{"events":[]}')
    assert (
        notify.verify_line_signature(body=b'{"events":[1]}', signature=signature)
        is False
    )


def test_unset_secret_rejects_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    # Fail closed. The route returns 503 before reaching here, but a helper
    # that returned True on an unset secret would be a trapdoor if reused.
    monkeypatch.setattr(settings, "LINE_CHANNEL_SECRET", None)
    assert notify.verify_line_signature(body=b"{}", signature="anything") is False


def test_signature_covers_raw_bytes_including_escape_characters(
    line_secret: None,
) -> None:
    # LINE's docs flag this specifically for Python: a body containing \n
    # survives verbatim only if hashed as raw bytes. Parsing and re-serializing
    # changes the byte string and breaks the HMAC (spec §1.5.1).
    body = (
        b'{"destination":"U123","events":[{"type":"message",'
        b'"message":{"type":"text","text":"hello\\ntest1\\ntest2"}}]}'
    )
    assert notify.verify_line_signature(body=body, signature=_sign(body)) is True


def test_send_line_reply_posts_the_reply_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "LINE_CHANNEL_ACCESS_TOKEN", "tok")
    captured: dict[str, Any] = {}

    def fake_post(url: str, *, headers: dict[str, str], json: dict[str, Any]):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return httpx.Response(
            200, json={}, request=httpx.Request("POST", "https://example.test")
        )

    monkeypatch.setattr(notify, "_post", fake_post)
    notify.send_line_reply(reply_token="rt-1", text="hi")

    assert captured["url"] == notify.LINE_REPLY_URL
    assert captured["json"]["replyToken"] == "rt-1"
    assert captured["json"]["messages"] == [{"type": "text", "text": "hi"}]
    assert captured["headers"]["Authorization"] == "Bearer tok"


def test_send_line_reply_without_a_token_is_permanent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "LINE_CHANNEL_ACCESS_TOKEN", None)
    with pytest.raises(notify.PermanentNotifyError):
        notify.send_line_reply(reply_token="rt-1", text="hi")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec backend pytest tests/services/test_line_signature.py -v`
Expected: FAIL — `AttributeError: module 'app.services.notify' has no attribute 'verify_line_signature'`

- [ ] **Step 3: Implement both helpers**

In `backend/app/services/notify.py`, add to the stdlib imports at the top:

```python
import base64
import hashlib
import hmac
```

Next to `LINE_PUSH_URL`:

```python
LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"
```

After `send_line`:

```python
def verify_line_signature(*, body: bytes, signature: str | None) -> bool:
    """Whether `signature` is LINE's HMAC over exactly these body bytes.

    This is the webhook's only trust boundary -- the endpoint is public and
    unauthenticated, so everything downstream trusts this returning True.

    `body` MUST be the raw request bytes, read before any JSON parsing.
    Parsing and re-serializing changes the byte string (escape characters,
    key order, whitespace) and the HMAC will not match. LINE's own docs call
    this out as the most common implementation error.

    Fails closed on an unset secret or a missing header. Uses compare_digest
    so a wrong signature costs the same time as a right one.
    """
    if not settings.LINE_CHANNEL_SECRET or not signature:
        return False
    expected = base64.b64encode(
        hmac.new(
            settings.LINE_CHANNEL_SECRET.encode("utf-8"), body, hashlib.sha256
        ).digest()
    ).decode("ascii")
    return hmac.compare_digest(expected, signature)


def send_line_reply(*, reply_token: str, text: str) -> None:
    """Reply in-chat to a webhook event (single raw attempt).

    Replies are excluded from the subscription plan's message quota -- only
    push, multicast, broadcast and narrowcast are billed -- so confirming the
    connect in-chat is free. It matters because at that moment the user is
    looking at their phone, not necessarily at the browser that started the
    flow.

    A reply token is single-use and short-lived; there is no point retrying a
    failed reply later, which is why the caller treats this as best-effort.
    """
    if not settings.LINE_CHANNEL_ACCESS_TOKEN:
        raise PermanentNotifyError("LINE_TOKEN not configured")
    try:
        response = _post(
            LINE_REPLY_URL,
            headers={
                "Authorization": f"Bearer {settings.LINE_CHANNEL_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                "replyToken": reply_token,
                "messages": [{"type": "text", "text": text}],
            },
        )
    except httpx.TransportError as exc:
        raise RetryableNotifyError("transport error") from exc
    _classify(response)
```

Add `from app.core.config import settings` if not already imported (it is — `send_line` uses it).

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec backend pytest tests/services/test_line_signature.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/notify.py backend/tests/services/test_line_signature.py
git commit -m "feat(notifications): LINE webhook signature verification + reply sender

Signature is computed over raw request bytes with stdlib hmac; no
line-bot-sdk dependency for six lines of HMAC."
```

---

## Task 5: Connect and disconnect routes

**Files:**
- Modify: `backend/app/api/routes/notifications.py` (append; modify nothing existing)
- Create: `backend/tests/api/routes/test_line_connect.py`

**Interfaces:**
- Consumes: `crud.create_line_connect_code`, `crud.disconnect_line`, `LineConnectResponse`, `LINE_CONNECT_RATE_LIMIT`, `render_qr_png_data_uri`
- Produces: `POST /api/v1/notifications/line/connect` → `LineConnectResponse`; `DELETE /api/v1/notifications/line/disconnect` → `Message`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/api/routes/test_line_connect.py`:

```python
"""Route tests for the LINE self-service connect flow (spec §1.4).

No real HTTP happens -- these routes make no outbound calls at all. The
webhook side lives in test_line_webhook.py.
"""

import re
import uuid
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.core.limiter import limiter
from app.models import LineConnectCode, User
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import random_email

PREFIX = settings.API_V1_STR
BASIC_ID = "@097shucy"


@pytest.fixture
def user_and_headers(client: TestClient, db: Session) -> tuple[User, dict[str, str]]:
    email = random_email()
    headers = authentication_token_from_email(client=client, email=email, db=db)
    user = crud.get_user_by_email(session=db, email=email)
    assert user is not None
    return user, headers


@pytest.fixture
def line_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LINE_BOT_BASIC_ID", BASIC_ID)
    monkeypatch.setattr(settings, "LINE_CHANNEL_SECRET", "secret")
    monkeypatch.setattr(settings, "LINE_CHANNEL_ACCESS_TOKEN", "token")


def test_connect_mints_a_code_and_deep_link(
    client: TestClient,
    line_configured: None,
    user_and_headers: tuple[User, dict[str, str]],
) -> None:
    _, headers = user_and_headers
    r = client.post(f"{PREFIX}/notifications/line/connect", headers=headers)
    assert r.status_code == 200
    body = r.json()
    # 32 hex chars == 128 bits: the code is a bearer credential (spec §1.3).
    assert re.fullmatch(r"[0-9a-f]{32}", body["code"])
    assert body["qr_code_data_uri"].startswith("data:image/png;base64,")
    assert body["expires_at"]


def test_deep_link_percent_encodes_the_basic_id(
    client: TestClient,
    line_configured: None,
    user_and_headers: tuple[User, dict[str, str]],
) -> None:
    # An unencoded '@' works but is deprecated by LINE. The deep link is the
    # entire enrollment entry point -- if it is malformed nothing else runs.
    _, headers = user_and_headers
    r = client.post(f"{PREFIX}/notifications/line/connect", headers=headers)
    body = r.json()
    assert body["deep_link"] == (
        f"https://line.me/R/oaMessage/{quote(BASIC_ID, safe='')}/?{body['code']}"
    )
    assert "%40097shucy" in body["deep_link"]
    assert "@" not in body["deep_link"]


def test_connect_without_configuration_is_a_400(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    user_and_headers: tuple[User, dict[str, str]],
) -> None:
    monkeypatch.setattr(settings, "LINE_BOT_BASIC_ID", None)
    _, headers = user_and_headers
    r = client.post(f"{PREFIX}/notifications/line/connect", headers=headers)
    assert r.status_code == 400
    assert "not configured" in r.json()["detail"].lower()


def test_connect_requires_authentication(
    client: TestClient, line_configured: None
) -> None:
    r = client.post(f"{PREFIX}/notifications/line/connect")
    assert r.status_code == 401


def test_connect_reaps_only_this_users_codes(
    client: TestClient,
    db: Session,
    line_configured: None,
    user_and_headers: tuple[User, dict[str, str]],
) -> None:
    user, headers = user_and_headers
    other = User(email=random_email(), hashed_password="x")
    db.add(other)
    db.commit()
    db.refresh(other)
    theirs = crud.create_line_connect_code(session=db, user_id=other.id)

    client.post(f"{PREFIX}/notifications/line/connect", headers=headers)
    client.post(f"{PREFIX}/notifications/line/connect", headers=headers)

    mine = db.exec(
        select(LineConnectCode).where(LineConnectCode.user_id == user.id)
    ).all()
    assert len(mine) == 1
    survived = db.exec(
        select(LineConnectCode).where(LineConnectCode.code == theirs.code)
    ).first()
    assert survived is not None


def test_disconnect_clears_the_binding_and_is_idempotent(
    client: TestClient,
    db: Session,
    user_and_headers: tuple[User, dict[str, str]],
) -> None:
    user, headers = user_and_headers
    user.line_user_id = f"U{uuid.uuid4().hex}"
    db.add(user)
    db.commit()

    first = client.delete(
        f"{PREFIX}/notifications/line/disconnect", headers=headers
    )
    assert first.status_code == 200
    db.refresh(user)
    assert user.line_user_id is None

    second = client.delete(
        f"{PREFIX}/notifications/line/disconnect", headers=headers
    )
    assert second.status_code == 200


def test_disconnect_requires_authentication(client: TestClient) -> None:
    r = client.delete(f"{PREFIX}/notifications/line/disconnect")
    assert r.status_code == 401


def test_disconnect_does_not_affect_another_user(
    client: TestClient,
    db: Session,
    user_and_headers: tuple[User, dict[str, str]],
) -> None:
    _, headers = user_and_headers
    other_id = f"U{uuid.uuid4().hex}"
    other = User(
        email=random_email(), hashed_password="x", line_user_id=other_id
    )
    db.add(other)
    db.commit()
    db.refresh(other)

    client.delete(f"{PREFIX}/notifications/line/disconnect", headers=headers)

    db.refresh(other)
    assert other.line_user_id == other_id


def test_connect_is_rate_limited(
    client: TestClient,
    line_configured: None,
    user_and_headers: tuple[User, dict[str, str]],
) -> None:
    _, headers = user_and_headers
    limiter.reset()
    statuses = [
        client.post(
            f"{PREFIX}/notifications/line/connect", headers=headers
        ).status_code
        for _ in range(21)
    ]
    assert 429 in statuses
    limiter.reset()


def test_one_users_rate_limit_does_not_block_another(
    client: TestClient,
    db: Session,
    line_configured: None,
    user_and_headers: tuple[User, dict[str, str]],
) -> None:
    # The half that actually proves per-user keying. Both users share one
    # source IP in the test client, so if the bucket were IP-keyed the second
    # user would be locked out by the first user's spending -- which is
    # exactly review finding M1 on /telegram/test, and the reason this route
    # carries Depends(bind_rate_limit_identity) + key_func=user_or_remote_address.
    # A shop where every till sits behind one public IP would otherwise get
    # one shared 20/hour bucket for the whole staff.
    _, headers = user_and_headers
    limiter.reset()
    for _ in range(21):
        client.post(f"{PREFIX}/notifications/line/connect", headers=headers)

    other_email = random_email()
    other_headers = authentication_token_from_email(
        client=client, email=other_email, db=db
    )
    r = client.post(
        f"{PREFIX}/notifications/line/connect", headers=other_headers
    )
    assert r.status_code == 200
    limiter.reset()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec backend pytest tests/api/routes/test_line_connect.py -v`
Expected: FAIL — 404s (routes don't exist).

- [ ] **Step 3: Implement the routes**

Append to `backend/app/api/routes/notifications.py`:

```python
@router.post(
    "/line/connect",
    response_model=LineConnectResponse,
    dependencies=[Depends(bind_rate_limit_identity)],
)
@limiter.limit(LINE_CONNECT_RATE_LIMIT, key_func=user_or_remote_address)
def connect_line(
    *,
    request: Request,  # noqa: ARG001 — required by slowapi's rate-limit decorator
    session: SessionDep,
    current_user: CurrentUser,
) -> LineConnectResponse:
    """Mint a one-time code + a line.me deep link that opens a chat with the
    Official Account and pre-types the code, so the user only taps send.

    A plain add-friend link would fire a `follow` event carrying userId but no
    code, which cannot identify which POS user connected -- hence the
    prefilled-message round trip (spec §2).

    Re-runnable: calling again mints a fresh code, so switching LINE accounts
    is one more tap, not a dead end.
    """
    if not settings.LINE_BOT_BASIC_ID:
        raise HTTPException(status_code=400, detail="LINE is not configured")
    record = crud.create_line_connect_code(session=session, user_id=current_user.id)
    # Percent-encode the basic ID: an unencoded '@' works but LINE deprecates
    # it. The code is [0-9a-f] so it needs no encoding, but quote() it anyway
    # rather than relying on that invariant holding forever.
    deep_link = (
        f"https://line.me/R/oaMessage/{quote(settings.LINE_BOT_BASIC_ID, safe='')}"
        f"/?{quote(record.code, safe='')}"
    )
    return LineConnectResponse(
        code=record.code,
        deep_link=deep_link,
        qr_code_data_uri=render_qr_png_data_uri(deep_link),
        expires_at=record.expires_at,
    )


@router.delete("/line/disconnect", response_model=Message)
def disconnect_line(*, session: SessionDep, current_user: CurrentUser) -> Message:
    crud.disconnect_line(session=session, user=current_user)
    return Message(message="LINE disconnected")
```

Update the file's imports:

```python
from urllib.parse import quote

from app.core.limiter import (
    LINE_CONNECT_RATE_LIMIT,
    TELEGRAM_CONFIRM_RATE_LIMIT,
    TELEGRAM_CONNECT_RATE_LIMIT,
    TELEGRAM_TEST_RATE_LIMIT,
    limiter,
    user_or_remote_address,
)
from app.models import (
    LineConnectResponse,
    Message,
    ...
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec backend pytest tests/api/routes/test_line_connect.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/notifications.py backend/tests/api/routes/test_line_connect.py
git commit -m "feat(notifications): LINE connect + disconnect routes"
```

---

## Task 6: The webhook

The only new attack surface. Order of operations inside the handler is load-bearing.

**Files:**
- Modify: `backend/app/api/routes/notifications.py` (append)
- Create: `backend/tests/api/routes/test_line_webhook.py`

**Interfaces:**
- Consumes: `notify.verify_line_signature`, `notify.send_line_reply`, `crud.confirm_line_connect_code`, `crud.clear_line_user`, `LineConfirmOutcome`
- Produces: `POST /api/v1/notifications/line/webhook` → `Message`, unauthenticated

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/api/routes/test_line_webhook.py`:

```python
"""Route tests for the LINE webhook (spec §1.5).

This endpoint is public and unauthenticated -- its only gate is the HMAC
signature -- so the signature tests here are the security regression suite,
not a formality. notify.send_line_reply is monkeypatched throughout; no real
HTTP happens.
"""

import base64
import hashlib
import hmac
import json
import logging
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.models import User, get_datetime_utc
from app.services import notify
from tests.utils.utils import random_email

PREFIX = settings.API_V1_STR
SECRET = "test-channel-secret"
URL = f"{PREFIX}/notifications/line/webhook"


@pytest.fixture(autouse=True)
def line_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LINE_CHANNEL_SECRET", SECRET)
    monkeypatch.setattr(settings, "LINE_CHANNEL_ACCESS_TOKEN", "token")


@pytest.fixture
def replies(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    sent: list[dict[str, str]] = []

    def fake_reply(*, reply_token: str, text: str) -> None:
        sent.append({"reply_token": reply_token, "text": text})

    monkeypatch.setattr(notify, "send_line_reply", fake_reply)
    return sent


def _user(db: Session, line_user_id: str | None = None) -> User:
    user = User(
        email=random_email(), hashed_password="x", line_user_id=line_user_id
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _post(client: TestClient, payload: dict[str, Any], *, secret: str = SECRET):
    body = json.dumps(payload).encode("utf-8")
    signature = base64.b64encode(
        hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("ascii")
    return client.post(
        URL,
        content=body,
        headers={
            "x-line-signature": signature,
            "Content-Type": "application/json",
        },
    )


def _message_event(text: str, line_user_id: str, reply_token: str = "rt-1"):
    return {
        "type": "message",
        "replyToken": reply_token,
        "source": {"type": "user", "userId": line_user_id},
        "message": {"type": "text", "text": text},
    }


# --- signature ------------------------------------------------------------


def test_valid_signature_is_accepted(client: TestClient, replies: list) -> None:
    r = _post(client, {"destination": "U1", "events": []})
    assert r.status_code == 200


def test_invalid_signature_is_rejected(client: TestClient, db: Session) -> None:
    user = _user(db)
    record = crud.create_line_connect_code(session=db, user_id=user.id)
    line_id = f"U{uuid.uuid4().hex}"
    r = _post(
        client,
        {"events": [_message_event(record.code, line_id)]},
        secret="wrong-secret",
    )
    assert r.status_code == 400
    db.refresh(user)
    assert user.line_user_id is None


def test_missing_signature_header_is_rejected(client: TestClient) -> None:
    r = client.post(URL, content=b'{"events":[]}')
    assert r.status_code == 400


def test_unset_secret_fails_closed_with_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "LINE_CHANNEL_SECRET", None)
    r = _post(client, {"events": []})
    assert r.status_code == 503


def test_body_is_never_logged(
    client: TestClient, db: Session, replies: list, caplog: pytest.LogCaptureFixture
) -> None:
    # The body carries LINE userIds. Same discipline as the Telegram bot
    # token (spec §1.5.7).
    user = _user(db)
    record = crud.create_line_connect_code(session=db, user_id=user.id)
    line_id = f"U{uuid.uuid4().hex}"
    with caplog.at_level(logging.DEBUG):
        _post(client, {"events": [_message_event(record.code, line_id)]})
    combined = "\n".join(r.getMessage() for r in caplog.records)
    assert line_id not in combined
    assert record.code not in combined


# --- binding --------------------------------------------------------------


def test_happy_path_binds_the_line_user_id(
    client: TestClient, db: Session, replies: list
) -> None:
    user = _user(db)
    record = crud.create_line_connect_code(session=db, user_id=user.id)
    line_id = f"U{uuid.uuid4().hex}"
    r = _post(client, {"events": [_message_event(record.code, line_id)]})
    assert r.status_code == 200
    db.refresh(user)
    assert user.line_user_id == line_id
    assert replies and replies[0]["reply_token"] == "rt-1"


def test_a_forged_code_binds_nobody(
    client: TestClient, db: Session, replies: list
) -> None:
    user = _user(db)
    crud.create_line_connect_code(session=db, user_id=user.id)
    r = _post(
        client,
        {"events": [_message_event(uuid.uuid4().hex, f"U{uuid.uuid4().hex}")]},
    )
    assert r.status_code == 200
    db.refresh(user)
    assert user.line_user_id is None
    assert replies == []


def test_a_consumed_code_does_not_bind_twice(
    client: TestClient, db: Session, replies: list
) -> None:
    # LINE redelivers webhooks; this replay path is routine, not theoretical.
    first_user = _user(db)
    record = crud.create_line_connect_code(session=db, user_id=first_user.id)
    _post(client, {"events": [_message_event(record.code, f"U{uuid.uuid4().hex}")]})

    second_id = f"U{uuid.uuid4().hex}"
    r = _post(client, {"events": [_message_event(record.code, second_id)]})
    assert r.status_code == 200
    db.refresh(first_user)
    assert first_user.line_user_id != second_id


def test_a_group_source_never_binds(
    client: TestClient, db: Session, replies: list
) -> None:
    # Binding a group id would deliver a user's stock and pricing alerts into
    # a group chat (spec §1.5.4).
    user = _user(db)
    record = crud.create_line_connect_code(session=db, user_id=user.id)
    event = _message_event(record.code, f"U{uuid.uuid4().hex}")
    event["source"] = {"type": "group", "groupId": "G123"}
    r = _post(client, {"events": [event]})
    assert r.status_code == 200
    db.refresh(user)
    assert user.line_user_id is None


def test_two_events_in_one_post_are_both_processed(
    client: TestClient, db: Session, replies: list
) -> None:
    first, second = _user(db), _user(db)
    code_one = crud.create_line_connect_code(session=db, user_id=first.id)
    code_two = crud.create_line_connect_code(session=db, user_id=second.id)
    id_one, id_two = f"U{uuid.uuid4().hex}", f"U{uuid.uuid4().hex}"
    r = _post(
        client,
        {
            "events": [
                _message_event(code_one.code, id_one, reply_token="rt-a"),
                _message_event(code_two.code, id_two, reply_token="rt-b"),
            ]
        },
    )
    assert r.status_code == 200
    db.refresh(first)
    db.refresh(second)
    assert first.line_user_id == id_one
    assert second.line_user_id == id_two


def test_non_message_events_are_ignored_but_still_200(
    client: TestClient, replies: list
) -> None:
    # A non-200 makes LINE retry and eventually disable the webhook entirely
    # (spec §1.5.3), which would break enrollment for everyone.
    for event_type in ("follow", "join", "leave", "postback"):
        r = _post(
            client,
            {
                "events": [
                    {
                        "type": event_type,
                        "replyToken": "rt-x",
                        "source": {"type": "user", "userId": "U999"},
                    }
                ]
            },
        )
        assert r.status_code == 200, event_type
    assert replies == []


def test_a_sticker_message_is_ignored(client: TestClient, replies: list) -> None:
    event = {
        "type": "message",
        "replyToken": "rt-1",
        "source": {"type": "user", "userId": "U999"},
        "message": {"type": "sticker", "packageId": "1"},
    }
    r = _post(client, {"events": [event]})
    assert r.status_code == 200
    assert replies == []


def test_a_cross_bound_line_account_is_refused_and_told_why(
    client: TestClient, db: Session, replies: list
) -> None:
    shared = f"U{uuid.uuid4().hex}"
    _user(db, line_user_id=shared)
    latecomer = _user(db)
    record = crud.create_line_connect_code(session=db, user_id=latecomer.id)

    r = _post(client, {"events": [_message_event(record.code, shared)]})
    assert r.status_code == 200
    db.refresh(latecomer)
    assert latecomer.line_user_id is None
    assert replies and "already connected" in replies[0]["text"].lower()


def test_a_failed_reply_does_not_roll_back_the_bind(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The reply is best-effort, like notify() (spec §1.9).
    def boom(*, reply_token: str, text: str) -> None:
        raise notify.PermanentNotifyError("HTTP 400")

    monkeypatch.setattr(notify, "send_line_reply", boom)
    user = _user(db)
    record = crud.create_line_connect_code(session=db, user_id=user.id)
    line_id = f"U{uuid.uuid4().hex}"
    r = _post(client, {"events": [_message_event(record.code, line_id)]})
    assert r.status_code == 200
    db.refresh(user)
    assert user.line_user_id == line_id


# --- unfollow -------------------------------------------------------------


def test_unfollow_clears_the_binding(
    client: TestClient, db: Session, replies: list
) -> None:
    # send_line reports SENT even when the user has blocked the Official
    # Account -- LINE returns 200 regardless. Clearing on unfollow turns that
    # silent failure into an accurate "Not connected" (spec §1.6 / finding H1).
    line_id = f"U{uuid.uuid4().hex}"
    user = _user(db, line_user_id=line_id)
    r = _post(
        client,
        {
            "events": [
                {"type": "unfollow", "source": {"type": "user", "userId": line_id}}
            ]
        },
    )
    assert r.status_code == 200
    db.refresh(user)
    assert user.line_user_id is None


def test_unfollow_for_an_unknown_user_is_a_no_op(
    client: TestClient, replies: list
) -> None:
    r = _post(
        client,
        {
            "events": [
                {
                    "type": "unfollow",
                    "source": {"type": "user", "userId": f"U{uuid.uuid4().hex}"},
                }
            ]
        },
    )
    assert r.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec backend pytest tests/api/routes/test_line_webhook.py -v`
Expected: FAIL — 404s.

- [ ] **Step 3: Implement the webhook**

Append to `backend/app/api/routes/notifications.py`:

```python
def _handle_line_event(*, session: Session, event: dict[str, Any]) -> None:
    """Process one webhook event. Never raises: the caller must return 200
    even for events it ignores (spec §1.5.3).

    Binds only on a text message from an individual user. A group or room
    source is ignored outright -- binding a group id would deliver a user's
    stock and pricing alerts into a group chat.
    """
    source = event.get("source") or {}
    line_user_id = source.get("userId")
    if source.get("type") != "user" or not line_user_id:
        return

    if event.get("type") == "unfollow":
        # The user blocked or removed the Official Account, so send_line can
        # no longer reach them -- but LINE returns 200 for pushes to a blocked
        # recipient, so nothing else would ever notice (spec §1.6).
        crud.clear_line_user(session=session, line_user_id=line_user_id)
        return

    if event.get("type") != "message":
        return
    message = event.get("message") or {}
    if message.get("type") != "text":
        return

    code = (message.get("text") or "").strip()
    outcome = crud.confirm_line_connect_code(
        session=session, code=code, line_user_id=line_user_id
    )

    reply_token = event.get("replyToken")
    if not reply_token:
        return
    if outcome is LineConfirmOutcome.CONNECTED:
        text = "✅ CastraNova POS\nYour LINE account is now connected."
    elif outcome is LineConfirmOutcome.USER_ALREADY_LINKED:
        text = (
            "This LINE account is already connected to another CastraNova "
            "user. Disconnect it there first, then try again."
        )
    else:
        # PENDING: someone messaged the Official Account without a live code.
        # Staying silent is deliberate -- replying "invalid code" to arbitrary
        # text would confirm to a guesser that codes exist to be guessed.
        return

    try:
        notify.send_line_reply(reply_token=reply_token, text=text)
    except (notify.RetryableNotifyError, notify.PermanentNotifyError):
        # Best-effort, exactly like notify(): the bind already committed and
        # must not be rolled back because a courtesy message failed. Reply
        # tokens are single-use and short-lived, so there is nothing to retry.
        pass


@router.post("/line/webhook", response_model=Message)
async def line_webhook(*, request: Request, session: SessionDep) -> Message:
    """Receive LINE Messaging API events. Public and unauthenticated.

    The signature is the only gate, and it is deliberately the only gate:
    there is no rate limiter here because LINE posts from shared, rotating
    IPs, so an IP-keyed cap would drop legitimate events (spec §1.5).

    Async purely to read the raw body -- the handler itself is sync DB work.
    """
    if not settings.LINE_CHANNEL_SECRET:
        raise HTTPException(status_code=503, detail="LINE is not configured")

    # Raw bytes, before any parsing. Verifying a re-serialized dict breaks the
    # HMAC -- this ordering is the whole point (spec §1.5.1).
    body = await request.body()
    if not notify.verify_line_signature(
        body=body, signature=request.headers.get("x-line-signature")
    ):
        raise HTTPException(status_code=400, detail="invalid signature")

    try:
        payload = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid body") from None

    events = payload.get("events")
    if isinstance(events, list):
        for event in events:
            if isinstance(event, dict):
                # This route must be async to await the raw body, but the
                # handler is blocking DB work. Calling it directly would stall
                # the event loop for every other request in flight; every
                # other route in this file is sync and gets a worker thread
                # from FastAPI automatically. run_in_threadpool restores that.
                await run_in_threadpool(
                    _handle_line_event, session=session, event=event
                )

    # Always 200 past the signature gate, including for ignored events: a
    # non-200 makes LINE retry and eventually disable the webhook.
    return Message(message="ok")
```

Update the file's imports:

```python
import json
from typing import Any
from urllib.parse import quote

from starlette.concurrency import run_in_threadpool
from sqlmodel import Session

from app.models import (
    LineConfirmOutcome,
    LineConnectResponse,
    Message,
    ...
)
```

Events are handled sequentially, not concurrently, on purpose: two events in
one POST can touch the same `Session`, which is not thread-safe.

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec backend pytest tests/api/routes/test_line_webhook.py -v`
Expected: 16 passed

- [ ] **Step 5: Verify no Telegram regression**

Run: `docker compose exec backend pytest tests/api/routes/test_telegram_connect.py tests/services/test_telegram_enrollment.py -v`
Expected: 36 passed — the same as before this branch. Any failure means a shared file was modified when it shouldn't have been.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/notifications.py backend/tests/api/routes/test_line_webhook.py
git commit -m "feat(notifications): LINE webhook with HMAC signature gate

Public unauthenticated endpoint. Signature verified over raw body bytes
before parsing; always 200 past the gate so LINE never disables the
webhook; unfollow clears the binding (review finding H1)."
```

---

## Task 7: Frontend connect card

**Files:**
- Create: `frontend/src/components/notifications/LineConnectCard.tsx`
- Modify: `frontend/src/routes/_layout/notifications.tsx`
- Regenerate: `frontend/src/client/` (never hand-edit)

**Interfaces:**
- Consumes: `NotificationsService.connectLine()`, `NotificationsService.disconnectLine()`, `NotificationsService.readNotificationPreferences()`
- Produces: `<LineConnectCard />`

- [ ] **Step 1: Regenerate the SDK**

```bash
cd frontend && bun run generate-client
```

Verify `connectLine` and `disconnectLine` now exist:

```bash
grep -n "connectLine\|disconnectLine" frontend/src/client/sdk.gen.ts
```

Expected: both present. If not, the backend OpenAPI didn't pick up the routes — restart the backend container.

- [ ] **Step 2: Write the card**

Create `frontend/src/components/notifications/LineConnectCard.tsx`:

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useState } from "react"

import { NotificationsService } from "@/client"
import { Button } from "@/components/ui/button"
import useCustomToast from "@/hooks/useCustomToast"

const POLL_INTERVAL_MS = 3_000
// The server-side code TTL is ~10 min; this is a shorter client-side give-up
// so the UI doesn't poll silently forever if the user never sends the code.
const POLL_TIMEOUT_MS = 2 * 60 * 1_000

/** LINE connect/reconnect card.
 *
 * Deliberately has no dedicated status endpoint. The preference grid's
 * `channel_connected` flag already reports exactly whether line_user_id is
 * set, and this card has to refetch that query on success anyway -- so it
 * polls the query it was going to invalidate. That is also what keeps this
 * feature from touching any Telegram file.
 *
 * Not a refactor of TelegramConnectCard: that is the change most likely to
 * regress the working Telegram flow, and it would buy little -- there is no
 * confirm poll, no username display and no already-linked branch here. */
export function LineConnectCard() {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()

  const [polling, setPolling] = useState(false)
  const [pollStartedAt, setPollStartedAt] = useState<number | null>(null)
  const [pollTimedOut, setPollTimedOut] = useState(false)

  const { data: preferences } = useQuery({
    queryKey: ["notification-preferences"],
    queryFn: () => NotificationsService.readNotificationPreferences(),
    refetchInterval: polling ? POLL_INTERVAL_MS : false,
  })

  const connected =
    preferences?.some((p) => p.channel === "LINE" && p.channel_connected) ??
    false

  const connectMutation = useMutation({
    mutationFn: () => NotificationsService.connectLine(),
    onSuccess: () => {
      setPolling(true)
      setPollStartedAt(Date.now())
      setPollTimedOut(false)
    },
    onError: () => showErrorToast("Could not start connecting LINE. Try again."),
  })

  // Connected: stop polling and celebrate. The grid query is already fresh --
  // it is what told us -- so there is nothing to invalidate.
  useEffect(() => {
    if (!polling || !connected) return
    setPolling(false)
    setPollStartedAt(null)
    showSuccessToast("LINE connected.")
  }, [polling, connected, showSuccessToast])

  // Give up client-side so the card doesn't poll forever if the user never
  // sends the code.
  useEffect(() => {
    if (pollStartedAt === null) return
    const remaining = POLL_TIMEOUT_MS - (Date.now() - pollStartedAt)
    const giveUp = () => {
      setPollTimedOut(true)
      setPolling(false)
      setPollStartedAt(null)
    }
    if (remaining <= 0) {
      giveUp()
      return
    }
    const timer = setTimeout(giveUp, remaining)
    return () => clearTimeout(timer)
  }, [pollStartedAt])

  const disconnectMutation = useMutation({
    mutationFn: () => NotificationsService.disconnectLine(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notification-preferences"] })
      showSuccessToast("LINE disconnected.")
    },
    onError: () => showErrorToast("Could not disconnect LINE. Try again."),
  })

  const connectData = connectMutation.data

  return (
    <div className="bg-card flex flex-col gap-4 rounded-lg border p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium">LINE</p>
          <p className="text-muted-foreground text-sm">
            {connected ? "Connected." : "Not connected."}
          </p>
        </div>
        <div className="flex gap-2">
          {connected && (
            <Button
              variant="destructive"
              onClick={() => disconnectMutation.mutate()}
              disabled={disconnectMutation.isPending}
            >
              {disconnectMutation.isPending ? "Disconnecting…" : "Disconnect"}
            </Button>
          )}
          <Button
            variant={connected ? "outline" : "default"}
            onClick={() => connectMutation.mutate()}
            disabled={connectMutation.isPending || polling}
          >
            {connected ? "Reconnect" : "Connect LINE"}
          </Button>
        </div>
      </div>

      {polling && connectData && (
        <div className="flex flex-col items-center gap-3 border-t pt-4 sm:flex-row sm:items-start">
          <img
            src={connectData.qr_code_data_uri}
            alt="Scan to connect LINE"
            className="size-40 rounded border"
          />
          <div className="flex flex-col gap-2">
            <p className="text-sm">
              Scan the QR code, or open this link on your phone:
            </p>
            <a
              href={connectData.deep_link}
              target="_blank"
              rel="noreferrer"
              className="text-primary text-sm break-all underline"
            >
              {connectData.deep_link}
            </a>
            <p className="text-muted-foreground text-xs">
              LINE opens with the code already typed — just tap send. This
              updates automatically once you do.
            </p>
          </div>
        </div>
      )}

      {pollTimedOut && (
        <p className="text-muted-foreground text-sm">
          Didn't detect a connection — tap Reconnect to try again.
        </p>
      )}
    </div>
  )
}
```

- [ ] **Step 3: Render it**

In `frontend/src/routes/_layout/notifications.tsx`, add the import and render it below `<TelegramConnectCard />`:

```tsx
import { LineConnectCard } from "@/components/notifications/LineConnectCard"
```

```tsx
        <TelegramConnectCard />
        <LineConnectCard />
```

- [ ] **Step 4: Typecheck and lint**

```bash
cd frontend && bunx tsc --noEmit -p tsconfig.json && bunx biome check src/components/notifications/LineConnectCard.tsx src/routes/_layout/notifications.tsx
```

Expected: no errors. Do **not** run `biome check` across the whole repo — it churns unrelated files cosmetically.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/notifications/LineConnectCard.tsx \
        frontend/src/routes/_layout/notifications.tsx frontend/src/client
git commit -m "feat(notifications): LINE connect card

Polls the preference grid's channel_connected flag rather than adding a
status endpoint -- it had to refetch that query on success anyway."
```

---

## Task 8: Documentation and full verification sweep

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/superpowers/specs/2026-08-10-line-enrollment-design.md` (Known Issues only)

- [ ] **Step 1: Update the project status**

In `CLAUDE.md`, replace the sentence reading "LINE has a working sender but still no enrollment path; design in …":

```markdown
- **LINE self-enrollment shipped** (m039): a one-time code + `line.me/R/oaMessage`
  deep link binds a user's LINE account via a signed webhook
  (`POST /notifications/line/webhook`, HMAC-SHA256 over the raw body — the only
  auth on a public endpoint). `unfollow` clears the binding, which is the
  partial fix for LINE reporting `SENT` on pushes to users who blocked the
  Official Account. Requires `LINE_CHANNEL_SECRET` + `LINE_BOT_BASIC_ID`
  alongside the existing `LINE_CHANNEL_ACCESS_TOKEN`, all three threaded
  through `compose.dokploy.yml`.
```

Update the Alembic head line to `m039` (`c4d5e6f7a8b0`).

- [ ] **Step 2: Record the accepted gap**

In the spec's §4 Known issues, confirm the H1-partial entry still reads correctly now that `unfollow` is implemented. It should: a user who blocks the Official Account without unfollowing, or deletes their account, still yields a false `SENT`. Leave it.

- [ ] **Step 3: Run the whole backend suite**

Run: `docker compose exec backend pytest -q`

Expected: the 3 known-failing tests on `dev` (2 stale redaction sweeps + the July-2026 date-dependent report test) and nothing else new. **Diff the failure names against the known list — do not compare counts**, since this branch adds tests.

- [ ] **Step 4: Verify the container actually has the new code**

```bash
docker compose exec backend grep -c "verify_line_signature" app/services/notify.py
```

Expected: `2` or more. `docker compose up` serves stale code — a green suite against an image without your symbol is a false green.

- [ ] **Step 5: Run the Playwright suite**

```bash
cd frontend && E2E_SKIP_DB_RESET=1 bun run test
```

Expected: 253 passed / 17 failed — the 17 are the pre-existing auth-flow specs. Any 18th failure is yours.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-08-10-line-enrollment-design.md
git commit -m "docs(notifications): record LINE enrollment as shipped"
```

- [ ] **Step 7: High-risk review gate**

This adds a public unauthenticated auth boundary, so per CLAUDE.md run **all three**:

```
Agent: ecc:security-reviewer   — the webhook signature gate, the bearer-code model, the reply path
Agent: ecc:database-reviewer   — m039, the UNIQUE constraint, the FOR UPDATE consume, the DELETE grant
Skill: superpowers:requesting-code-review
```

Do not open the PR until these pass.

---

## Post-merge operator steps (not code — do not attempt from this session)

1. Add `LINE_CHANNEL_ACCESS_TOKEN`, `LINE_CHANNEL_SECRET`, `LINE_BOT_BASIC_ID` to Dokploy → CastraNova → castranova-pos → Environment.
2. Merge to `dev`; Dokploy auto-deploys and `prestart` runs `alembic upgrade head`.
3. Press **Verify** in the LINE Developers Console against
   `https://castranova-api.nexuslab.asia/api/v1/notifications/line/webhook`.
   It sends `{"destination":"…","events":[]}` with a valid signature and expects 200.
4. Real phone: Connect → scan → send → card flips → Disconnect → block the OA → card returns to Not connected.
5. **Reissue the channel secret** (it was exposed in a setup screenshot) and update the Dokploy env.
