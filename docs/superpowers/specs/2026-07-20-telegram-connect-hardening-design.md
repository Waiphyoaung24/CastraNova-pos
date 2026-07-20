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

This spec covers both halves. It adds no product behaviour — the connect flow's user-visible
contract is unchanged.

## Findings that shape the design

Three facts established by reading the running code, not the review doc. Each one changes the
answer, so they are recorded here rather than left implicit.

### 1. `get_telegram_updates()` returns global, un-acknowledged state

`notify.get_telegram_updates()` deliberately never advances Telegram's update offset (its own
docstring explains the trade-off: no poller, no offset state to coordinate across workers).
Telegram retains unacknowledged updates for ~24h and returns up to 100 per call.

The consequence the review missed: **the response is identical for every caller.** It is the
bot's whole pending queue, not a per-user view. Ten staff polling concurrently make ten
identical outbound requests for the same bytes. That makes the fetch cacheable, which attacks
the amplification directly rather than throttling the symptom.

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

### Part 1 — Collapse the outbound amplification

Leave `get_telegram_updates()` untouched. Its docstring promises "a single raw attempt", it is
covered by existing tests, and that contract stays true. Add a separate cached wrapper and point
only the confirm route at it:

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

## Error handling

| Case | Behaviour |
|---|---|
| Telegram unreachable during confirm | Propagates from the cache, route returns `connected=False`, client keeps polling. Unchanged. |
| Cache miss racing another thread | Lock serializes; loser reads the fresh entry. One outbound call. |
| Confirm 429 | Surfaces to the card as a query error. See M-15 note below. |
| Connect 429 | Standard slowapi JSON error; the card's `onError` already shows a toast. |

## Testing

Follows the existing `rate_limit_on` fixture (`tests/api/test_login_rate_limit.py`), the
`MockTransport` pattern (`tests/services/test_notify.py`), and the suite already covering this
flow (`tests/api/routes/test_telegram_connect.py`, 20+ cases).

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
  the custom key_func; without it the change is pointless.

## Out of scope

- **Shared limiter storage.** Making buckets shop-wide instead of per-worker requires Redis,
  which the stack does not run. That is an infrastructure decision, not part of this finding.
- **M-15** (`TelegramConnectCard` fails silently when the confirm poll errors). A 429 mid-poll
  would surface as the same silent spinner. `60/minute` puts that out of practical reach, but
  the findings genuinely touch; M-15 stays a separate item rather than being folded in here.
- **Telegram's own server-side rate limits.** Part 1 reduces call volume by construction; no
  attempt is made to model or respect Telegram's published quotas beyond the existing 429
  handling in `get_telegram_updates`.
