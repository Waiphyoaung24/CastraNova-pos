# Viber Removal Implementation Plan (Part 0 / PR 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove every executable trace of the dead Viber notification channel, which has no enrollment path and carries a latent bug that silently discards notification audit rows.

**Architecture:** Delete the Viber sender, its config token and its address mapping, then drop the `user.viber_user_id` column. `NotificationChannel.VIBER` stays a legal enum member — Postgres cannot remove a value from a native enum type, and removing it would require dropping an append-only audit trigger and destroying historical log rows. `CHANNEL_ADDRESS_ATTR` becomes the single source of truth for "channels we can actually address", which drops Viber from the API and UI automatically.

**Tech Stack:** FastAPI, SQLModel, Alembic, PostgreSQL, pytest; React + TypeScript, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-10-line-enrollment-design.md` Part 0.

## Global Constraints

- **Do not remove `NotificationChannel.VIBER` from the Python enum or the Postgres enum type.** Spec §0.2. Historical `notificationlog` rows carry the value and must still deserialize.
- **Do not touch `notificationlog` rows.** The table is protected by `trg_notificationlog_append_only` (m021, BEFORE UPDATE OR DELETE).
- **Do not modify any Telegram code path.** Telegram enrollment is working and out of scope.
- **Alembic:** current head is `m037` (`a1b2c3d4e5f7`). This PR adds exactly one migration, `m038`. Verify with `alembic heads` before writing it — several worktrees add migrations concurrently.
- **Every schema change requires an Alembic migration** (CLAUDE.md).
- **mypy strict is on.** Annotate everything.
- **Frontend lint is biome**, not ESLint/Prettier.

### Running tests

**Do not use `bash scripts/test.sh` for the TDD loop.** It runs `docker compose down -v`, which **destroys the database volume**. Use it only for a final full-suite run, and expect to reseed afterwards.

For the per-task loop:

```bash
# Terminal 1 — keeps the container's code in sync with your edits.
# Without this the container runs STALE code and pytest reports false greens.
docker compose watch

# Terminal 2 — run a single test
docker compose exec backend pytest tests/path/test_file.py::test_name -v
```

**The backend test suite TRUNCATEs all domain data including users.** After any backend test run, restore the dev database with:

```bash
docker compose exec backend python -m app.initial_data
docker compose exec backend python -m app.seed_demo
```

**Known-failing baseline:** the suite has 3 persistent pre-existing failures (2 stale redaction sweeps, 1 July-2026 date-dependent report test) plus occasional catalog-ordering flakes. Diff failure *names* against the baseline, never counts.

Frontend pure-logic specs are Playwright, not vitest, and run browserless:

```bash
cd frontend && bunx playwright test tests/labels.spec.ts --no-deps
```

---

### Task 1: Make `channel_connected` total and drop VIBER from the address map

This is the only behaviour change in the PR. `VIBER` remains a legal `NotificationChannel` but leaves `CHANNEL_ADDRESS_ATTR`, so the existing `CHANNEL_ADDRESS_ATTR[channel]` lookup would raise `KeyError` for a value the type system still permits. Making the grid iterate the map is what removes Viber from the API and UI.

**Files:**
- Modify: `backend/app/models.py:222-233` (`CHANNEL_ADDRESS_ATTR`, `channel_connected`)
- Modify: `backend/app/crud.py:3808` (`list_notification_preferences`)
- Test: `backend/tests/services/test_notification_policy.py:93-98`
- Test: `backend/tests/api/routes/test_notifications.py:186-206`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `CHANNEL_ADDRESS_ATTR: dict[NotificationChannel, str]` containing exactly `LINE` and `TELEGRAM`. `channel_connected(user: User, channel: NotificationChannel) -> bool` never raises. Tasks 2 and 3 rely on VIBER already being absent from this map.

- [ ] **Step 1: Write the failing tests**

Keep the existing `VIBER` assertion in `test_channel_disconnected_by_default` — it stops being a Viber test and becomes the regression test for totality. Add an explicit test naming that intent, in `backend/tests/services/test_notification_policy.py`:

```python
def test_channel_connected_is_total_over_the_enum() -> None:
    """VIBER remains a legal enum member (historical log rows) but has no
    address attribute. channel_connected must answer False, not raise."""
    user = _user(UserRole.YGN_STAFF)
    for channel in NotificationChannel:
        assert channel_connected(user, channel) is False
