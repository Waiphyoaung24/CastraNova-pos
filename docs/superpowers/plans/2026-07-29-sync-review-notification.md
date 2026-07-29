# Sync-Review Pending Notification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Push a Telegram/LINE/Viber alert to BKK admins when an offline mutation lands in the sync-review queue, instead of leaving them to discover it by visiting the page.

**Architecture:** A fifth `NotificationEvent` rides the existing FR-018 fan-out. The ingest route queues a `BackgroundTasks` producer that counts the PENDING queue, drops any admin notified in the last 5 minutes, and delegates to the shipped `notify()`. No new channel, no scheduler, no client change.

**Tech Stack:** FastAPI, SQLModel, Alembic, PostgreSQL, pytest. Frontend is SDK-regeneration only.

**Spec:** `docs/superpowers/specs/2026-07-29-sync-review-notification-design.md`

## Global Constraints

- **Alembic head is `m033` (`e5f6a7b8c9d0`).** The new migration is `m034`, revision `f6a7b8c9d0e1`, `down_revision = 'e5f6a7b8c9d0'`.
- **mypy strict is on.** Annotate every parameter and return type. No bare `Any` where a concrete type exists.
- **Routes never run SQL.** All DB reads/writes go through `crud.py`. The one exception already in `notify.py` — it selects `User` / `NotificationPreference` directly — is the established pattern for the service layer, and the cooldown query follows it.
- **Never put a `payload` field in message text.** `SyncReviewItem.payload` is the raw held mutation and carries prices. Counts only. `notify.py:474` states the rule.
- **Lint/format:** ruff + mypy via `prek`. Must pass before each commit.
- **Never run `generate-client` inside the frontend container** — it regenerates from a stale image-baked `openapi.json` and silently drops fields. Run it on the host.
- **Do not reset the dev database.** No `E2E_SKIP_DB_RESET` runs are needed for this plan; it is backend-only plus an SDK regen.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `backend/app/models.py` | `NotificationEvent.SYNC_REVIEW_PENDING`, `ADMIN_ONLY_EVENTS` membership, `SyncReviewPendingCounts` schema | 1, 2 |
| `backend/app/alembic/versions/f6a7b8c9d0e1_m034_sync_review_notification_event.py` | Additive enum value | 1 |
| `backend/app/crud.py` | `count_pending_sync_review_items`, `create_sync_review_item` returning `(item, replayed)` | 2, 5 |
| `backend/app/services/notify.py` | Render template, cooldown filter, producer + `_bg` entrypoint | 3, 4 |
| `backend/app/api/routes/sync_review.py` | Queues the background notify on a genuine insert | 5 |
| `backend/app/seed_demo.py` | Caller updated for the tuple return | 5 |
| `backend/tests/services/test_notification_policy.py` | Role-eligibility of the new event | 1 |
| `backend/tests/services/test_notify.py` | Render template + producer/cooldown behaviour | 3, 4 |
| `backend/tests/api/routes/test_sync_review.py` | Counts helper + route wiring + replay guard | 2, 5 |
| `frontend/src/client/**` | Regenerated SDK | 6 |

---

### Task 1: Add the event and its migration

**Files:**
- Modify: `backend/app/models.py:127-153`
- Create: `backend/app/alembic/versions/f6a7b8c9d0e1_m034_sync_review_notification_event.py`
- Test: `backend/tests/services/test_notification_policy.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `NotificationEvent.SYNC_REVIEW_PENDING` (str enum, value `"SYNC_REVIEW_PENDING"`), a member of `ADMIN_ONLY_EVENTS`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/services/test_notification_policy.py`:

```python
def test_sync_review_pending_is_admin_only() -> None:
    from app.models import ADMIN_ONLY_EVENTS, ALL_ROLE_EVENTS, NotificationEvent

    assert NotificationEvent.SYNC_REVIEW_PENDING in ADMIN_ONLY_EVENTS
    assert NotificationEvent.SYNC_REVIEW_PENDING not in ALL_ROLE_EVENTS


def test_sync_review_pending_offered_to_admins_only() -> None:
    from app.models import NotificationEvent, User, UserRole, eligible_events

    admin = User(email="a@example.test", hashed_password="x", role=UserRole.BKK_ADMIN)
    staff = User(email="s@example.test", hashed_password="x", role=UserRole.YGN_STAFF)

    assert NotificationEvent.SYNC_REVIEW_PENDING in eligible_events(admin)
    assert NotificationEvent.SYNC_REVIEW_PENDING not in eligible_events(staff)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/services/test_notification_policy.py -v -k sync_review`
