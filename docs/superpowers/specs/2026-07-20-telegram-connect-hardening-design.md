# Telegram connect/confirm hardening (H-8)

**Date:** 2026-07-20
**Branch:** `dev_wth`
**Status:** design approved; implementation pending
**Source finding:** H-8 in `docs/dev_notes/2026-07-18-full-code-review.md`

## Purpose

`POST /notifications/telegram/connect` and `POST /notifications/telegram/confirm` carry no
rate limit, and `confirm` makes a real outbound call to Telegram's API on **every** request.
`TelegramConnectCard.tsx` polls `confirm` every 3s for up to 2 minutes — roughly 40 requests
per connect attempt, per user. An authenticated user can therefore drive unbounded traffic to
a third-party API on the shop's single bot token, risking Telegram-side throttling of the whole
bot. `connect` being unlimited also grows `telegramconnectcode` rows with no reaping path.

Investigating that finding surfaced a second, unrelated defect in the same call path: the
`getUpdates` fetch reads the *oldest* end of Telegram's update queue, so connect can silently
stop working once the queue is busy (finding 1a). It is fixed here because it lives in the one
line this spec was already changing.

Scope is therefore both halves of H-8 plus that fix. The connect flow's user-visible contract is
otherwise unchanged: no new screens, no new inputs. Two behaviours do change deliberately —
connect becomes reliable when more than 100 updates are queued (Part 0), and the card stops
polling on a 429 instead of hanging (Part 4).

## Findings that shape the design

Four facts established by reading the running code and the Bot API docs, not the review doc.
Each one changes the answer, so they are recorded here rather than left implicit.

### 1. `get_telegram_updates()` returns global, un-acknowledged state

`notify.get_telegram_updates()` deliberately never advances Telegram's update offset (its own
docstring explains the trade-off: no poller, no offset state to coordinate across workers).
Telegram retains unacknowledged updates for ~24h and returns up to 100 per call.

The consequence the review missed: **the response is identical for every caller.** It is the
bot's whole pending queue, not a per-user view. Ten staff polling concurrently make ten
identical outbound requests for the same bytes. That makes the fetch cacheable, which attacks
the amplification directly rather than throttling the symptom.

### 1a. The un-offset fetch returns the OLDEST 100 updates, capping connect reliability

`get_telegram_updates` posts `json={}` — no `offset`, no `limit`. Per the Bot API docs, that
returns "updates starting with the earliest unconfirmed update", with `limit` defaulting to 100
(also its maximum). Because the code never confirms anything, updates only leave the queue by
aging out at 24h.

So once more than 100 unconfirmed updates accumulate, `/confirm` sees the **oldest** 100 and a
freshly-sent `/start` falls outside the window entirely. Connect then fails with no error — just
a two-minute spinner and a timeout — until older updates expire. This is a correctness ceiling
that tightens as the bot sees more traffic, and neither caching nor rate limiting touches it.

The docs also document the fix: "The negative offset can be specified to retrieve updates
starting from *-offset* update from the end of the updates queue." Passing `offset: -100` yields
the newest 100 instead, which always contains a `/start` sent seconds ago.

### 2. Rate-limit buckets are per-worker, not shop-wide

`backend/Dockerfile:45` runs `fastapi run --workers 4`. `core/limiter.py:11` constructs
`Limiter(key_func=get_remote_address, ...)` with no `storage_uri`, so slowapi defaults to
in-memory storage — **one counter per process**. Every existing limit is therefore up to 4×
looser than it reads; `TELEGRAM_TEST_RATE_LIMIT = "10/hour"` is really up to 40/hour.

This is pre-existing and applies to all six current limits. It is not fixed here (see
"Out of scope"), but it bounds how precise any new number can honestly claim to be.

### 3. IP keying collapses co-located staff into one bucket

`get_remote_address` reads `request.client.host`, which `FORWARDED_ALLOW_IPS=*` resolves from
`X-Forwarded-For`. Staff at one site share a public IP, so an IP-keyed limit sized to tolerate
one user's 40-request poll must be multiplied by headcount to avoid false 429s — at which point
it constrains nothing. Both endpoints already require `CurrentUser`, so a per-user key is
available at no lookup cost.

