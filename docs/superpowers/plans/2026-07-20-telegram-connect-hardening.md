# Telegram Connect/Confirm Hardening (H-8) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `/notifications/telegram/confirm` from amplifying a client poll into unbounded outbound Telegram traffic, bound the `telegramconnectcode` table, and fix the un-offset `getUpdates` call that silently breaks connect once the update queue is busy.

**Architecture:** Five independent changes along one call path. Read the newest slice of Telegram's update queue instead of the oldest (Part 0); cache that fetch behind a short TTL so concurrent pollers collapse to one outbound call (Part 1); add per-user rate limits via a custom slowapi `key_func` (Part 2); reap prior connect codes on mint (Part 3); stop the client poll on 429 so the new limit cannot present as a hang (Part 4).

**Tech Stack:** FastAPI, SQLModel, slowapi, httpx, pytest (backend); React + TanStack Query, @hey-api SDK, biome (frontend).

**Spec:** `docs/superpowers/specs/2026-07-20-telegram-connect-hardening-design.md`

## Global Constraints

- Branch is `dev_wth`. Never push to `master`.
- mypy runs in **strict** mode (`backend/pyproject.toml:43`). Annotate everything.
- All DB access goes through `crud.py`. Routes never call `session.exec` directly.
- The Telegram bot token rides in the URL path — **the getUpdates/sendMessage URL must never reach a log, an exception message, or Sentry.** Do not add the URL to any error string.
- Backend static checks must pass on touched files: `uv run --offline mypy app`, `uv run --offline ruff check <file>`, `uv run --offline ruff format --check <file>`. Run from `backend/`.
- Frontend: `bunx tsc -p tsconfig.build.json --noEmit` and `bunx biome check <files>` from `frontend/`. **Never run `bun run lint`** — `package.json:9` is `biome check --write --unsafe` across the whole tree and will smear unrelated changes into the commit.
- Docker is not currently running, so `pytest` cannot execute (it needs Postgres). Each task below still specifies its exact pytest command; run them once the stack is up. Known baseline is **3 failed / 654 passed** — only counts above that indicate a regression.
- **Never run `scripts/test.sh`** — it does `docker compose down -v` and destroys the dev volume.
- Existing test conventions: `notify._post` is the single monkeypatched network seam; rate-limit tests wrap in `limiter.reset()` / `limiter.enabled = True` inside `try/finally`.

---

### Task 1: Read the newest updates, not the oldest (Part 0)

**Files:**
- Modify: `backend/app/services/notify.py:181-205` (`get_telegram_updates`)
- Test: `backend/tests/services/test_notify.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `get_telegram_updates() -> list[dict[str, Any]]` — signature unchanged; the outbound request body now carries `{"offset": -100}`. Module constant `_GET_UPDATES_WINDOW: int = 100`.

**Background the implementer needs:** Telegram's `getUpdates` with no `offset` returns "updates starting with the earliest unconfirmed update", capped at `limit` (default and max 100). This code never confirms updates, so they only leave the queue by ageing out at 24h. Once more than 100 unconfirmed updates accumulate, a freshly-sent `/start` is outside the returned window and connect fails silently. A negative offset reads from the end of the queue instead.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/services/test_notify.py`:

```python
def test_get_telegram_updates_requests_the_newest_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a negative offset Telegram returns the OLDEST 100 unconfirmed
    updates, so a fresh /start falls outside the window once the queue is busy
    and connect silently fails until the backlog ages out at 24h."""
    captured: dict[str, Any] = {}

    def fake_post(url: str, *, headers: dict[str, str], json: dict[str, Any]):
        captured["json"] = json
        return _resp(200, {"ok": True, "result": []})

    monkeypatch.setattr(notify, "_post", fake_post)

    notify.get_telegram_updates()

    assert captured["json"] == {"offset": -100}
```