Expected: FAIL with `AttributeError: SYNC_REVIEW_PENDING`

- [ ] **Step 3: Add the enum member**

In `backend/app/models.py`, extend `NotificationEvent`:

```python
class NotificationEvent(str, enum.Enum):
    LOW_STOCK = "LOW_STOCK"
    OVERRIDE_PENDING = "OVERRIDE_PENDING"
    PULL_FULFILLED = "PULL_FULFILLED"
    PULL_SHORT = "PULL_SHORT"
    SYNC_REVIEW_PENDING = "SYNC_REVIEW_PENDING"
```

- [ ] **Step 4: Add it to `ADMIN_ONLY_EVENTS`**

Replace the block at `models.py:139-150`. Note the comment says "the three below" today and must say four — the recipient-query claim it makes is exactly what keeps this list honest:

```python
# Who may receive which event. These must agree with the recipient queries in
# app.services.notify: the four below are fetched with
# `User.role == UserRole.BKK_ADMIN`, while notify_low_stock has no role filter.
# Offering a staff user a checkbox for an admin-only event would persist
# enabled=True and then silently never deliver.
ADMIN_ONLY_EVENTS: frozenset["NotificationEvent"] = frozenset(
    {
        NotificationEvent.PULL_SHORT,
        NotificationEvent.PULL_FULFILLED,
        NotificationEvent.OVERRIDE_PENDING,
        NotificationEvent.SYNC_REVIEW_PENDING,
    }
)
```