## Design

### Part 0 — Fetch the newest updates, not the oldest

Change the `getUpdates` body from `json={}` to `json={"offset": -100}`, and update the
docstring to record why. One line; it removes the ceiling in finding 1a.

This preserves the design the docstring deliberately chose. An update is confirmed only when
`getUpdates` is called with an offset *higher than its update_id*; a negative offset resolves
relative to the queue's end, so it should confirm nothing — leaving no offset state to persist
or coordinate across the 4 workers, exactly as today.

**That last point is an assumption the docs do not state explicitly and it must be verified
empirically against the live API before this ships.** If a negative offset *does* confirm, one
worker's poll could forget a `/start` before the worker serving that user's `/confirm` sees it —
a flaky-connect race, and precisely the coordination problem the original author avoided. Should
that turn out to be the behaviour, the fallback is to keep `json={}` and accept the 100-update
ceiling as a documented limitation rather than trade a rare ceiling for a common race.

### Part 1 — Collapse the outbound amplification

Leave `get_telegram_updates()`'s contract otherwise untouched. Its docstring promises "a single
raw attempt", it is covered by existing tests, and that stays true. Add a separate cached
wrapper and point only the confirm route at it:

```python
TELEGRAM_UPDATES_CACHE_TTL_SECONDS = 3.0  # one client poll interval

def get_telegram_updates_cached() -> list[dict[str, Any]]: ...
```

Module-level `(payload, fetched_at)` guarded by a `threading.Lock`. **The lock is required, not
defensive:** `confirm_telegram` is declared `def`, not `async def`, so FastAPI runs it in an
anyio threadpool — several threads per worker, racing the same cache slot.

Two deliberate choices:

- **Cache successes only.** On `RetryableNotifyError`/`PermanentNotifyError`, propagate. The
  route's existing `except` already converts that to `connected=False`. Caching a failure would
  freeze a transient network blip for the whole TTL and stall a legitimate connect.
- **Cache the empty result too.** "No updates yet" is the dominant response during a poll and is
  exactly the case worth collapsing. Skipping it would defeat the purpose.

Outbound volume goes from linear in concurrent users (20/min each) to constant: at most one call
per TTL per worker, so ≤80/min shop-wide regardless of how many staff connect simultaneously.
The cost is up to 3s of added detection latency, absorbed by a spinner the card already shows.

The cached payload holds chat IDs and usernames. It stays in memory, is never logged, and never
reaches Sentry — consistent with the token-scrubbing discipline established in C-2
(`core/logging.py`).

### Part 2 — Per-user rate-limit key

```python
# app/api/deps.py
def bind_rate_limit_identity(request: Request, current_user: CurrentUser) -> None:
    request.state.rate_limit_key = str(current_user.id)

# app/core/limiter.py
def user_or_remote_address(request: Request) -> str:
    return getattr(request.state, "rate_limit_key", None) or get_remote_address(request)
```

Ordering is sound: FastAPI resolves all dependencies before invoking the endpoint, and slowapi's
`limit` decorator wraps the endpoint, so `request.state` is populated by the time `key_func` runs.

The IP fallback is intentional. If the dependency is ever dropped from a route, the limit
degrades to today's behaviour rather than raising or — worse — silently keying every request to
one shared bucket.

New constants:

```python
TELEGRAM_CONNECT_RATE_LIMIT = "20/hour"     # per user
TELEGRAM_CONFIRM_RATE_LIMIT = "60/minute"   # per user; 3x the 20/min client poll
```

`60/minute` sits far enough above the real poll rate that a legitimate connect attempt cannot
trip it even if all of one attempt's requests land on a single worker, while still catching a
runaway client loop. `20/hour` on connect covers mis-taps and account switching; it matters
because connect renders a QR PNG (`render_qr_png_data_uri`), which is real CPU per request.

Both constants carry a comment, matching `REFRESH_RATE_LIMIT`'s existing explanatory style,
recording that buckets are per-process across 4 workers so effective ceilings are up to 4× the
stated numbers. These are runaway-loop guards, not precise quotas — Part 1's cache is what
actually bounds outbound Telegram traffic.

