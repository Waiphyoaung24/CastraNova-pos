# LINE enrollment (self-connect) + Viber removal — design

**Date:** 2026-08-10
**Status:** Approved for planning
**Ships as:** two PRs into `dev` — Part 0 (Viber removal) first, then Part 1 (LINE enrollment)
**Related:** `.claude/reviews/2026-08-10-notification-subsystem-review.md`,
`docs/superpowers/specs/2026-07-20-telegram-connect-hardening-design.md`

---

## 1. Problem

LINE notifications are 80% built and 0% usable. `send_line`, the
`NotificationChannel.LINE` enum, `User.line_user_id`, `LINE_CHANNEL_ACCESS_TOKEN`
and the LINE column in the preference grid all exist and work. Nothing ever
writes `line_user_id`, so `channel_connected` is permanently false, every LINE
checkbox renders disabled, and `notify()` would log
`FAILED / "line recipient id not set (not enrolled)"`.

The missing piece is **enrollment only**: a way for a user to bind their LINE
account to their POS account, equivalent to what `m030`/`m031` gave Telegram.

## 2. Why LINE cannot copy the Telegram flow

Telegram enrollment works by **polling** (`notify.get_telegram_updates`,
`notify.py:194`). No inbound endpoint, no public URL, no request signing.

The LINE Messaging API has **no polling equivalent**. LINE delivers `source.userId`
exclusively by POSTing a webhook to a URL registered in the LINE Developers
Console. That inbound endpoint is the one genuinely new component, and it is a
public, unauthenticated trust boundary.

Correlating a webhook back to the requesting POS user uses LINE's URL scheme
`https://line.me/R/oaMessage/@{basicId}/?{code}`, which opens a chat with the
code pre-typed so the user only taps send. A plain add-friend link
(`line.me/R/ti/p/@{basicId}`) fires a `follow` event carrying `userId` but **no
code**, so it cannot identify which POS user connected. The prefilled-message
round trip is required.

Once the webhook exists, LINE is **simpler** than Telegram: no `getUpdates` TTL
cache, no threading lock, no `/confirm` endpoint, no `parse_start_code`.

## 3. Non-goals

- No inbound LINE commands (querying stock from chat, etc.).
- No "send test message" button — the connect round trip already proves delivery.
- No refactor of `TelegramConnectCard` into a shared component.
- No change to `notify()`, the retry policy, the preference grid, or any
  Telegram code path.
- No Viber replacement channel.

---

## Part 0 — Viber removal (PR 1)

### 0.1 Rationale

Viber has no enrollment path and never had one, so it can never deliver. It also
carries finding **H2** from the review: `send_viber` calls `response.json()` on a
200 (`notify.py:132`), which raises `ValueError` on a non-JSON body. `ValueError`
is not in the caught tuple at `notify.py:368`, so it escapes `notify()` **before**
`session.commit()` at line 394 — silently discarding every notification log row
for that fan-out, across all users and all channels. Deleting `send_viber`
deletes the bug.

### 0.2 The Postgres enum constraint

`notificationchannel` is a native Postgres enum (`m007/m019:23`). Postgres
supports `ADD VALUE` (used by `m030:34` for TELEGRAM) but has **no `DROP VALUE`**.
Removing the value requires recreating the type, which requires deleting existing
`VIBER` rows from `notificationlog` — a table protected by
`trg_notificationlog_append_only` (`m021`, BEFORE UPDATE OR DELETE). The dev DB
holds 1 such row; production may hold more.

**Decision: keep `VIBER` in the Postgres enum and in the Python enum.** Removing
it would mean dropping an audit table's append-only trigger and destroying
historical records to gain a tidier type definition. Everything that *executes* is
removed either way.

`NotificationChannel.VIBER` stays in `models.py` with a comment marking it as
historical-only with no sender, so existing log rows still deserialize.

### 0.3 Changes

**Backend**