`ALL_ROLE_EVENTS` is derived (`set(NotificationEvent) - ADMIN_ONLY_EVENTS`) and needs no edit.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/services/test_notification_policy.py -v -k sync_review`
Expected: PASS (2 tests)

- [ ] **Step 6: Write the migration**

Create `backend/app/alembic/versions/f6a7b8c9d0e1_m034_sync_review_notification_event.py`:

```python
"""m034 sync review notification event

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-29 00:00:00.000000

Adds SYNC_REVIEW_PENDING to the notificationevent enum so admins can be
pushed an alert when an offline mutation lands in the sync-review queue
(M020). Additive only — no table, column, or constraint changes.

Asymmetric downgrade (deliberate, mirroring m030): PostgreSQL cannot drop a
value from an enum without recreating the type and rewriting every dependent
column (notificationlog.event_type, notificationpreference.event_type), so
the downgrade LEAVES the value in place. Harmless — it is simply unreferenced
once no producer emits it.

PG 12+ permits ALTER TYPE ... ADD VALUE inside a transaction block; the new
value may not be *used* in that same transaction, which this migration does
not do.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE notificationevent ADD VALUE IF NOT EXISTS 'SYNC_REVIEW_PENDING'"
    )


def downgrade() -> None:
    # 'SYNC_REVIEW_PENDING' intentionally left in the notificationevent enum
    # — see module docstring.
    pass
```

- [ ] **Step 7: Apply and verify the migration**

Run: `cd backend && alembic upgrade head && alembic current`
Expected: `alembic current` reports `f6a7b8c9d0e1 (head)`.

Then confirm the enum actually accepts the value:

Run: `docker compose exec db psql -U postgres -d app -c "SELECT unnest(enum_range(NULL::notificationevent))"`
Expected: five rows, including `SYNC_REVIEW_PENDING`.

- [ ] **Step 8: Commit**

```bash
git add backend/app/models.py backend/app/alembic/versions/f6a7b8c9d0e1_m034_sync_review_notification_event.py backend/tests/services/test_notification_policy.py
git commit -m "feat(notify): add SYNC_REVIEW_PENDING event (m034)"
```

---

### Task 2: Count the PENDING queue

**Files:**
- Modify: `backend/app/models.py` (new schema, beside `SyncReviewResolve` around line 1291)
- Modify: `backend/app/crud.py` (beside `list_sync_review_items`, around line 2307)
- Test: `backend/tests/api/routes/test_sync_review.py`

**Interfaces:**
- Consumes: `SyncReviewItem`, `SyncReviewState`, `SyncReviewReason` from Task 1's module.
- Produces:
  - `SyncReviewPendingCounts(SQLModel)` with fields `total: int`, `stale: int`, `conflict: int`.
  - `crud.count_pending_sync_review_items(*, session: Session) -> SyncReviewPendingCounts`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/api/routes/test_sync_review.py`. The existing `_ingest` helper at line 27 is reused; it defaults to `SyncReviewReason.STALE`:

```python
def test_count_pending_splits_by_reason(db: Session) -> None:
    before = crud.count_pending_sync_review_items(session=db)

    _ingest(db, reason=SyncReviewReason.STALE)
    _ingest(db, reason=SyncReviewReason.CONFLICT)
    _ingest(db, reason=SyncReviewReason.CONFLICT)

    after = crud.count_pending_sync_review_items(session=db)
    assert after.stale == before.stale + 1
    assert after.conflict == before.conflict + 2
    assert after.total == after.stale + after.conflict


def test_count_pending_excludes_resolved(db: Session) -> None:
    item_id = _ingest(db, reason=SyncReviewReason.CONFLICT)
    before = crud.count_pending_sync_review_items(session=db)

    crud.resolve_sync_review_item(
        session=db,
        item_id=item_id,
        admin_id=_admin_id(db),
        new_state=SyncReviewState.RESOLVED,
        note=None,
    )

    after = crud.count_pending_sync_review_items(session=db)
    assert after.conflict == before.conflict - 1
    assert after.total == before.total - 1
```

The `db` fixture is session-scoped and shared, so these assert *deltas*, never absolute counts — other tests in the same run leave rows behind.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/api/routes/test_sync_review.py -v -k count_pending`
Expected: FAIL with `AttributeError: module 'app.crud' has no attribute 'count_pending_sync_review_items'`

- [ ] **Step 3: Add the schema**

In `backend/app/models.py`, after `SyncReviewResolve`:

```python
class SyncReviewPendingCounts(SQLModel):
    # Named fields rather than a bare 3-tuple: three same-typed ints are
    # trivially transposable at the call site, and the notify template reads
    # all three.
    total: int
    stale: int
    conflict: int
```

- [ ] **Step 4: Add the crud function**

In `backend/app/crud.py`, after `list_sync_review_items`. `func` is already imported at `crud.py:10`; add `SyncReviewPendingCounts` and `SyncReviewReason` to the `app.models` import block at the top:

```python
def count_pending_sync_review_items(
    *, session: Session
) -> SyncReviewPendingCounts:
    """PENDING queue depth, split by reason — the numbers the admin alert
    quotes. One grouped scan, served by ix_syncreviewitem_state_created."""
    rows = session.exec(
        select(col(SyncReviewItem.reason), func.count())
        .where(col(SyncReviewItem.state) == SyncReviewState.PENDING)
        .group_by(col(SyncReviewItem.reason))
    ).all()
    by_reason = dict(rows)
    stale = int(by_reason.get(SyncReviewReason.STALE, 0))
    conflict = int(by_reason.get(SyncReviewReason.CONFLICT, 0))
    return SyncReviewPendingCounts(
        total=stale + conflict, stale=stale, conflict=conflict
    )
```

If mypy objects to the two-column `session.exec(...)` (SQLModel's `exec` is typed for scalar selects), switch to SQLAlchemy's executor — `sa_select` is already imported at `crud.py:11`:

```python
    rows = session.execute(
        sa_select(SyncReviewItem.reason, func.count())
        .where(col(SyncReviewItem.state) == SyncReviewState.PENDING)
        .group_by(col(SyncReviewItem.reason))
    ).all()
```

Only the `rows = ...` statement changes; `by_reason` onward is identical.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/api/routes/test_sync_review.py -v -k count_pending`
Expected: PASS (2 tests)

- [ ] **Step 6: Run the full sync-review suite for regressions**

Run: `cd backend && pytest tests/api/routes/test_sync_review.py -v`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/models.py backend/app/crud.py backend/tests/api/routes/test_sync_review.py
git commit -m "feat(sync-review): count PENDING items by reason"
```

---

### Task 3: Render the message

**Files:**
- Modify: `backend/app/services/notify.py:425-476` (`_render_text`)
- Test: `backend/tests/services/test_notify.py`

**Interfaces:**
- Consumes: `NotificationEvent.SYNC_REVIEW_PENDING` (Task 1).
- Produces: `_render_text` handling `SYNC_REVIEW_PENDING` with a payload of `{"total": int, "stale": int, "conflict": int}`. Task 4 builds that exact payload shape.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/services/test_notify.py`:

```python
def test_render_sync_review_pending_plural() -> None:
    text = notify._render_text(
        event_type=NotificationEvent.SYNC_REVIEW_PENDING,
        payload={"total": 3, "stale": 1, "conflict": 2},
    )
    assert text == "⚠️ 3 offline actions need review\n2 conflicts, 1 stale"


def test_render_sync_review_pending_singular() -> None:
    text = notify._render_text(
        event_type=NotificationEvent.SYNC_REVIEW_PENDING,
        payload={"total": 1, "stale": 0, "conflict": 1},
    )
    assert text == "⚠️ 1 offline action needs review\n1 conflict"


def test_render_sync_review_pending_omits_zero_reason() -> None:
    text = notify._render_text(
        event_type=NotificationEvent.SYNC_REVIEW_PENDING,
        payload={"total": 2, "stale": 2, "conflict": 0},
    )
    assert "conflict" not in text
    assert text.endswith("2 stale")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/services/test_notify.py -v -k render_sync_review`
Expected: FAIL with `NotImplementedError: No render template for <NotificationEvent.SYNC_REVIEW_PENDING...>`

- [ ] **Step 3: Add the render branch**

In `notify.py`, insert before the final `raise NotImplementedError`:

```python
    if event_type == NotificationEvent.SYNC_REVIEW_PENDING:
        # Counts only — SyncReviewItem.payload is the raw held mutation and
        # carries prices. Ids and payload fields stay in the append-only log.
        total = int(payload.get("total") or 0)
        stale = int(payload.get("stale") or 0)
        conflict = int(payload.get("conflict") or 0)
        head = (
            "⚠️ 1 offline action needs review"
            if total == 1
            else f"⚠️ {total} offline actions need review"
        )
        parts: list[str] = []
        if conflict:
            parts.append(f"{conflict} conflict" + ("" if conflict == 1 else "s"))
        if stale:
            # "stale" is an adjective here — never pluralized.
            parts.append(f"{stale} stale")
        return f"{head}\n{', '.join(parts)}" if parts else head
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/services/test_notify.py -v -k render_sync_review`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/notify.py backend/tests/services/test_notify.py
git commit -m "feat(notify): render SYNC_REVIEW_PENDING message"
```

---

### Task 4: The producer and its cooldown

**Files:**
- Modify: `backend/app/services/notify.py` (append after `notify_override_pending_bg`, around line 623)
- Test: `backend/tests/services/test_notify.py`

**Interfaces:**
- Consumes: `crud.count_pending_sync_review_items` (Task 2), `_render_text` branch (Task 3).
- Produces:
  - `SYNC_REVIEW_COOLDOWN_SECONDS: int` (module constant, `300`).
  - `notify_sync_review_pending(*, session: Session) -> list[NotificationLog]`.
  - `notify_sync_review_pending_bg() -> None` — no parameters. Task 5 passes it to `background_tasks.add_task` bare.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/services/test_notify.py`. Reuses the existing `_make_user`, `_opt_in`, `_recording_post`, and `_resp` helpers:

```python
def _ingest_pending(db: Session, reason: Any, submitted_by: uuid.UUID) -> None:
    """Put one PENDING row in the queue. `submitted_by` must be a real user id
    — the column carries an FK to user.id."""
    from app import crud
    from app.models import SyncReviewItemCreate

    crud.create_sync_review_item(
        session=db,
        data=SyncReviewItemCreate(
            idempotency_key=uuid.uuid4(),
            mutation_kind="sale",
            payload={"total_thb": "1200.00"},
            reason=reason,
        ),
        submitted_by_user_id=submitted_by,
    )


def test_notify_sync_review_targets_admins_not_staff(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.models import SyncReviewReason

    monkeypatch.setattr(notify, "_post", lambda *a, **k: _resp(200))
    admin = _make_user(db, role=UserRole.BKK_ADMIN)
    _opt_in(db, admin, NotificationChannel.LINE,
            NotificationEvent.SYNC_REVIEW_PENDING)
    staff = _make_user(db, role=UserRole.YGN_STAFF)
    _opt_in(db, staff, NotificationChannel.LINE,
            NotificationEvent.SYNC_REVIEW_PENDING)

    _ingest_pending(db, SyncReviewReason.CONFLICT, admin.id)
    logs = notify.notify_sync_review_pending(session=db)

    targets = {log.target_user_id for log in logs}
    assert admin.id in targets
    assert staff.id not in targets


def test_notify_sync_review_suppressed_inside_cooldown(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.models import SyncReviewReason

    monkeypatch.setattr(notify, "_post", lambda *a, **k: _resp(200))
    admin = _make_user(db, role=UserRole.BKK_ADMIN)
    _opt_in(db, admin, NotificationChannel.LINE,
            NotificationEvent.SYNC_REVIEW_PENDING)

    _ingest_pending(db, SyncReviewReason.STALE, admin.id)
    first = notify.notify_sync_review_pending(session=db)
    assert any(log.target_user_id == admin.id for log in first)

    _ingest_pending(db, SyncReviewReason.STALE, admin.id)
    second = notify.notify_sync_review_pending(session=db)
    assert not any(log.target_user_id == admin.id for log in second)


def test_notify_sync_review_sends_again_after_cooldown(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.models import SyncReviewReason

    monkeypatch.setattr(notify, "_post", lambda *a, **k: _resp(200))
    admin = _make_user(db, role=UserRole.BKK_ADMIN)
    _opt_in(db, admin, NotificationChannel.LINE,
            NotificationEvent.SYNC_REVIEW_PENDING)

    _ingest_pending(db, SyncReviewReason.STALE, admin.id)
    notify.notify_sync_review_pending(session=db)

    # Shrink the window rather than sleeping or back-dating a log row.
    monkeypatch.setattr(notify, "SYNC_REVIEW_COOLDOWN_SECONDS", 0)
    again = notify.notify_sync_review_pending(session=db)
    assert any(log.target_user_id == admin.id for log in again)


def test_notify_sync_review_cooldown_is_per_recipient(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.models import SyncReviewReason

    monkeypatch.setattr(notify, "_post", lambda *a, **k: _resp(200))
    first_admin = _make_user(db, role=UserRole.BKK_ADMIN)
    _opt_in(db, first_admin, NotificationChannel.LINE,
            NotificationEvent.SYNC_REVIEW_PENDING)

    _ingest_pending(db, SyncReviewReason.CONFLICT, first_admin.id)
    notify.notify_sync_review_pending(session=db)

    # A second admin enrolls mid-burst — must still be reachable.
    late_admin = _make_user(db, role=UserRole.BKK_ADMIN)
    _opt_in(db, late_admin, NotificationChannel.LINE,
            NotificationEvent.SYNC_REVIEW_PENDING)

    logs = notify.notify_sync_review_pending(session=db)
    targets = {log.target_user_id for log in logs}
    assert late_admin.id in targets
    assert first_admin.id not in targets


def test_notify_sync_review_failed_send_starts_cooldown(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A not-enrolled admin logs FAILED; that row must suppress the next
    attempt, or every ingest writes another FAILED row forever (spec 3.3)."""
    from app.models import SyncReviewReason

    monkeypatch.setattr(notify, "_post", lambda *a, **k: _resp(200))
    admin = _make_user(db, role=UserRole.BKK_ADMIN, line_user_id=None,
                       telegram_chat_id=None, viber_user_id=None)
    _opt_in(db, admin, NotificationChannel.LINE,
            NotificationEvent.SYNC_REVIEW_PENDING)

    _ingest_pending(db, SyncReviewReason.STALE, admin.id)
    first = notify.notify_sync_review_pending(session=db)
    assert [log.status for log in first
            if log.target_user_id == admin.id] == [NotificationStatus.FAILED]

    second = notify.notify_sync_review_pending(session=db)
    assert not any(log.target_user_id == admin.id for log in second)