```

Add to `backend/tests/api/routes/test_notifications.py`:

```python
def test_grid_omits_channels_with_no_address_attribute(
    client: TestClient, staff_token_headers: dict[str, str]
) -> None:
    """A channel notify() cannot address must not appear in the grid at all —
    offering the checkbox would promise a send that never happens."""
    r = client.get(f"{PREFIX}/notifications/preferences", headers=staff_token_headers)
    assert r.status_code == 200, r.text
    channels = {p["channel"] for p in r.json()}
    assert "VIBER" not in channels
    assert channels == {c.value for c in CHANNEL_ADDRESS_ATTR}
```

Add `CHANNEL_ADDRESS_ATTR` to that file's imports from `app.models`.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
docker compose exec backend pytest \
  tests/services/test_notification_policy.py::test_channel_connected_is_total_over_the_enum \
  tests/api/routes/test_notifications.py::test_grid_omits_channels_with_no_address_attribute -v
```

Expected: both FAIL. The first passes today by accident (VIBER is still in the map); it must fail only *after* Step 3's map edit, so if it passes now, that is expected — re-run it after Step 3 and confirm it still passes. The second FAILs with `assert 'VIBER' not in {...}`.

- [ ] **Step 3: Drop VIBER from the map and make the lookup total**

In `backend/app/models.py`, replace lines 220-233:

```python
# Mirrors the address-attribute mapping baked into services/notify.py's
# _CHANNELS -- keep both in sync if a channel is ever added. This dict is
# the single source of truth for "channels we can actually address": the
# preference grid is built from its keys, so a channel absent here is
# invisible to the API and UI.
CHANNEL_ADDRESS_ATTR: dict[NotificationChannel, str] = {
    NotificationChannel.LINE: "line_user_id",
    NotificationChannel.TELEGRAM: "telegram_chat_id",
}


def channel_connected(user: User, channel: NotificationChannel) -> bool:
    """Whether `user` has an address configured for `channel`, independent of
    any event opt-in -- a preference row is meaningless to enable if notify()
    has no address to send to.

    Total over NotificationChannel on purpose: VIBER is still a legal member
    (historical notificationlog rows carry it) but has no address attribute,
    and a channel we cannot address is by definition not connected.
    """
    attr = CHANNEL_ADDRESS_ATTR.get(channel)
    return bool(attr and getattr(user, attr))
```

At `backend/app/models.py:126`, annotate the retained enum member:

```python
class NotificationChannel(str, enum.Enum):
    LINE = "LINE"
    # Historical only -- no sender, no address attribute, not offered in the
    # preference grid. Retained because Postgres cannot remove a value from a
    # native enum type and existing notificationlog rows still carry it.
    VIBER = "VIBER"
    TELEGRAM = "TELEGRAM"
```

In `backend/app/crud.py:3808`, change the grid loop:

```python
    for channel in CHANNEL_ADDRESS_ATTR:
```

Add `CHANNEL_ADDRESS_ATTR` to crud.py's existing `from app.models import (...)` block.

- [ ] **Step 4: Fix the existing grid test, which encodes the old source of truth**

`backend/tests/api/routes/test_notifications.py:198` builds its expectation from `NotificationChannel`, which still includes VIBER. Change it to:

```python
    expected = {
        (c.value, e.value) for c in CHANNEL_ADDRESS_ATTR for e in ALL_ROLE_EVENTS
    }
```

- [ ] **Step 5: Run the affected tests to verify they pass**

```bash
docker compose exec backend pytest \
  tests/services/test_notification_policy.py \
  tests/api/routes/test_notifications.py -v
```

Expected: PASS. `test_patch_preferences_upsert_idempotent` will still FAIL — it PATCHes a VIBER preference and is fixed in Task 3. That is the only expected failure here.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models.py backend/app/crud.py \
  backend/tests/services/test_notification_policy.py \
  backend/tests/api/routes/test_notifications.py
git commit -m "refactor(notifications): CHANNEL_ADDRESS_ATTR is the live-channel source of truth