| File | Change |
|---|---|
| `services/notify.py` | Delete `VIBER_SEND_URL:53`, `send_viber:114-134`, the `_CHANNELS` VIBER entry `:299`. Update the module docstring (drops Viber's `status != 0` rule). |
| `core/config.py` | Delete `VIBER_AUTH_TOKEN:116`; update the comment at `:112-113`. |
| `models.py` | Delete `User.viber_user_id:208` and the `CHANNEL_ADDRESS_ATTR` VIBER entry `:224`. Keep the enum member with a historical-only comment. |
| `crud.py:3808` | `for channel in NotificationChannel` → `for channel in CHANNEL_ADDRESS_ATTR`. |
| `seed_demo.py:554` | Delete the VIBER preference seed. |
| `alembic` `m038` | `op.drop_column("user", "viber_user_id")`. Safe: zero non-null values. Downgrade re-adds it nullable. |

The `crud.py:3808` one-liner is the fix for review finding **M2**: it makes
`CHANNEL_ADDRESS_ATTR` the single source of truth for "channels we can actually
address", so Viber disappears from the API and UI automatically — as would any
future dead channel.

**Frontend**

- `lib/labels.ts:53-54` — delete the VIBER case. Safe: `channelLabel` takes a
  plain `string` with a `default` fallback, so this cannot break typing.
- `components/Sidebar/AppSidebar.tsx:73` — comment says "(LINE/Viber)"; correct
  to "(LINE/Telegram)".
- Regenerate the SDK.

**Tests** — remove Viber cases from `tests/services/test_notify.py`,
`test_notification_policy.py`, `tests/api/routes/test_notifications.py`,
`test_low_stock.py`, `frontend/tests/labels.spec.ts`,
`frontend/tests/notifications.spec.ts`.

**Docs** — update the CLAUDE.md status line that reads "LINE/Viber still have no
enrollment path".

### 0.4 Verification

- New test: the preference grid returns no VIBER rows for any user.
- Existing notification tests pass with Viber cases removed.
- `alembic upgrade head` then `downgrade -1` round-trips cleanly.
- Manual: a pre-existing VIBER `notificationlog` row still reads without error.

---

## Part 1 — LINE enrollment (PR 2)

### 1.1 Configuration

`LINE_CHANNEL_ACCESS_TOKEN` already exists (`config.py:115`). Adding:

```python
LINE_CHANNEL_SECRET: str | None = None   # webhook HMAC key — SECRET, never log
LINE_BOT_BASIC_ID: str | None = None     # "@123abcde" — public, builds the deep link
```

Unset secret ⇒ the webhook returns 503 and `/line/connect` returns
`400 "LINE is not configured"`, mirroring how `send_telegram` handles a missing
token.

### 1.2 Data model — migration `m039`

**New table `LineConnectCode`**, mirroring `TelegramConnectCode:1859`:

```
id           uuid  pk
user_id      uuid  fk user.id, indexed
code         str   unique, indexed, max_length=32
expires_at   timestamptz
consumed_at  timestamptz | null
```

**Decision: a separate table, not a `channel` column on `TelegramConnectCode`.**
Altering or renaming `telegramconnectcode` is the only migration that could
disturb the working Telegram path. A new table is purely additive. Cost is ~12
duplicated lines; the benefit is that Part 1 cannot regress Telegram.

**New schema models** in `models.py`, alongside the Telegram equivalents:
`LineConnectResponse` (`code`, `deep_link`, `qr_code_data_uri`, `expires_at`) and
`LineConfirmOutcome` (`CONNECTED` / `PENDING` / `USER_ALREADY_LINKED`), mirroring
`TelegramConnectResponse:1918` and `TelegramConfirmOutcome:1929`.
`LineConfirmOutcome` is internal — the webhook never returns it to a client.

**`User.line_user_id`** already exists. Add `UNIQUE uq_user_line_user_id`,
mirroring `uq_user_telegram_chat_id` (`models.py:197`).

This is a security requirement, not a nicety: without it, two staff can bind the
same LINE account and cross-feed each other's stock and pricing notifications.
The migration is safe today precisely because nothing has ever written the column
— every row is NULL — and gets riskier the longer it waits. Multiple NULLs are
unaffected; Postgres UNIQUE never treats NULL as equal to NULL.

### 1.3 The connect code is a bearer credential

Telegram's confirm is authenticated: `confirm_telegram_connect_code` filters on
`user_id == current_user.id`, so a leaked code alone cannot bind an account.

**The LINE webhook has no session.** Whoever echoes the code back gets bound to
`user_id`. The code alone *is* the identity. The properties carrying that weight —
`secrets.token_hex(16)` (128 bits), single use via an atomic `FOR UPDATE`
check-then-set, and a 10-minute TTL — are therefore load-bearing and must not be
relaxed for convenience.

### 1.4 Routes

Appended to `api/routes/notifications.py`. **No existing route is modified.**

| Route | Auth | Rate limit | Purpose |
|---|---|---|---|
| `POST /notifications/line/connect` | user | `LINE_CONNECT_RATE_LIMIT = "20/hour"`, per-user via `Depends(bind_rate_limit_identity)` + `key_func=user_or_remote_address` | Mint code, return QR + deep link |
| `POST /notifications/line/webhook` | **none** | none — see 1.5 | Receive LINE events |
| `DELETE /notifications/line/disconnect` | user | none | Clear `line_user_id` |

**There is deliberately no `/line/status` endpoint.**
`NotificationPreferencePublic.channel_connected` already reports exactly whether
`line_user_id` is set, and the card already invalidates that query on success. The
connect card polls the preferences query it was going to refetch anyway. This also
removes the only consumer that would have required generalizing
`get_latest_telegram_notification_log`, which is what makes "zero Telegram files
modified" literally true.

`/line/connect` reuses `render_qr_png_data_uri` (`services/barcode.py`) and
returns `{code, deep_link, qr_code_data_uri, expires_at}` — the same shape as
`TelegramConnectResponse`, as its own model.

### 1.5 The webhook

The only new attack surface. Order matters.

1. Read the **raw body bytes** (`await request.body()`). Verify **before**
   parsing — deserializing changes the byte string and breaks the HMAC. This is
   the most commonly reported implementation error in LINE's own docs.
2. Compute `base64(hmac_sha256(LINE_CHANNEL_SECRET, raw_body))` and compare to
   the `x-line-signature` header with `hmac.compare_digest`. Mismatch or missing
   ⇒ `400`, nothing parsed, nothing logged.
   Implemented with stdlib `hmac`/`hashlib`/`base64` — roughly four lines. The
   `line-bot-sdk` dependency is explicitly not added for this.
3. On a valid signature, **always return 200**, including for ignored events. A
   non-200 makes LINE retry and eventually disable the webhook.
4. Bind only on `type == "message"` and `message.type == "text"` and
   `source.type == "user"`. The trimmed text is the candidate code.
5. On `type == "unfollow"`, clear `line_user_id` for that `userId` — see 1.6.
6. Silently ignore everything else (follow, sticker, image, group, postback,
   join, leave).
7. **Never log the request body** — it carries `userId`s. Same discipline as the
   Telegram bot token (`notify.py` module docstring).
8. Reply in chat via `POST /v2/bot/message/reply` using the event's `replyToken`.
   Reply messages are excluded from the subscription plan's message quota; only
   push, multicast, broadcast and narrowcast count. The confirmation is therefore
   free, and it matters because the user is looking at their phone at that moment,
   not necessarily at the browser that started the flow.

**No rate limiter on this route, deliberately.** LINE posts from shared, rotating
IPs, so an IP-keyed cap would drop legitimate events. The signature is the gate.

### 1.6 `unfollow` handling closes review finding H1

`send_line` records `NotificationStatus.SENT` for messages LINE never delivers:
LINE returns HTTP 200 even when the recipient has blocked the Official Account or
never added it as a friend. `_classify` (`notify.py:88`) sees 2xx and reports
success, so the append-only log — whose stated purpose is weekly admin review —
is wrong for the most common LINE failure mode. Telegram is unaffected; it
returns 403.

Handling the `unfollow` event by clearing `line_user_id` converts that silent
failure into an accurate "Not connected" state in the UI, using the endpoint this
feature already builds. Roughly four lines, no polling, no delivery-stats API.

It is not a complete fix — a user who blocks the OA without unfollowing, or whose
account is deleted, still produces a false SENT. Full accuracy needs LINE's
delivery-stats API and is out of scope. Recorded in Known Issues.

### 1.7 crud functions (all new; none modified)

- `create_line_connect_code(*, session, user_id) -> LineConnectCode` — mirrors
  `create_telegram_connect_code:3873`, including the `FOR UPDATE` lock on the
  parent `User` row to serialize concurrent mints and the same-transaction reap
  of prior codes.
- `confirm_line_connect_code(*, session, code, line_user_id) -> LineConfirmOutcome`
  — **takes no `user` argument** (see 1.3). `FOR UPDATE` makes the `consumed_at`
  check-then-set atomic. Returns `CONNECTED`, `PENDING` (unknown, expired, or
  already consumed) or `USER_ALREADY_LINKED`, with an `IntegrityError` backstop
  on the bind race, mirroring `confirm_telegram_connect_code:3921`.
- `disconnect_line(*, session, user) -> None`.
- `clear_line_user(*, session, line_user_id) -> None` — for `unfollow`.

### 1.8 Frontend

New `components/notifications/LineConnectCard.tsx` (~110 lines): connect mutation
→ render QR + deep link → poll the `notification-preferences` query every 3s,
reading `channel_connected` off any LINE row → stop on connected, on a terminal
error, or at the same 2-minute give-up as the Telegram card. Disconnect button
when connected.

`routes/_layout/notifications.tsx` — add `<LineConnectCard />` below
`<TelegramConnectCard />`. One line.

Then `bun run generate-client`.

`TelegramConnectCard` is **not** refactored into a shared component. That is the
change most likely to regress the working Telegram flow, and it would buy little:
the LINE card has no confirm-poll, no username display, and no
`CHAT_ALREADY_LINKED` branch.

### 1.9 Failure modes

| Case | Behaviour |
|---|---|
| Bad or missing signature | `400`, nothing parsed, nothing logged |
| `LINE_CHANNEL_SECRET` unset | Webhook `503`; connect `400 "LINE is not configured"` |
| Unknown / expired / consumed code | `200`, ignored — someone just messaged the OA |
| `userId` already bound to another POS user | `200`, code **not** consumed, in-chat reply explaining; the user can unlink there and retry within the TTL |
| Non-message event (sticker, image, join) | `200`, ignored |
| Duplicate webhook delivery (`isRedelivery`) | Harmless — the code is single-use, so the replay resolves to `PENDING` |
| Webhook never arrives | Card times out at 2 minutes → "tap Reconnect" |
| User blocks the OA | `unfollow` clears the binding → card shows Not connected |
| LINE unreachable during a real push | Existing `notify.py` retry policy, unchanged |

### 1.10 Verification

**pytest** — valid signature; invalid signature; missing header; body-modified-
before-verify regression; happy-path bind; expired code; already-consumed code;
`userId` already bound to another user; non-message events ignored; 200 returned
for ignored events; unset secret ⇒ 503; `unfollow` clears the binding; connect
mints and reaps prior codes; the UNIQUE constraint rejects a duplicate bind.

**Review stage** — this adds a public unauthenticated auth boundary, so per
CLAUDE.md it is high-risk: run `ecc:security-reviewer` and `ecc:database-reviewer`
in addition to `requesting-code-review`.

**Manual** — the LINE Developers Console "Verify" button (which also settles
whether the API host is reachable from LINE's servers over IPv4; fallback is
routing the webhook via the Cloudflare-fronted frontend host), then a real phone:
scan → send → card flips → disconnect → block the OA → card returns to Not
connected.

### 1.11 Operator setup (prerequisite, manual)

1. Create the LINE Official Account and enable the Messaging API.
2. **Choose the provider once and permanently** — `userId` is scoped per
   provider, so moving the OA later, or adding LINE Login under a different
   provider, issues different `userId`s and breaks every existing binding.
3. From the LINE Developers Console collect: **Channel secret** →
   `LINE_CHANNEL_SECRET`; **long-lived channel access token** →
   `LINE_CHANNEL_ACCESS_TOKEN`; **bot basic ID** → `LINE_BOT_BASIC_ID`.
4. In the LINE Official Account Manager → Response settings: **Webhooks
   Enabled**, **Auto-reply messages OFF** (it would fire over the connect flow),
   greeting message optional.
5. Register the webhook URL `https://<api-host>/api/v1/notifications/line/webhook`
   and press Verify.
6. Confirm the region's plan quota. Push messages are billed beyond a monthly
   allowance; low-stock and sync-review alerts to several admins add up. Replies
   are free.

---

## 4. Known issues (accepted, not fixed here)

- **H1 partial** — a user who blocks the Official Account without unfollowing, or
  deletes their account, still yields a false `SENT` in `notificationlog`.
  Complete accuracy requires LINE's delivery-stats API.
- **M1** — `/notifications/telegram/test` (`notifications.py:141`) is IP-keyed
  rather than user-keyed, so its `10/hour` bucket is shared shop-wide behind one
  public IP. Not inherited by LINE, which has no test button. Fix separately by
  adding `Depends(bind_rate_limit_identity)` and
  `key_func=user_or_remote_address`.
- **VIBER** remains a legal value in the Postgres enum and the Python enum, with
  no sender and no UI presence (Part 0, §0.2).

## 5. Open questions

None.