`_resp` already exists at `backend/tests/services/test_notify.py:47` — reuse it, don't redefine it. The autouse `_tokens` fixture (`:41`) already sets `settings.TELEGRAM_BOT_TOKEN`, so no token setup is needed in the test.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run --offline pytest tests/services/test_notify.py::test_get_telegram_updates_requests_the_newest_window -v
```

Expected: FAIL — `assert {} == {'offset': -100}`

- [ ] **Step 3: Add the constant**

In `backend/app/services/notify.py`, directly below `_TIMEOUT = 10.0`:

```python
# Read the NEWEST updates, not the oldest. With no offset, Telegram returns
# "updates starting with the earliest unconfirmed update" capped at limit
# (default and max 100). This module never confirms updates -- they leave the
# queue only by ageing out at 24h -- so once >100 unconfirmed updates pile up,
# a freshly-sent /start sits outside the window and connect silently fails.
# A negative offset reads from the end of the queue instead. It confirms
# nothing, so there is still no offset state to persist or coordinate across
# workers, which is the property the no-offset design was protecting.
_GET_UPDATES_WINDOW = 100
```

- [ ] **Step 4: Send the offset**

In `get_telegram_updates`, replace:

```python
        response = _post(url, headers={"Content-Type": "application/json"}, json={})
```

with:

```python
        response = _post(
            url,
            headers={"Content-Type": "application/json"},
            json={"offset": -_GET_UPDATES_WINDOW},
        )
```

- [ ] **Step 5: Update the docstring**

In `get_telegram_updates`, replace the paragraph beginning "Deliberately never advances the update offset:" with:

```
    Deliberately never advances the update offset: Telegram retains
    unacknowledged updates for ~24h, so this trades an unbounded update
    backlog for having no poller and no offset state to persist or coordinate
    across workers.

    Reads the newest ``_GET_UPDATES_WINDOW`` updates via a negative offset --
    see that constant for why the default (oldest-first) window is a
    correctness bug here. Used to resolve enrollment codes sent via
    ``/start <code>`` -- see ``parse_start_code``.
```

- [ ] **Step 6: Run test to verify it passes**

```bash
cd backend && uv run --offline pytest tests/services/test_notify.py -v
```

Expected: PASS, including all pre-existing tests in that file.

- [ ] **Step 7: Static checks**

```bash
cd backend && uv run --offline mypy app && uv run --offline ruff check app/services/notify.py && uv run --offline ruff format --check app/services/notify.py
```

Expected: `Success: no issues found`, `All checks passed!`, `1 file already formatted`

- [ ] **Step 8: MANUAL pre-flight — verify a negative offset does not confirm updates**

This cannot be a pytest case; a mock cannot observe Telegram's server-side queue. Against a real bot token in a scratch environment:

1. Send the bot two `/start x` messages from a Telegram client.
2. `curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" -d 'offset=-100' -H 'Content-Type: application/x-www-form-urlencoded'` — note the `update_id`s returned.
3. Run the identical call a second time.
4. **Both calls must return the same `update_id`s.** If the second returns fewer (or none), the negative offset confirmed them.

**If it does confirm:** stop and revert this task. One worker's poll would forget a `/start` before the worker serving that user's `/confirm` sees it — a flaky-connect race, strictly worse than the ceiling being fixed. The fallback is to keep `json={}`, document the 100-update ceiling in the docstring as a known limitation, and proceed to Task 2.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/notify.py backend/tests/services/test_notify.py
git commit -m "fix(notify): read the newest getUpdates window, not the oldest

Without an offset Telegram returns the earliest unconfirmed updates capped
at 100. Since this module never confirms, a backlog of >100 pushed a fresh
/start outside the window and connect failed silently until it aged out at
24h. A negative offset reads from the end of the queue and still confirms
nothing, preserving the stateless design."
```

---

### Task 2: Cache the getUpdates fetch (Part 1)

**Files:**
- Modify: `backend/app/services/notify.py` (add cache below `get_telegram_updates`)
- Modify: `backend/app/api/routes/notifications.py:78` (confirm route call site)
- Test: `backend/tests/services/test_notify.py`

**Interfaces:**
- Consumes: `get_telegram_updates() -> list[dict[str, Any]]` from Task 1.
- Produces:
  - `TELEGRAM_UPDATES_CACHE_TTL_SECONDS: float = 3.0`
  - `get_telegram_updates_cached() -> list[dict[str, Any]]`
  - `reset_telegram_updates_cache() -> None` (test seam)

**Background:** `confirm_telegram` is declared `def`, not `async def`, so FastAPI runs it in an anyio threadpool — multiple threads per worker race the same cache slot. The lock is required, not defensive. It is deliberately held **across** the network call: that is what collapses concurrent pollers into a single outbound request. The cost is that a slow Telegram response blocks other threads in that worker for up to `_TIMEOUT` (10s); acceptable because the client is a retrying poll.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/services/test_notify.py`:

```python
def test_cached_updates_collapse_repeat_calls_within_the_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}

    def fake_post(url: str, *, headers: dict[str, str], json: dict[str, Any]):
        calls["n"] += 1
        return _resp(200, {"ok": True, "result": [{"update_id": 1}]})

    monkeypatch.setattr(notify, "_post", fake_post)
    notify.reset_telegram_updates_cache()

    first = notify.get_telegram_updates_cached()
    second = notify.get_telegram_updates_cached()

    assert calls["n"] == 1
    assert first == second == [{"update_id": 1}]


def test_cached_updates_refetch_after_the_ttl_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}

    def fake_post(url: str, *, headers: dict[str, str], json: dict[str, Any]):
        calls["n"] += 1
        return _resp(200, {"ok": True, "result": []})

    monkeypatch.setattr(notify, "_post", fake_post)
    notify.reset_telegram_updates_cache()

    clock = {"t": 1000.0}
    monkeypatch.setattr(notify.time, "monotonic", lambda: clock["t"])

    notify.get_telegram_updates_cached()
    clock["t"] += notify.TELEGRAM_UPDATES_CACHE_TTL_SECONDS + 0.1
    notify.get_telegram_updates_cached()

    assert calls["n"] == 2


def test_a_failed_fetch_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    """Caching a transient failure would freeze it for the whole TTL and stall
    a legitimate connect."""
    calls = {"n": 0}

    def fake_post(url: str, *, headers: dict[str, str], json: dict[str, Any]):
        calls["n"] += 1
        if calls["n"] == 1:
            return _resp(503)
        return _resp(200, {"ok": True, "result": [{"update_id": 7}]})

    monkeypatch.setattr(notify, "_post", fake_post)
    notify.reset_telegram_updates_cache()

    with pytest.raises(notify.RetryableNotifyError):
        notify.get_telegram_updates_cached()

    assert notify.get_telegram_updates_cached() == [{"update_id": 7}]
    assert calls["n"] == 2


def test_concurrent_threads_collapse_to_one_outbound_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """confirm_telegram is a sync def, so FastAPI runs it in a threadpool --
    several threads per worker race the same cache slot."""
    import threading

    calls = {"n": 0}
    count_lock = threading.Lock()

    def fake_post(url: str, *, headers: dict[str, str], json: dict[str, Any]):
        with count_lock:
            calls["n"] += 1
        time.sleep(0.05)  # widen the race window
        return _resp(200, {"ok": True, "result": []})

    monkeypatch.setattr(notify, "_post", fake_post)
    notify.reset_telegram_updates_cache()

    threads = [
        threading.Thread(target=notify.get_telegram_updates_cached) for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert calls["n"] == 1
```

Add `import time` to the test file's imports if absent.

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run --offline pytest tests/services/test_notify.py -k "cached or concurrent or failed_fetch" -v
```

Expected: FAIL — `AttributeError: module 'app.services.notify' has no attribute 'reset_telegram_updates_cache'`

- [ ] **Step 3: Add imports**

In `backend/app/services/notify.py`, add to the stdlib import block (keep alphabetical: `logging`, `threading`, `time`, `uuid`):

```python
import threading
import time
```

- [ ] **Step 4: Implement the cache**

Add directly below `get_telegram_updates` in `backend/app/services/notify.py`:

```python
# One client poll interval (TelegramConnectCard polls every 3s). Multiple
# staff connecting at once would otherwise each drive their own outbound call
# for byte-identical data: getUpdates returns the bot's whole pending queue,
# not a per-user view.
TELEGRAM_UPDATES_CACHE_TTL_SECONDS = 3.0