### Part 3 — Delete-on-mint reaping

`crud.create_telegram_connect_code` deletes the calling user's existing rows in the same
transaction as the insert. The table is then bounded to ~1 row per user who has ever connected,
with no scheduler introduced (the stack has none) and no change to the documented "re-runnable:
calling again mints a fresh code" contract — if anything it reinforces it.

Safe against the confirm path: `confirm_telegram_connect_code` looks up by `(code, user_id)`, so
a deleted prior code returns `PENDING`, identical to the expired/unknown case it already handles
and already tests.

### Part 4 — Stop the confirm poll on 429

The `/confirm` limit introduces a failure mode that does not exist today: if it ever trips, the
card's poll keeps spinning until the 2-minute timeout with nothing shown to the user, because
both existing stop conditions key off *successful* responses (M-15).

`TelegramConnectCard` gains one narrow stop condition — on a 429 from `confirmQuery`, halt
polling and surface the message. This is not a fix for M-15 generally; it closes only the gap
this spec's own change opens, per the "clean up your own mess" rule. M-15's broader case
(5xx, dropped network) stays open and separately tracked.

## Error handling

| Case | Behaviour |
|---|---|
| Telegram unreachable during confirm | Propagates from the cache, route returns `connected=False`, client keeps polling. Unchanged. |
| Cache miss racing another thread | Lock serializes; loser reads the fresh entry. One outbound call. |
| Confirm 429 | `TelegramConnectCard` stops polling and shows the error instead of spinning out the 2-minute timer. See Part 4. |
| Connect 429 | Standard slowapi JSON error; the card's `onError` already shows a toast. |

## Testing

Follows the existing `rate_limit_on` fixture (`tests/api/test_login_rate_limit.py`), the
`MockTransport` pattern (`tests/services/test_notify.py`), and the suite already covering this
flow (`tests/api/routes/test_telegram_connect.py`, 20+ cases).

Offset (Part 0):
- The outbound request body carries `offset: -100` (assert on the captured `MockTransport` request).
- A code present only in the newest updates still resolves — i.e. the window is the recent end,
  not the stale head.
- Separately, and **not** as a pytest case: confirm against the live API that a negative offset
  does not confirm updates (see Part 0's caveat). This is a manual pre-flight check, since a
  mock cannot observe Telegram's server-side queue state.

Cache:
- Two confirms within the TTL produce **one** outbound call; a third after expiry produces a second.
- A failed fetch is not cached — failure followed by success within the TTL re-fetches.
- Concurrent threads collapse to a single outbound call.

Reaping:
- Calling connect twice leaves exactly one row for that user.
- Another user's rows are untouched.

Rate limits:
- 61st confirm within a minute → 429; 21st connect within an hour → 429.
- **User A exhausting their bucket does not 429 user B.** This is the property that justifies
  the custom key_func; without it the change is pointless. It is also what proves the
  dependency-ordering assumption in Part 2 — if `request.state` were unpopulated when `key_func`
  ran, both users would share the IP-fallback bucket and this test fails.

Frontend (Part 4):
- A 429 from the confirm poll stops the polling and renders the message, rather than spinning to
  the 2-minute timeout.

## Out of scope

- **Shared limiter storage.** Making buckets shop-wide instead of per-worker requires Redis,
  which the stack does not run. That is an infrastructure decision, not part of this finding.
- **M-15 in general.** Part 4 handles only the 429 case this spec introduces. The broader
  silent-failure gap on 5xx and dropped connections stays open and separately tracked.
- **Telegram's own server-side rate limits.** Parts 0 and 1 reduce call volume by construction;
  no attempt is made to model or respect Telegram's published quotas beyond the existing 429
  handling in `get_telegram_updates`.
- **Confirming/acknowledging updates.** Part 0 reads the newest window but still never advances
  the offset, so the queue continues to drain only by 24h expiry. Genuine acknowledgement would
  require cross-worker offset coordination — the trade-off the original design rejected, and
  nothing here revisits it.
