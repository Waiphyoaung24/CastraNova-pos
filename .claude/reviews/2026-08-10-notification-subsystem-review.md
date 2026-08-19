# Code Review: notification subsystem (pre-LINE-enrollment)

**Reviewed**: 2026-08-10
**Scope**: committed code — `services/notify.py`, `api/routes/notifications.py`,
`crud.py:3781-4002`, `models.py` (notification models), `TelegramConnectCard.tsx`
**Mode**: local, committed-code (no uncommitted changes exist)
**Decision**: REQUEST CHANGES — 2 HIGH findings, both fixable inside the LINE work

## Summary

The Telegram enrollment auth boundary is well built and safe to mirror. Channel
dispatch is already generic, so LINE enrollment needs no edits to Telegram code
paths. Two HIGH findings concern delivery-status accuracy in the append-only
`notification_log`, and both land squarely on the LINE feature.

## Findings

### CRITICAL

None.

### HIGH

**H1 — `send_line` records SENT for messages LINE never delivers**
`services/notify.py:96-111`

LINE's push API returns HTTP 200 when the recipient has blocked the Official
Account or never added it as a friend ("Messages will not be delivered to users
who have deleted their accounts, blocked the official account, or have not added
the account as a friend, even if a 200 status code is returned" —
`docs/messaging-api/reference`). `_classify` treats any 2xx as success, so
`notify()` writes `NotificationStatus.SENT`.

Consequence: the append-only log — whose stated purpose (module docstring) is
"weekly admin review" — reports success for the single most common LINE failure
mode. The `delivery_failing` banner planned for the LINE connect card would never
fire, because it keys off the latest log row being FAILED.

Telegram is unaffected: it returns 403 for a blocked bot.

Fix (cheapest correct): the LINE webhook being added for enrollment also receives
`unfollow` events. Handle it by clearing `line_user_id`. That converts a silent
delivery failure into an accurate "Not connected" state, reuses the endpoint
already being built, and needs no polling and no delivery-stats API.

**H2 — one malformed Viber 200 body discards an entire notification log batch**
`services/notify.py:132`

`response.json()` raises `ValueError` on a 200 with a non-JSON body. `ValueError`
is not in the `except (RetryableNotifyError, PermanentNotifyError)` tuple at
`notify.py:368`, so it escapes `notify()` — before `session.commit()` at line 394.
Every log row for that fan-out is lost: all users, all channels, not just the
Viber one.

This contradicts the module docstring ("`notify` is best-effort: it never raises
to its caller"). `send_telegram_test:186-190` guards exactly this case with
`except ValueError`, so the hazard was already known in one place and missed here.

Contained from user-visible 500s by the `_bg` wrappers' blanket `except
Exception`, which is why it has gone unnoticed — the rows just vanish.

Fix: wrap the parse in `try/except ValueError` and treat an unparseable 200 as
success, consistent with the existing "absent key on a 200 is status 0" rule.
Two lines.

### MEDIUM

**M1 — `/notifications/telegram/test` is rate-limited per IP, not per user**
`api/routes/notifications.py:141-147`

Unlike `/telegram/connect` and `/telegram/confirm`, this route has neither
`Depends(bind_rate_limit_identity)` nor `key_func=user_or_remote_address`, so
`TELEGRAM_TEST_RATE_LIMIT = "10/hour"` falls back to `get_remote_address`. All
staff in one shop share one public IP, so the bucket is shop-wide: one user
tapping Test ten times locks out everyone else for the hour.

The comment at `core/limiter.py:41` ("Both keyed per user") covers CONNECT and
CONFIRM only; TEST is declared separately at line 26 and does not follow it.

Not inherited by LINE — the agreed LINE scope has no test button.

**M2 — VIBER is a phantom channel in the preference grid**
`crud.py:3808`, `notifications.tsx:45`

`list_notification_preferences` iterates `for channel in NotificationChannel`, so
the API returns VIBER rows that the frontend silently drops (`CHANNEL_ORDER` is
TELEGRAM, LINE). A client that PATCHes VIBER on directly gets a permanent FAILED
log row per event, since no enrollment path exists. Once LINE ships, VIBER is the
only dead channel left.

Out of scope for this feature (CLAUDE.md §3) — noted for a later cleanup.

### LOW

**L1** — `get_telegram_updates` (`notify.py:194`) issues a POST via the `_post`
helper for what is semantically a read. Telegram accepts it; only a naming
mismatch. Leave alone.

## Assessment against the three review questions

**1. Is the Telegram enrollment auth boundary safe to mirror?** Yes. The code is
128-bit (`secrets.token_hex(16)`), single-use via an atomic `FOR UPDATE`
check-then-set, 10-minute TTL, minted under a row lock on the parent `User` to
serialize concurrent connects, with prior codes reaped in the same transaction.
`UNIQUE uq_user_telegram_chat_id` plus an `IntegrityError` backstop closes the
bind race. This is a good pattern to copy.

One delta the LINE design must account for: Telegram's confirm is authenticated
(`confirm_telegram_connect_code` filters on `user_id == current_user.id`), so a
leaked code is not sufficient to bind. The LINE webhook has no session, so **the
code alone is the bearer credential**. The 128-bit entropy, single use and short
TTL are what carry that weight — none of them may be relaxed for LINE.

**2. Do the senders classify failures correctly?** LINE does not — see H1. Viber
is correct on `status != 0` but crashes on an unparseable body — see H2. Telegram
is correct, including the 429-as-transient special case.

**3. Would a second enrollment channel break Telegram?** No. `CHANNEL_ADDRESS_ATTR`
(`models.py:222`), `channel_connected` (`models.py:229`) and `_CHANNELS`
(`notify.py:297`) are all generic dict lookups already containing LINE. The
preference grid, the fan-out and the connected-flag need zero edits. The only
Telegram-shaped code is the enrollment flow itself, which the design keeps
separate.

## Validation

| Check | Result |
|---|---|
| Type check (mypy strict) | Skipped |
| Lint (ruff) | Skipped |
| Tests (pytest) | **Skipped deliberately** — `conftest` TRUNCATEs all domain data including users in the shared dev DB. Not run without an explicit request. |
| Build | Skipped |

## Files reviewed

- `backend/app/services/notify.py` (read in full)
- `backend/app/api/routes/notifications.py` (read in full)
- `backend/app/crud.py:3781-4002` + `channel_connected`/`eligible_events`
- `backend/app/models.py` — User address columns, `CHANNEL_ADDRESS_ATTR`,
  `TelegramConnectCode`, notification schemas
- `frontend/src/components/notifications/TelegramConnectCard.tsx` (read in full)
- `frontend/src/routes/_layout/notifications.tsx` (read in full)
- `backend/app/core/limiter.py`, `backend/app/core/config.py`