Drops VIBER from the address map and makes channel_connected total over
the enum. VIBER stays a legal member for historical log rows, so the
lookup must return False rather than KeyError."
```

---

### Task 2: Delete the Viber sender

Removes review finding **H2**: `send_viber` calls `response.json()` on a 200, which raises `ValueError` on a non-JSON body. `ValueError` is not in the caught tuple at `notify.py:368`, so it escapes `notify()` before `session.commit()` at line 394 — discarding every log row for that fan-out, across all users and channels.

**Files:**
- Modify: `backend/app/services/notify.py:1-14, 53, 114-134, 296-301`
- Modify: `backend/app/core/config.py:112-117`
- Modify: `.env.example:55`
- Test: `backend/tests/services/test_notify.py:1, 33, 45, 496-528, 590, 628-645, 743-752`
- Test: `backend/tests/api/routes/test_low_stock.py:136`

**Interfaces:**
- Consumes: Task 1's `CHANNEL_ADDRESS_ATTR` without VIBER.
- Produces: `notify._CHANNELS` containing exactly `LINE` and `TELEGRAM`. `notify.send_viber` and `settings.VIBER_AUTH_TOKEN` no longer exist — any later reference is an `AttributeError`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/services/test_notify.py`:

```python
def test_notify_fans_out_only_to_addressable_channels() -> None:
    """_CHANNELS must match CHANNEL_ADDRESS_ATTR: a channel in one but not the
    other either sends to an address the grid never offered, or is offered a
    checkbox that can never deliver."""
    assert set(notify._CHANNELS) == set(CHANNEL_ADDRESS_ATTR)
    assert NotificationChannel.VIBER not in notify._CHANNELS
```

Import `CHANNEL_ADDRESS_ATTR` from `app.models` in that file.

- [ ] **Step 2: Run it to verify it fails**

```bash
docker compose exec backend pytest \
  tests/services/test_notify.py::test_notify_fans_out_only_to_addressable_channels -v
```

Expected: FAIL — `_CHANNELS` still holds VIBER.

- [ ] **Step 3: Delete the sender and its wiring**

In `backend/app/services/notify.py`:

- Delete line 53: `VIBER_SEND_URL = "https://chatapi.viber.com/pa/send_message"`
- Delete lines 114-134 in full (`def send_viber` through `raise PermanentNotifyError(f"viber status {status}")`)
- Delete the `NotificationChannel.VIBER: (send_viber, "viber_user_id"),` line from `_CHANNELS`
- Replace the module docstring's first two paragraphs (lines 1-13) with:

```python
"""Outbound LINE + Telegram push notifications (FR-018).

Outbound only. Each channel send runs 4 attempts / 3 retries with exponential
backoff (waits 1s, 5s, 25s) on transient failures (5xx / transport errors); 4xx
is permanent and never retried. Telegram's 429 (rate-limited) is the one 4xx
treated as transient. ``notify`` is best-effort: it never raises to its caller
— every send outcome (including failures and un-enrolled recipients) lands as
one append-only ``notification_log`` row for weekly admin review.

Tokens are read from settings and never logged. LINE sends its token in a
header; Telegram's bot token rides in the URL path instead, so the Telegram URL
must never reach a log or an exception message.
"""
```

In `backend/app/core/config.py`, replace lines 112-117:

```python
    # Outbound push notification tokens (FR-018). None in dev/test; the LINE
    # and Telegram clients are mocked in tests. Never log these.
    # TELEGRAM_BOT_TOKEN goes in the request URL, not a header — see notify.py.
    LINE_CHANNEL_ACCESS_TOKEN: str | None = None
    TELEGRAM_BOT_TOKEN: str | None = None
```

In `.env.example`, delete line 55 (`VIBER_AUTH_TOKEN=`).

- [ ] **Step 4: Remove the Viber tests and repair the shared fixtures**

In `backend/tests/services/test_notify.py`:

- Line 1 docstring: `"""Service tests for LINE + Telegram push notifications (FR-018, Task 2.7).`
- Delete line 33 (`VIBER_TOKEN = ...`) and line 45 (`monkeypatch.setattr(settings, "VIBER_AUTH_TOKEN", VIBER_TOKEN)`). Line 45 would raise `AttributeError` against the new Settings.
- Delete `test_send_viber_status_zero_success` (496-510), `test_send_viber_nonzero_status_permanent_no_retry` (512-528), `test_send_viber_unset_token_raises_permanent_no_call` (743-752).
- Line 590 comment: change `# explicit disabled LINE pref + no VIBER pref at all` to `# explicit disabled LINE pref + no TELEGRAM pref at all`.
- In `test_notify_one_log_per_attempted_recipient_channel` (628-645), change line 634 to opt into TELEGRAM instead of VIBER and line 643 to `assert channels == ["LINE", "TELEGRAM"]`. The test's point is one log row per attempted (recipient, channel) pair, which TELEGRAM exercises identically.

In `backend/tests/api/routes/test_low_stock.py`, delete line 136 (`monkeypatch.setattr(settings, "VIBER_AUTH_TOKEN", "viber-token")`).

Leave `viber_user_id` in the `_user` helper (lines 85, 100) and line 1314 alone — Task 3 removes the column and those go with it.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
docker compose exec backend pytest tests/services/test_notify.py tests/api/routes/test_low_stock.py -v
```

Expected: PASS, with no `test_send_viber_*` collected.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/notify.py backend/app/core/config.py .env.example \
  backend/tests/services/test_notify.py backend/tests/api/routes/test_low_stock.py
git commit -m "refactor(notifications): delete the Viber sender

Viber has no enrollment path and can never deliver. Deleting send_viber
also removes a latent bug: response.json() on a non-JSON 200 raised
ValueError, which escaped notify() before its commit and silently
discarded every notification log row for that fan-out."
```

---

### Task 3: Drop the `viber_user_id` column

**Files:**
- Modify: `backend/app/models.py:208`
- Create: `backend/app/alembic/versions/<rev>_m038_drop_user_viber_user_id.py`
- Modify: `backend/app/seed_demo.py:553-560`
- Test: `backend/tests/services/test_notify.py:85, 100, 1314`
- Test: `backend/tests/api/routes/test_notifications.py:87, 102, 117, 127`
- Test: `backend/tests/services/test_telegram_enrollment.py` (new test)

**Interfaces:**
- Consumes: Task 1's map (nothing references `viber_user_id` any more) and Task 2's deleted sender.
- Produces: `User` with no `viber_user_id` attribute. Alembic head becomes `m038`.

- [ ] **Step 1: Write the failing test**

The retained enum member exists so historical rows still read. Prove it, in `backend/tests/services/test_telegram_enrollment.py`:

```python
def test_historical_viber_notification_log_still_reads(db: Session) -> None:
    """VIBER stays in the enum precisely so pre-existing audit rows survive
    the channel's removal. notificationlog is append-only (m021), so these
    rows cannot be deleted and must remain readable."""
    user = _make_user(db)
    log = NotificationLog(
        channel=NotificationChannel.VIBER,
        event_type=NotificationEvent.PULL_FULFILLED,
        target_user_id=user.id,
        payload={"pull": "PRJ-2026-01"},
        status=NotificationStatus.SENT,
        attempts=1,
    )
    db.add(log)
    db.commit()

    fetched = db.exec(
        select(NotificationLog).where(NotificationLog.id == log.id)
    ).one()
    assert fetched.channel is NotificationChannel.VIBER
    assert channel_connected(user, fetched.channel) is False
```

Use the file's existing user-creation helper rather than inventing one; add the imports it needs.

- [ ] **Step 2: Run it to verify it passes for the right reason**

```bash
docker compose exec backend pytest \
  tests/services/test_telegram_enrollment.py::test_historical_viber_notification_log_still_reads -v
```

Expected: PASS. This one is a characterization test — it must pass both before and after the column drop. If it errors on `channel_connected`, Task 1 was not applied.

- [ ] **Step 3: Delete the model field**

In `backend/app/models.py`, delete line 208:

```python
    viber_user_id: str | None = Field(default=None, max_length=128)
```

- [ ] **Step 4: Generate and review the migration**

```bash
docker compose exec backend alembic revision --autogenerate -m "m038_drop_user_viber_user_id"
```

Review the generated file. It must contain exactly one operation. Replace its body with:

```python
def upgrade() -> None:
    # Safe: nothing ever wrote this column. Viber had no enrollment path, so
    # every row is NULL and no data is lost.
    op.drop_column("user", "viber_user_id")


def downgrade() -> None:
    op.add_column(
        "user",
        sa.Column("viber_user_id", sa.String(length=128), nullable=True),
    )
```