_updates_cache_lock = threading.Lock()
_updates_cache: tuple[float, list[dict[str, Any]]] | None = None


def get_telegram_updates_cached() -> list[dict[str, Any]]:
    """``get_telegram_updates`` behind a short TTL, collapsing concurrent
    pollers into one outbound call.

    The lock is required, not defensive: ``confirm_telegram`` is a sync ``def``
    so FastAPI runs it in a threadpool, and several threads per worker race
    this slot. It is deliberately held across the fetch -- that is what makes
    concurrent callers share one request rather than stampede. The cost is
    that a slow Telegram response blocks other threads in this worker for up
    to ``_TIMEOUT``; acceptable because the caller is a retrying poll.

    Failures are deliberately NOT cached: freezing a transient blip for the
    whole TTL would stall a legitimate connect. An empty result IS cached --
    "nothing yet" is the dominant response during a poll and is exactly the
    case worth collapsing.

    The cached payload holds chat ids and usernames. It stays in memory and
    must never be logged (the same discipline as the bot token itself).
    """
    global _updates_cache
    with _updates_cache_lock:
        now = time.monotonic()
        cached = _updates_cache
        if cached is not None and now - cached[0] < TELEGRAM_UPDATES_CACHE_TTL_SECONDS:
            return cached[1]
        updates = get_telegram_updates()
        _updates_cache = (now, updates)
        return updates


def reset_telegram_updates_cache() -> None:
    """Drop the cached window. Test seam -- production never needs this, since
    entries expire on their own."""
    global _updates_cache
    with _updates_cache_lock:
        _updates_cache = None
```

- [ ] **Step 5: Point the confirm route at the cached fetch**

In `backend/app/api/routes/notifications.py`, in `confirm_telegram`, replace:

```python
        for update in notify.get_telegram_updates():
```

with:

```python
        for update in notify.get_telegram_updates_cached():
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd backend && uv run --offline pytest tests/services/test_notify.py tests/api/routes/test_telegram_connect.py -v
```

Expected: PASS. The existing `test_telegram_connect.py` cases still pass because they monkeypatch `_post`, which sits underneath the cache — but they now share cache state, so if any fail with a stale-result error, add `notify.reset_telegram_updates_cache()` to the top of that test.

- [ ] **Step 7: Static checks**

```bash
cd backend && uv run --offline mypy app && uv run --offline ruff check app/services/notify.py app/api/routes/notifications.py && uv run --offline ruff format --check app/services/notify.py app/api/routes/notifications.py
```

Expected: `Success: no issues found`, `All checks passed!`

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/notify.py backend/app/api/routes/notifications.py backend/tests/services/test_notify.py
git commit -m "perf(notify): cache getUpdates so concurrent confirm polls share one call

getUpdates returns the bot's whole pending queue, identical for every
caller, so N staff polling confirm made N identical outbound requests.
A 3s TTL (one client poll interval) makes outbound volume constant in
users rather than linear. Failures are not cached; empty results are."
```

---

### Task 3: Reap prior connect codes on mint (Part 3)

**Files:**
- Modify: `backend/app/crud.py` (`create_telegram_connect_code`, ~line 3253)
- Test: `backend/tests/api/routes/test_telegram_connect.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `create_telegram_connect_code(*, session: Session, user_id: uuid.UUID) -> TelegramConnectCode` — signature unchanged; now deletes the caller's prior rows first.

**Background:** `crud.py` has **no** existing bulk-`delete()` call and does not import `sqlalchemy.delete`. Use ORM-level deletion to match the module's existing `select`-based style; the row count is ~1, so there is no performance argument for a bulk statement.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/api/routes/test_telegram_connect.py`, in the connect section:

```python
def test_connect_reaps_the_users_previous_codes(
    client: TestClient, db: Session, user_and_headers: tuple[User, dict[str, str]]
) -> None:
    """Bounds the table at ~1 row per user without a scheduler. A superseded
    code was already unusable the moment a fresh one was minted."""
    user, headers = user_and_headers

    client.post(f"{PREFIX}/notifications/telegram/connect", headers=headers)
    client.post(f"{PREFIX}/notifications/telegram/connect", headers=headers)
    r3 = client.post(f"{PREFIX}/notifications/telegram/connect", headers=headers)
    assert r3.status_code == 200, r3.text

    rows = db.exec(
        select(TelegramConnectCode).where(TelegramConnectCode.user_id == user.id)
    ).all()
    assert len(rows) == 1
    assert rows[0].code == r3.json()["code"]


def test_connect_does_not_reap_another_users_codes(
    client: TestClient, db: Session, user_and_headers: tuple[User, dict[str, str]]
) -> None:
    other_email = random_email()
    other_headers = authentication_token_from_email(
        client=client, email=other_email, db=db
    )
    other = crud.get_user_by_email(session=db, email=other_email)
    assert other is not None

    client.post(f"{PREFIX}/notifications/telegram/connect", headers=other_headers)
    _user, headers = user_and_headers
    client.post(f"{PREFIX}/notifications/telegram/connect", headers=headers)

    other_rows = db.exec(
        select(TelegramConnectCode).where(TelegramConnectCode.user_id == other.id)
    ).all()
    assert len(other_rows) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run --offline pytest tests/api/routes/test_telegram_connect.py -k reap -v
```

Expected: FAIL on the first test — `assert 3 == 1`

- [ ] **Step 3: Implement the reap**

In `backend/app/crud.py`, in `create_telegram_connect_code`, insert immediately before `record = TelegramConnectCode(`:

```python
    # Reap this user's prior codes in the same transaction, so the table stays
    # bounded at ~1 row per user who has ever connected without introducing a
    # scheduler (the stack has none). Consistent with the re-runnable contract
    # above: a superseded code was already unusable the moment this call minted
    # a fresh one. Deleting a consumed row is safe -- confirm looks codes up by
    # (code, user_id) and returns PENDING for a miss, exactly as it already
    # does for an expired or unknown code.
    for stale in session.exec(
        select(TelegramConnectCode).where(TelegramConnectCode.user_id == user_id)
    ).all():
        session.delete(stale)
```

- [ ] **Step 4: Extend the docstring**

Append to `create_telegram_connect_code`'s docstring, before the closing `"""`:

```
    Also reaps this user's prior codes -- see the inline comment for why that
    is safe against a concurrent confirm.
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd backend && uv run --offline pytest tests/api/routes/test_telegram_connect.py -v
```

Expected: PASS — both new tests and all pre-existing cases, especially `test_confirm_is_single_use` and `test_confirm_does_not_consume_the_code_when_the_chat_is_taken`.

- [ ] **Step 6: Static checks**

```bash
cd backend && uv run --offline mypy app && uv run --offline ruff check app/crud.py && uv run --offline ruff format --check app/crud.py
```

Expected: `Success: no issues found`, `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add backend/app/crud.py backend/tests/api/routes/test_telegram_connect.py
git commit -m "fix(telegram): reap a user's prior connect codes on mint

/connect had no reaping path, so every tap left a row behind. Deleting
the caller's prior rows in the same transaction bounds the table at ~1
row per user with no scheduler, and reinforces the documented
re-runnable contract."
```

---

### Task 4: Per-user rate limits on connect and confirm (Part 2)

**Files:**
- Modify: `backend/app/api/deps.py` (add `bind_rate_limit_identity`)
- Modify: `backend/app/core/limiter.py` (add `user_or_remote_address` + two constants)
- Modify: `backend/app/api/routes/notifications.py:49-63, 66-72` (both routes)
- Test: `backend/tests/api/routes/test_telegram_connect.py`