def test_notify_sync_review_payload_has_no_financial_keys(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.models import SyncReviewReason

    monkeypatch.setattr(notify, "_post", lambda *a, **k: _resp(200))
    admin = _make_user(db, role=UserRole.BKK_ADMIN)
    _opt_in(db, admin, NotificationChannel.LINE,
            NotificationEvent.SYNC_REVIEW_PENDING)

    _ingest_pending(db, SyncReviewReason.CONFLICT, admin.id)
    logs = notify.notify_sync_review_pending(session=db)

    assert logs
    assert_no_financial_keys(logs[0].payload)
    assert set(logs[0].payload) == {"total", "stale", "conflict"}
```

`_ingest_pending` takes the submitting user's id rather than `None`: `submitted_by_user_id` carries an FK to `user.id` and `crud.create_sync_review_item` types it as a required `uuid.UUID`. Passing the admin created in each test satisfies both and exercises nothing else — the replay-actor binding is out of scope here.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/services/test_notify.py -v -k sync_review`
Expected: FAIL with `AttributeError: module 'app.services.notify' has no attribute 'notify_sync_review_pending'`

- [ ] **Step 3: Add imports**

At the top of `notify.py`:

```python
from datetime import timedelta
```

and add `get_datetime_utc` to the existing `from app.models import (...)` block (it already imports `NotificationLog`, `User`, `UserRole`, and the enums this task uses). `crud` is already imported at `notify.py:31`.

- [ ] **Step 4: Write the producer**

Append to `notify.py`:

```python
# One burst of sync-review ingests must not become one message per item.
# divertStaleMutations posts every stale item unawaited (query-client.ts:122),
# so a reconnect lands several POSTs at once; conflicts then trickle in as
# replays 409. The first item still notifies immediately -- this only mutes
# the follow-ups.
SYNC_REVIEW_COOLDOWN_SECONDS = 300


def _sync_review_suppressed_user_ids(*, session: Session) -> set[uuid.UUID]:
    """Admins already told about the queue inside the cooldown window.

    Counts rows of ANY status, not just SENT. notify() logs a FAILED row for
    an un-enrolled recipient, and if those did not suppress, every single
    ingest would write another one for the same admin forever. The cost is
    that a genuinely failed send waits out the window (spec 3.3).
    """
    cutoff = get_datetime_utc() - timedelta(seconds=SYNC_REVIEW_COOLDOWN_SECONDS)
    rows = session.exec(
        select(col(NotificationLog.target_user_id))
        .where(
            col(NotificationLog.event_type)
            == NotificationEvent.SYNC_REVIEW_PENDING,
            col(NotificationLog.created_at) >= cutoff,
        )
        .distinct()
    ).all()
    return set(rows)


def notify_sync_review_pending(*, session: Session) -> list[NotificationLog]:
    """Notify every BKK_ADMIN outside the cooldown that offline mutations are
    waiting in the review queue (FR-021).

    The counts are read here, at send time, so the message reflects the queue
    as it stands rather than as it stood when the triggering item arrived.
    """
    suppressed = _sync_review_suppressed_user_ids(session=session)
    recipients = [
        user
        for user in session.exec(
            select(User).where(User.role == UserRole.BKK_ADMIN)
        ).all()
        if user.id not in suppressed
    ]
    if not recipients:
        return []
    counts = crud.count_pending_sync_review_items(session=session)
    if counts.total == 0:
        return []  # triaged between ingest and dispatch
    payload: dict[str, Any] = {
        "total": counts.total,
        "stale": counts.stale,
        "conflict": counts.conflict,
    }
    return notify(
        session=session,
        event_type=NotificationEvent.SYNC_REVIEW_PENDING,
        recipients=recipients,
        payload=payload,
    )


def notify_sync_review_pending_bg() -> None:
    """BackgroundTasks entrypoint for sync-review alerts. Opens its OWN session
    and never raises out of the background task (best-effort)."""
    try:
        with Session(engine) as session:
            notify_sync_review_pending(session=session)
    except Exception:  # noqa: BLE001 — belt: best-effort, swallow + log
        logger.exception("notify_sync_review_pending_bg failed")
```

Note the `suppressed` local: the query must run once, not once per candidate admin.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/services/test_notify.py -v -k sync_review`
Expected: PASS (6 tests)

- [ ] **Step 6: Run the whole notify suite for regressions**

Run: `cd backend && pytest tests/services/test_notify.py -v`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/notify.py backend/tests/services/test_notify.py
git commit -m "feat(notify): sync-review producer with per-recipient cooldown"
```

---

### Task 5: Wire the ingest route, guarding replays

**Files:**
- Modify: `backend/app/crud.py:2270-2298` (`create_sync_review_item` return type)
- Modify: `backend/app/api/routes/sync_review.py:20-37`
- Modify: `backend/app/seed_demo.py:507`
- Modify: `backend/tests/api/routes/test_sync_review.py:37-39` (helper)
- Test: `backend/tests/api/routes/test_sync_review.py`

**Interfaces:**
- Consumes: `notify.notify_sync_review_pending_bg` (Task 4).
- Produces: `crud.create_sync_review_item(...) -> tuple[SyncReviewItem, bool]` — second element is `replayed`.

This task has three existing callers to update in lockstep. Changing the signature without them is a red test suite, so they move in one commit.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/api/routes/test_sync_review.py`:

```python
def test_ingest_returns_replayed_flag(db: Session) -> None:
    key = uuid.uuid4()
    data = SyncReviewItemCreate(
        idempotency_key=key,
        mutation_kind="sale",
        payload={"customer_id": str(uuid.uuid4())},
        reason=SyncReviewReason.CONFLICT,
    )
    first, replayed_first = crud.create_sync_review_item(
        session=db, data=data, submitted_by_user_id=_admin_id(db)
    )
    second, replayed_second = crud.create_sync_review_item(
        session=db, data=data, submitted_by_user_id=_admin_id(db)
    )
    assert replayed_first is False
    assert replayed_second is True
    assert first.id == second.id


def test_route_notifies_once_per_genuine_insert(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import sync_review as route

    queued: list[str] = []
    monkeypatch.setattr(
        route.notify, "notify_sync_review_pending_bg",
        lambda: queued.append("sent"),
    )

    body = {
        "idempotency_key": str(uuid.uuid4()),
        "mutation_kind": "sale",
        "payload": {"customer_id": str(uuid.uuid4())},
        "reason": "CONFLICT",
    }
    first = client.post(
        f"{settings.API_V1_STR}/sync-review", headers=superuser_token_headers,
        json=body,
    )
    assert first.status_code == 200
    assert len(queued) == 1

    # Same idempotency_key — a replay must NOT re-notify.
    second = client.post(
        f"{settings.API_V1_STR}/sync-review", headers=superuser_token_headers,
        json=body,
    )
    assert second.status_code == 200
    assert len(queued) == 1
```

The monkeypatch replaces the function on the module object the route resolves through, so `BackgroundTasks` runs the stub. `TestClient` executes background tasks synchronously on response, so `queued` is populated by the time `post` returns.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/api/routes/test_sync_review.py -v -k "replayed_flag or notifies_once"`
Expected: FAIL — `test_ingest_returns_replayed_flag` with `TypeError: cannot unpack non-sequence SyncReviewItem`, `test_route_notifies_once_per_genuine_insert` with `AttributeError: module 'app.api.routes.sync_review' has no attribute 'notify'`

- [ ] **Step 3: Change the crud return type**

In `crud.py`, change the signature and final return of `create_sync_review_item`. The docstring already documents the replay semantics; extend the first line:

```python
def create_sync_review_item(
    *, session: Session, data: SyncReviewItemCreate, submitted_by_user_id: uuid.UUID
) -> tuple[SyncReviewItem, bool]:
    """Ingest a STALE/CONFLICT offline mutation into the admin review queue.

    Returns ``(item, replayed)``. ``replayed`` is True when an existing row was
    returned instead of a fresh insert — the caller uses it to avoid
    re-notifying for an item already sitting in the queue.

    Idempotent by ``idempotency_key``: a re-POST of the same offline item
    returns the existing row (UNIQUE constraint + IntegrityError rollback path
    via ``get_or_replay``), never a duplicate. Replays are bound to the
    original submitter (hardening spec §4.1.3); legacy NULL rows replay
    unbound."""
```

and replace the final `return item` with:

```python
    return item, replayed
```

Leave the body between untouched.

- [ ] **Step 4: Update the two non-route callers**

`backend/app/seed_demo.py:507` — the list comprehension collects the results, so index the item out:

```python
        crud.create_sync_review_item(
            session=s,
            data=SyncReviewItemCreate(
                idempotency_key=key(),
                mutation_kind=kind,
                payload=payload,
                reason=reason,
            ),
            submitted_by_user_id=uid,
        )[0]
```

`backend/tests/api/routes/test_sync_review.py:37-39` — the `_ingest` helper returns an id:

```python
    return crud.create_sync_review_item(
        session=db, data=data, submitted_by_user_id=_admin_id(db)
    )[0].id
```

- [ ] **Step 5: Wire the route**

In `backend/app/api/routes/sync_review.py`, add `BackgroundTasks` to the FastAPI import at line 4 and import the service:

```python
from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request

from app import crud
from app.api.deps import AdminUser, CurrentUser, SessionDep, get_admin
from app.core.limiter import SYNC_INGEST_RATE_LIMIT, limiter
from app.services import notify
```

Then replace the body of `ingest_sync_review_item`:

```python
def ingest_sync_review_item(
    *,
    request: Request,  # noqa: ARG001 — required by slowapi's rate-limit decorator
    session: SessionDep,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
    data: SyncReviewItemCreate,
) -> SyncReviewItemStaffPublic:
    """Report a STALE/CONFLICT offline mutation for review (FR-021). Any
    authenticated device may ingest; idempotent on idempotency_key."""
    item, replayed = crud.create_sync_review_item(
        session=session, data=data, submitted_by_user_id=current_user.id
    )
    # Only a genuine insert alerts admins — a device re-POSTing the same
    # idempotency_key must not re-notify for an item already in the queue.
    if not replayed:
        background_tasks.add_task(notify.notify_sync_review_pending_bg)
    return SyncReviewItemStaffPublic.model_validate(item)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && pytest tests/api/routes/test_sync_review.py -v`
Expected: all PASS, including the pre-existing idempotency tests

- [ ] **Step 7: Run the full backend suite**

Run: `cd backend && pytest -q`
Expected: 0 failed. The baseline on this repo is fully green — any failure here is yours.

- [ ] **Step 8: Verify lint and types**

Run: `cd backend && ruff check app tests && mypy app`
Expected: clean

- [ ] **Step 9: Commit**

```bash
git add backend/app/crud.py backend/app/api/routes/sync_review.py backend/app/seed_demo.py backend/tests/api/routes/test_sync_review.py
git commit -m "feat(sync-review): notify admins on ingest, skipping replays"
```

---

### Task 6: Regenerate the SDK

**Files:**
- Modify: `frontend/src/client/types.gen.ts`, `frontend/src/client/schemas.gen.ts` (generated)

**Interfaces:**
- Consumes: the OpenAPI schema produced by Tasks 1–5.
- Produces: `NotificationEvent` in `types.gen.ts` including `'SYNC_REVIEW_PENDING'`.

No component changes. The preferences grid builds rows from whatever the API returns and labels them with `humanize()` (`notifications.tsx:55,137`), so the checkbox row appears once `eligible_events()` includes the event.

- [ ] **Step 1: Confirm the backend is serving the new schema**

Run: `curl -s http://localhost:8000/api/v1/openapi.json | grep -o "SYNC_REVIEW_PENDING" | head -1`
Expected: `SYNC_REVIEW_PENDING`

If empty, the backend container is serving stale code — restart it before continuing. Regenerating against a stale schema silently drops the new value.

- [ ] **Step 2: Regenerate**

Run **on the host**, not inside the frontend container:

```bash
cd frontend && bun run generate-client
```

- [ ] **Step 3: Verify the generated types**

Run: `grep -n "SYNC_REVIEW_PENDING" frontend/src/client/types.gen.ts frontend/src/client/schemas.gen.ts`
Expected: a hit in each — `types.gen.ts` should read
`export type NotificationEvent = 'LOW_STOCK' | 'OVERRIDE_PENDING' | 'PULL_FULFILLED' | 'PULL_SHORT' | 'SYNC_REVIEW_PENDING';`

- [ ] **Step 4: Typecheck and lint the frontend**

Run: `cd frontend && bunx tsc --noEmit && bunx biome check src`
Expected: clean

- [ ] **Step 5: Confirm the row renders**

Log in as a BKK_ADMIN, open `/notifications`, and confirm a "Sync review pending" row appears in the grid with Telegram/LINE checkboxes. Log in as YGN_STAFF and confirm it does **not**.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/client
git commit -m "chore(client): regenerate SDK for SYNC_REVIEW_PENDING"
```

---

## Done criteria

- `alembic current` reports `f6a7b8c9d0e1 (head)`.
- `cd backend && pytest -q` reports 0 failed.
- An admin opted into SYNC_REVIEW_PENDING receives one message on the first ingest and none for four more minutes.
- A staff user opted in receives nothing.
- Re-POSTing an existing `idempotency_key` sends nothing.
- `/notifications` shows the new row for admins only, with no frontend source change.