Confirm `down_revision` is `a1b2c3d4e5f7` (m037).

- [ ] **Step 5: Apply the migration and verify the round trip**

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend alembic downgrade -1
docker compose exec backend alembic upgrade head
docker compose exec backend alembic current
```

Expected: `alembic current` reports the new m038 revision as `(head)`, with no errors on either direction.

- [ ] **Step 6: Remove the remaining `viber_user_id` and VIBER-preference references**

In `backend/app/seed_demo.py`, delete the `NotificationLog(...)` entry with `channel=NotificationChannel.VIBER` (lines 553-560). Leave the surrounding list and the `print` alone.

In `backend/tests/services/test_notify.py`: delete the `viber_user_id: str | None = "V-recipient",` parameter at line 85, the `user.viber_user_id = viber_user_id` assignment at line 100, and the `viber_user_id=None,` argument at line 1314.

In `backend/tests/api/routes/test_notifications.py`, `test_patch_preferences_upsert_idempotent` PATCHes a VIBER preference — which the grid no longer offers. Change `"channel": "VIBER"` at line 87 to `"channel": "TELEGRAM"`, and the three matching filters at lines 102, 117 and 127 to TELEGRAM. The test covers upsert idempotency, not Viber; TELEGRAM exercises it identically.

- [ ] **Step 7: Run the backend suite**

```bash
docker compose exec backend pytest tests/ -q
```

Expected: no new failures beyond the documented baseline (3 pre-existing failures — 2 stale redaction sweeps, 1 date-dependent report test — plus possible catalog-ordering flakes). Diff failure *names* against the baseline, not counts.

Then restore the dev database, which the run truncated:

```bash
docker compose exec backend python -m app.initial_data
docker compose exec backend python -m app.seed_demo
```

- [ ] **Step 8: Commit**

```bash
git add backend/app/models.py backend/app/alembic/versions/ backend/app/seed_demo.py \
  backend/tests/services/test_notify.py backend/tests/api/routes/test_notifications.py \
  backend/tests/services/test_telegram_enrollment.py
git commit -m "feat(notifications)!: drop user.viber_user_id (m038)

Every value was NULL — Viber never had an enrollment path to write one.
VIBER remains a legal enum member so append-only notificationlog rows
still deserialize; covered by a characterization test."
```

---

### Task 4: Frontend and documentation

**Files:**
- Modify: `frontend/src/lib/labels.ts:53-54`
- Modify: `frontend/src/components/Sidebar/AppSidebar.tsx:73`
- Modify: `frontend/tests/labels.spec.ts:34-36`
- Modify: `frontend/tests/notifications.spec.ts:35`
- Modify: `CLAUDE.md`
- Regenerate: `frontend/src/client/`

**Interfaces:**
- Consumes: Task 3's backend schema — the regenerated SDK reflects it.
- Produces: nothing later tasks depend on. This task ends the PR.

- [ ] **Step 1: Update the failing spec first**

`frontend/tests/labels.spec.ts:34-36` asserts `channelLabel("VIBER")` returns `"Viber"`. Change the test to pin the new behaviour — unknown channels pass through unchanged:

```typescript
test("channelLabel keeps LINE, names Telegram, and passes through unknowns", () => {
  expect(channelLabel("LINE")).toBe("LINE")
  expect(channelLabel("TELEGRAM")).toBe("Telegram")
  // VIBER survives in the enum for historical log rows but has no friendly
  // name and never renders in the grid; it must fall through, not throw.
  expect(channelLabel("VIBER")).toBe("VIBER")
  expect(channelLabel("SMOKE_SIGNAL")).toBe("SMOKE_SIGNAL")
})
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd frontend && bunx playwright test tests/labels.spec.ts --no-deps
```

Expected: FAIL — `expected "VIBER", received "Viber"`.

- [ ] **Step 3: Delete the label case**

In `frontend/src/lib/labels.ts`, delete lines 53-54:

```typescript
    case "VIBER":
      return "Viber"