**Interfaces:**
- Consumes: `CurrentUser` from `app.api.deps`.
- Produces:
  - `bind_rate_limit_identity(request: Request, current_user: CurrentUser) -> None`
  - `user_or_remote_address(request: Request) -> str`
  - `TELEGRAM_CONNECT_RATE_LIMIT: str = "20/hour"`
  - `TELEGRAM_CONFIRM_RATE_LIMIT: str = "60/minute"`

**Background:** `get_remote_address` keys on the client IP, which collapses co-located staff into one bucket — a limit sized for one user's 40-request poll would false-429 the second person to connect. Both routes already require `CurrentUser`, so a per-user key costs no extra lookup. FastAPI resolves all dependencies before invoking the endpoint, and slowapi's `limit` decorator wraps the endpoint, so `request.state` is populated by the time `key_func` runs. **The cross-user test in Step 6 is what proves that ordering** — if it were wrong, both users would fall through to the IP bucket and that test fails.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/api/routes/test_telegram_connect.py`:

```python
def test_connect_is_rate_limited_per_user(
    client: TestClient, db: Session, user_and_headers: tuple[User, dict[str, str]]
) -> None:
    _user, headers = user_and_headers
    limiter.reset()
    limiter.enabled = True
    try:
        codes = [
            client.post(
                f"{PREFIX}/notifications/telegram/connect", headers=headers
            ).status_code
            for _ in range(20)
        ]
        assert all(c == 200 for c in codes)
        r21 = client.post(f"{PREFIX}/notifications/telegram/connect", headers=headers)
        assert r21.status_code == 429
    finally:
        limiter.enabled = False
        limiter.reset()


def test_one_users_limit_does_not_block_another_user(
    client: TestClient, db: Session, user_and_headers: tuple[User, dict[str, str]]
) -> None:
    """The whole point of the custom key_func. Both users share a client IP
    here, so if request.state were unpopulated when key_func ran they would
    share the IP-fallback bucket and user B would 429."""
    _user_a, headers_a = user_and_headers
    email_b = random_email()
    headers_b = authentication_token_from_email(client=client, email=email_b, db=db)

    limiter.reset()
    limiter.enabled = True
    try:
        for _ in range(20):
            client.post(f"{PREFIX}/notifications/telegram/connect", headers=headers_a)
        assert (
            client.post(
                f"{PREFIX}/notifications/telegram/connect", headers=headers_a
            ).status_code
            == 429
        )

        r_b = client.post(
            f"{PREFIX}/notifications/telegram/connect", headers=headers_b
        )
        assert r_b.status_code == 200, r_b.text
    finally:
        limiter.enabled = False
        limiter.reset()


def test_confirm_is_rate_limited_per_user(
    client: TestClient,
    db: Session,
    user_and_headers: tuple[User, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _user, headers = user_and_headers
    monkeypatch.setattr(
        notify, "_post", lambda *a, **k: _resp(200, {"ok": True, "result": []})
    )
    notify.reset_telegram_updates_cache()
    body = {"code": "deadbeef" * 4}

    limiter.reset()
    limiter.enabled = True
    try:
        codes = [
            client.post(
                f"{PREFIX}/notifications/telegram/confirm", headers=headers, json=body
            ).status_code
            for _ in range(60)
        ]
        assert all(c == 200 for c in codes)
        r61 = client.post(
            f"{PREFIX}/notifications/telegram/confirm", headers=headers, json=body
        )
        assert r61.status_code == 429
    finally:
        limiter.enabled = False
        limiter.reset()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run --offline pytest tests/api/routes/test_telegram_connect.py -k "rate_limited_per_user or does_not_block_another" -v
```

Expected: FAIL — the 21st connect returns 200, not 429.

- [ ] **Step 3: Add the dependency to deps.py**

In `backend/app/api/deps.py`, change the fastapi import line to:

```python
from fastapi import Depends, HTTPException, Request, status
```

Then append at the end of the file:

```python
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
```

- [ ] **Step 4: Add the key_func and constants to limiter.py**

In `backend/app/core/limiter.py`, add the import at the top:

```python
from fastapi import Request
```

Append after the existing constants:

```python
def user_or_remote_address(request: Request) -> str:
    """Per-user rate-limit key, falling back to the client IP.

    The fallback is deliberate: if a route ever loses its
    ``bind_rate_limit_identity`` dependency, the limit degrades to today's
    IP-keyed behaviour rather than raising or -- worse -- silently keying every
    request in the process to one shared bucket.
    """
    key: str | None = getattr(request.state, "rate_limit_key", None)
    return key or get_remote_address(request)


# Both keyed per user (see user_or_remote_address), not per IP. As with every
# limit in this module the buckets are per-process and the container runs 4
# workers, so real ceilings are up to 4x these numbers -- they are
# runaway-loop guards, not precise quotas. What actually bounds outbound
# Telegram traffic is the TTL cache in services/notify.py.
TELEGRAM_CONNECT_RATE_LIMIT = "20/hour"  # a deliberate tap that renders a QR PNG
TELEGRAM_CONFIRM_RATE_LIMIT = "60/minute"  # 3x the client's 20/min poll rate
```

- [ ] **Step 5: Wire both routes**

In `backend/app/api/routes/notifications.py`, change the imports:

```python
from fastapi import APIRouter, Depends, HTTPException, Request
```

```python
from app.api.deps import CurrentUser, SessionDep, bind_rate_limit_identity
from app.core.limiter import (
    TELEGRAM_CONFIRM_RATE_LIMIT,
    TELEGRAM_CONNECT_RATE_LIMIT,
    TELEGRAM_TEST_RATE_LIMIT,
    limiter,
    user_or_remote_address,
)
```

Replace the `connect_telegram` decorator and signature:

```python
@router.post(
    "/telegram/connect",
    response_model=TelegramConnectResponse,
    dependencies=[Depends(bind_rate_limit_identity)],
)
@limiter.limit(TELEGRAM_CONNECT_RATE_LIMIT, key_func=user_or_remote_address)
def connect_telegram(
    *,
    request: Request,  # noqa: ARG001 — required by slowapi's rate-limit decorator
    session: SessionDep,
    current_user: CurrentUser,
) -> TelegramConnectResponse:
```

Replace the `confirm_telegram` decorator and signature:

```python
@router.post(
    "/telegram/confirm",
    response_model=TelegramConfirmResult,
    dependencies=[Depends(bind_rate_limit_identity)],
)
@limiter.limit(TELEGRAM_CONFIRM_RATE_LIMIT, key_func=user_or_remote_address)
def confirm_telegram(
    *,
    request: Request,  # noqa: ARG001 — required by slowapi's rate-limit decorator
    session: SessionDep,
    current_user: CurrentUser,
    payload: TelegramConfirmRequest,
) -> TelegramConfirmResult:
```

Leave both function bodies unchanged.

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd backend && uv run --offline pytest tests/api/routes/test_telegram_connect.py -v
```

Expected: PASS on all cases. If `test_one_users_limit_does_not_block_another_user` fails with user B getting 429, the dependency-ordering assumption is wrong — do not weaken the test. Instead change `user_or_remote_address` to decode the JWT `sub` from the `Authorization` header directly, using the same `jwt.decode(token, settings.SECRET_KEY, algorithms=[security.ALGORITHM])` call as `deps.get_current_user`, and drop `bind_rate_limit_identity`.

- [ ] **Step 7: Static checks**

```bash
cd backend && uv run --offline mypy app && uv run --offline ruff check app/api/deps.py app/core/limiter.py app/api/routes/notifications.py && uv run --offline ruff format --check app/api/deps.py app/core/limiter.py app/api/routes/notifications.py
```

Expected: `Success: no issues found`, `All checks passed!`

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/deps.py backend/app/core/limiter.py backend/app/api/routes/notifications.py backend/tests/api/routes/test_telegram_connect.py
git commit -m "feat(security): rate limit telegram connect/confirm per user

Both endpoints were unlimited. Keyed per authenticated user rather than
per IP, since co-located staff share a public IP and an IP-keyed limit
sized for one user's poll would 429 the next person to connect.
20/hour on connect (renders a QR PNG); 60/minute on confirm, 3x the
client's 20/min poll so a real attempt cannot trip it."
```

---

### Task 5: Stop the confirm poll on 429 (Part 4)

**Files:**
- Modify: `frontend/src/components/notifications/TelegramConnectCard.tsx`

**Interfaces:**
- Consumes: `TELEGRAM_CONFIRM_RATE_LIMIT` behaviour from Task 4 (the 429 this handles).
- Produces: no exported surface change.

**Background:** Task 4 introduces a failure mode that does not exist today. Both of the card's existing stop conditions key off *successful* responses, so a 429 would leave it spinning to the 2-minute timeout with nothing shown — the M-15 shape. This closes only the gap this plan opens; M-15's broader 5xx/network case stays open and separately tracked. The card already has `confirmError` state and a terminal-failure effect at lines 72-82 to model this on. `ApiError` from the generated SDK carries a numeric `status` field (`frontend/src/client/core/ApiError.ts:6`).

- [ ] **Step 1: Add the 429 stop condition**

In `frontend/src/components/notifications/TelegramConnectCard.tsx`, add immediately after the existing terminal-failure effect (the one ending `}, [confirmQuery.data])`):

```tsx
  // The confirm rate limit tripping is terminal for this attempt: more polling
  // cannot help, and without this the card would spin silently to the
  // 2-minute timeout. Narrow to 429 on purpose -- other transport errors are
  // genuinely retryable and the poll should ride them out.
  useEffect(() => {
    const error = confirmQuery.error
    if (!error) return
    if ((error as ApiError).status !== 429) return
    setActiveCode(null)
    setPollStartedAt(null)
    setConfirmError("Too many connection attempts. Wait a minute, then retry.")
  }, [confirmQuery.error])