```

The `default: return channel` arm already handles it, and `channelLabel` takes a plain `string`, so this cannot break typing.

- [ ] **Step 4: Run it to verify it passes**

```bash
cd frontend && bunx playwright test tests/labels.spec.ts --no-deps
```

Expected: PASS.

- [ ] **Step 5: Fix the remaining frontend references**

In `frontend/tests/notifications.spec.ts`, delete the `gridRow("VIBER", "LOW_STOCK", false, true),` fixture at line 35. **Keep** lines 47-48 — they assert no Viber checkbox and no Viber column header, which is now guaranteed by the backend rather than by the frontend filtering it out. They are the regression test for that.

In `frontend/src/components/Sidebar/AppSidebar.tsx:73`, correct the stale comment:

```typescript
  // Notification opt-in (LINE/Telegram), per-user, both roles (FR-018).
```

- [ ] **Step 6: Regenerate the SDK**

With the backend running (`docker compose watch`):

```bash
cd frontend && bun run generate-client
```

Expected: `frontend/src/client/` no longer declares `viber_user_id`. `NotificationChannel` still includes `"VIBER"` — that is correct, the enum member is retained by design.

- [ ] **Step 7: Update the project status doc**

In `CLAUDE.md`, the Telegram bullet reads "LINE/Viber still have no enrollment path". Replace with:

```markdown
- **Telegram self-enrollment shipped** (m030/m031): a one-time-code connect flow binds a user's Telegram chat to their account (`telegramconnectcode` table, unique `telegram_chat_id`). **Viber was removed entirely** (m038) — no enrollment path, no sender; `NotificationChannel.VIBER` is retained only so historical `notificationlog` rows deserialize. LINE has a sender but no enrollment path yet.
```

Also update the "Alembic head" line to `m038`.

- [ ] **Step 8: Lint and run the frontend specs**

```bash
cd frontend && bun run lint && bunx playwright test tests/labels.spec.ts --no-deps
```

Note: biome's `--write --unsafe` rewrites files across the whole repo. Review `git diff` and stage only files this PR owns; cosmetic churn elsewhere must not ride along.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/lib/labels.ts frontend/src/components/Sidebar/AppSidebar.tsx \
  frontend/tests/labels.spec.ts frontend/tests/notifications.spec.ts \
  frontend/src/client/ CLAUDE.md
git commit -m "chore(notifications): drop Viber from the frontend and docs

channelLabel now falls through for VIBER rather than naming it; the
notifications spec keeps its no-Viber-column assertions, which the
backend now guarantees."
```

---

## Final verification

- [ ] `grep -rn -i viber --exclude-dir=client --exclude-dir=.git .` returns only: the retained `NotificationChannel.VIBER` member and its comment, the `m038` migration, the characterization test, the `labels.spec.ts` fall-through assertion, the `notifications.spec.ts` absence assertions, historical design docs under `docs/`, and this plan.
- [ ] `docker compose exec backend alembic heads` reports a single head at m038.
- [ ] Full backend suite shows no new failure *names* versus the documented baseline.
- [ ] Dev database reseeded after the final test run.
- [ ] Open the PR into `dev` — never `master`.

## Self-review notes

Checked against spec §0.1-§0.4:

| Spec item | Task |
|---|---|
| Delete `VIBER_SEND_URL`, `send_viber`, `_CHANNELS` entry, docstring | Task 2 |
| Delete `VIBER_AUTH_TOKEN` + comment | Task 2 |
| Delete `User.viber_user_id`, `CHANNEL_ADDRESS_ATTR` entry | Tasks 1 and 3 |
| Keep enum member with historical-only comment | Task 1 Step 3 |
| `channel_connected` becomes total via `.get()` | Task 1 Step 3 |
| `crud.py:3808` iterates `CHANNEL_ADDRESS_ATTR` | Task 1 Step 3 |
| `seed_demo.py` VIBER log row | Task 3 Step 6 |
| Migration m038 drop-column + downgrade | Task 3 Steps 4-5 |
| `labels.ts` case, `AppSidebar` comment, SDK regen | Task 4 |
| Four listed breaking tests updated | Tasks 1, 2, 3, 4 |
| New: grid returns no VIBER rows | Task 1 Step 1 |
| New: `channel_connected(VIBER)` is False, never raises | Task 1 Step 1 |
| New: historical VIBER log row still reads | Task 3 Step 1 |
| New: migration round-trips | Task 3 Step 5 |