```

- [ ] **Step 2: Add the type import**

Change the SDK import line to:

```tsx
import { type ApiError, NotificationsService } from "@/client"
```

- [ ] **Step 3: Typecheck**

```bash
cd frontend && bunx tsc -p tsconfig.build.json --noEmit
```

Expected: no output (clean).

- [ ] **Step 4: Lint**

```bash
cd frontend && bunx biome check src/components/notifications/TelegramConnectCard.tsx
```

Expected: `Checked 1 file`, no errors. If biome reports a formatter diff, apply exactly what it prints — do **not** run `bun run lint`.

- [ ] **Step 5: Manual verification**

With the stack up, temporarily set `TELEGRAM_CONFIRM_RATE_LIMIT = "2/minute"` in `backend/app/core/limiter.py` and `RATE_LIMIT_ENABLED=true` in the environment. Open the notifications page, tap Connect, and let the poll run. Expected: within ~9s the spinner stops and "Too many connection attempts. Wait a minute, then retry." appears — rather than a silent 2-minute spin. **Revert the constant to `"60/minute"` before committing.**

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/notifications/TelegramConnectCard.tsx
git commit -m "fix(notifications): stop the telegram confirm poll on 429

The new confirm rate limit introduced a failure mode the card could not
show: both stop conditions keyed off successful responses, so a 429 would
spin silently to the 2-minute timeout. Narrow to 429 only -- other
transport errors stay retryable. Closes the gap this change opened, not
M-15 generally."
```

---

## Final verification

After all five tasks:

- [ ] Full backend suite; compare against the **3 failed / 654 passed** baseline

```bash
cd backend && uv run --offline pytest -q
```

- [ ] Full static sweep

```bash
cd backend && uv run --offline mypy app
cd ../frontend && bunx tsc -p tsconfig.build.json --noEmit
```

- [ ] Confirm no new SDK regeneration is needed. None of these tasks changes a route signature, request model, or response model — `connect_telegram` and `confirm_telegram` gain only a `Request` parameter and a dependency, neither of which appears in the OpenAPI schema. If `git status` shows changes under `frontend/src/client/`, something unintended altered the schema; investigate before committing.

- [ ] Update `docs/dev_notes/2026-07-18-full-code-review.md`: mark H-8 resolved, and add the `getUpdates` oldest-window defect as a newly-found-and-fixed item (it was not in the original review).
