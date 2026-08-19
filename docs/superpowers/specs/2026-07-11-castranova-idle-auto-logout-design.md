# CastraNova-POS — Idle Auto-Logout (Sliding-Window Refresh) — Design

- **Date:** 2026-07-11
- **Status:** Approved design — ready for implementation planning
- **Scope:** Satisfy PRD §8.3 ("auto-logs-out after **12 hours of inactivity**") by turning the app's *already-built-but-unused* refresh-token flow into a **sliding idle window**: short-lived access tokens transparently renewed while the user is active, and a 12h refresh token that the server lets expire only after 12h of genuine silence. Wire the frontend (currently never refreshes) to refresh-then-retry, and make offline-queued work survive a forced re-login with **zero data loss**.
- **Authoritative sources:** `docs/superpowers/specs/2026-05-23-castranova-pos-system-design.md` (§6.2 — refresh tokens); backend auth in `backend/app/api/routes/login.py`, `backend/app/api/deps.py`, `backend/app/core/security.py`, `backend/app/core/config.py`; frontend auth in `frontend/src/hooks/useAuth.ts`, `frontend/src/lib/query-client.ts`, `frontend/src/main.tsx`.
- **Origin:** User request — resolve the deferred §8.3 item (no idle timer exists). Key insight driving the design: **12h of inactivity ≠ a 12h token lifetime** — a user active at 11h must stay logged in (sliding window), which is exactly what refresh tokens are for.

---

## 1. Problem

PRD §8.3 requires the app to log a user out after **12 hours of inactivity**. No idle timer exists today, and the current token setup does not express "inactivity" at all:

- **Access token TTL = 8 days** (`ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 8`, `config.py:36`).
- **Refresh token TTL = 7 days** (`REFRESH_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7`, `config.py:39`).
- The **frontend never refreshes.** `useAuth.login()` stores only `access_token` in `localStorage` (`useAuth.ts:31`); nothing ever calls the SDK's `refreshAccessToken()`. The httponly refresh cookie the backend sets on login is **dead weight** on the client.

Net effect: a session simply lasts as long as the 8-day access token, regardless of whether the user did anything. "Inactivity" is unmeasured and unenforced.

Crucially, **inactivity is a *sliding* concept**: the clock must reset on activity. A naïve "make the token live 12h" is wrong — a user working continuously would be kicked out mid-shift at the 12h mark.

## 2. Key insight — the machinery already exists

The backend **already implements sliding-window refresh**; it is only mis-configured and unused:

- `POST /login/access-token` issues an access token **and** sets an httponly `refresh_token` cookie (`login.py:71`).
- `POST /login/refresh-token` validates the cookie, **rotates it, and re-sets `max_age`** (`login.py:109`, `login.py:44`). **That re-set-`max_age` on every refresh *is* the sliding window** — each refresh pushes the expiry forward by the full TTL.
- `POST /login/logout` clears the cookie (`login.py:131`).
- `deps.get_current_user` already returns **401** for any unresolvable/expired/wrong-type bearer token (fixed in prior work, `deps.py:36`), so the frontend's existing 401→redirect handler already fires on a dead access token.

So this feature is mostly **(a) re-tune two TTLs** and **(b) make the frontend use the refresh flow**, not build anything new server-side.

## 3. Decision

**Approach B — short access token + sliding refresh (server-enforced idle boundary).**

Rejected alternatives:
- **A — frontend idle timer only** (track mouse/keyboard, reset a 12h JS timer, clear token on fire). Rejected: it is *theater* — the 8-day access token stays valid server-side, so a stale/stolen token outlives the timer. 12h would not be a real boundary. It also measures "fidgeting," not meaningful activity.
- **Hybrid** (short tokens *and* a DOM idle timer). Rejected as YAGNI: in a POS, meaningful activity is API-bound (scans, sales, lookups), which Approach B already ties the window to.

### 3.1 Token TTLs

| Setting | Old | New | Rationale |
|---|---|---|---|
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60*24*8` (8 days) | **`15`** | Short enough that killing the refresh token kills the session within ~15 min. |
| `REFRESH_TOKEN_EXPIRE_MINUTES` | `60*24*7` (7 days) | **`60*12`** (12h) | This *is* the idle window. Rotated + `max_age`-reset on every refresh → slides forward on activity; expires only after 12h with no refresh. |

**Why the window slides on API activity, not wall-clock:** the frontend refreshes the access token as it nears expiry *while the user is transacting*. Every refresh re-sets the 12h cookie. Continuous activity → the cookie is perpetually renewed. 12h of no requests → the browser drops the cookie → next refresh 401s → logout. This makes "activity" mean *actual use of the system*, which is the correct signal for a financial app (idle mouse-jiggling should not hold a POS session open).

**Effective worst-case idle before forced logout:** up to `refresh_TTL` (12h) since the last activity; because access tokens are only 15 min, the session becomes unusable within ~15 min of the refresh token dying. The 12h boundary is what the user experiences.

### 3.2 The core frontend principle (protects offline work)

> **Never fire an authenticated request — including a replayed offline mutation — until a valid access token is held. On a 401, try refresh once; only redirect to login if refresh also fails.**

This single principle makes the offline queue safe (see §4). Two mechanisms implement it:

1. **Refresh-then-retry on 401** (single-flight). Any request that 401s triggers one `/login/refresh-token`; on success the new access token is stored and the original request is retried transparently; on failure the session ends (redirect to login). An active user never sees a login screen for a mere 15-min access expiry.
2. **Gate replay on a valid session.** The existing `resumePausedMutations()` calls (on the `online` event and on cache rehydration) are wrapped: `if (await ensureValidSession()) resumePausedMutations()`. `ensureValidSession()` refreshes if the access token is missing/expired. If it cannot obtain a valid token, **paused mutations are left paused** (not fired, not errored) and the app redirects to login; they replay after re-login.

## 4. Offline interaction (the decisive constraint)

The app is offline-first for **sales and receipts** (paused → persisted to IndexedDB → replayed with a reused idempotency key; see the offline machinery in `query-client.ts`, `main.tsx`, `OfflineIndicator.tsx`). Two facts make zero-loss achievable:

- **The token is read fresh per request** — `OpenAPI.TOKEN` is an async function reading `localStorage` on every call (`main.tsx:15`). A mutation replayed *after* re-login automatically uses the new token; nothing stale is baked into the queued payload.
- **The queue lives in IndexedDB and survives a redirect** — `handleApiError` clears `access_token` and redirects but never touches the persisted mutation cache (`query-client.ts:16`).

**The trap in naïve B:** on reconnect, `resumePausedMutations()` fires queued sales *immediately*; against a dead token each 401s → **errors out → an errored mutation is no longer "paused," so it will not auto-replay after the forced login** → the sale is lost. The §3.2 principle (don't fire until authenticated) is precisely what avoids this.

### Behaviour by offline duration

| Offline duration | Refresh cookie (12h) | On reconnect |
|---|---|---|
| **< 12h** (e.g. active 11h) | still alive | `ensureValidSession()` refreshes silently → queue replays with fresh token → **zero friction, zero loss** |
| **> 12h** | browser expired it | refresh fails → redirect to login; **queue stays *paused* (never fired, never errored)** → after re-login, replay fires with the new token; idempotency dedupes → **re-auth required, zero loss** |

### Decision for the >12h case — **(ii) re-auth on reconnect, preserve + replay the queue**

Chosen over "(i) keep the session alive while unsynced work is queued." Rationale:
- **Security/threat model:** the idle timeout defends against an unattended terminal. A device offline 12h+ that reconnects should re-authenticate *before* its queued writes commit — otherwise a terminal offline for days would silently flush writes with no human present. (i) is a hole; (ii) aligns the boundary with the threat.
- **No data loss either way:** because the queue is persisted + idempotent and we never let it error, re-login is a speed bump, not a loss. The `OfflineIndicator` keeps showing "N queued" through the re-login so the operator knows work is pending.

## 5. Change set

### 5.1 Backend (config only — behaviour already correct)

| File | Change |
|---|---|
| `app/core/config.py` | `ACCESS_TOKEN_EXPIRE_MINUTES = 15`; `REFRESH_TOKEN_EXPIRE_MINUTES = 60 * 12`. Update the inline comment to state the 12h value **is the idle window** (supersedes the "§6.2 refresh tokens live 7 days" note). |

No route/dependency changes. `/login/refresh-token` already rotates + re-sets `max_age`; `get_current_user` already returns 401. Existing backend auth tests continue to pass; add a test asserting the refresh endpoint re-sets a ~12h `max_age` cookie (locks the sliding-window contract against future regressions).

### 5.2 Frontend

| File | Change |
|---|---|
| `frontend/src/lib/auth-session.ts` *(new)* | `refreshAccessToken()` — single-flight wrapper over `LoginService.refreshAccessToken()`; on success writes `access_token` to `localStorage` and returns `true`; on failure returns `false`. Concurrent callers share one in-flight promise (so N queued mutations trigger **one** refresh). `ensureValidSession()` — returns `true` if a usable access token is present, else attempts `refreshAccessToken()`. (Access-token expiry is read from the JWT `exp` claim; a small skew buffer, e.g. 30s, triggers proactive refresh.) `endSession()` — clears `access_token` and redirects to `/login` (single source of truth for the logout redirect). |
| `frontend/src/main.tsx` (request boundary) | **Owns refresh-then-retry.** (a) Keep `OpenAPI.TOKEN` reading `localStorage`. (b) Add a single-flight interceptor/thin `OpenAPI` wrapper: a request that 401s triggers one `refreshAccessToken()`; on success the original request is retried once with the new token; on persistent failure the 401 propagates unchanged. This runs for both app requests and replayed offline mutations. (Exact hook — `@hey-api` interceptor vs. wrapper — chosen in planning.) (c) Wrap **both** `resumePausedMutations()` sites (the `online` listener and the `PersistQueryClientProvider onSuccess`) with `if (await ensureValidSession()) resumePausedMutations()`. |
| `frontend/src/lib/query-client.ts` | `handleApiError` no longer attempts refresh — by the time a 401 reaches the query/mutation cache error handler, the request-boundary interceptor has **already** tried refresh and failed. So on 401, simply call `endSession()`. This keeps refresh single-sourced at the request boundary (no double-refresh). 403 handling unchanged. |
| `frontend/src/hooks/useAuth.ts` | `login()` unchanged in shape (backend already sets the refresh cookie on `/login/access-token`). After a successful login, call `resumePausedMutations()` so any queue held back during a prior forced logout flushes with the new token. `logout()` calls the new `endSession()` **and** `POST /login/logout` (currently the client-side logout never clears the server refresh cookie — fix this so an explicit logout is a true logout). |

**Isolation:** all new client logic lives in one small `auth-session.ts` module with a clear interface (`ensureValidSession`, `refreshAccessToken`, `endSession`). `query-client.ts` and `main.tsx` consume it; no auth logic is duplicated across components.

## 6. Success criteria / verification

Follows the high-risk loop (auth = stages 3–5 mandatory).

**Backend (pytest):**
- Refresh endpoint re-sets the `refresh_token` cookie with `max_age ≈ 12h` on each call (sliding-window contract).
- Existing 401/refresh/wrong-type/expired tests remain green (no behaviour regression).

**Frontend (Playwright E2E) — the load-bearing tests:**
1. **Active user, access token expiry is invisible.** With a short access token, a request after expiry silently refreshes and succeeds; no redirect to `/login`.
2. **Idle → logout.** After the refresh token is expired/absent, the next request redirects to `/login`.
3. **Offline < 12h → reconnect → zero loss, no re-login.** Extends the existing offline sale test: access token expired but refresh valid on reconnect → queued sale replays exactly once, user stays logged in. (Reuses the `waitForPersistedPausedMutation` harness in `sale.spec.ts`.)
4. **Offline > 12h → reconnect → re-login → replay, zero loss.** Refresh token dead on reconnect → redirect to login; queued sale stays paused; after re-login it replays exactly once (single `SOLD` movement — idempotency verified via the append-only ledger, as in the current offline test).
5. **Explicit logout is a true logout.** After `logout()`, the server refresh cookie is cleared (a subsequent refresh attempt 401s).

**Manual smoke:** confirm continuous activity across the old 8-day-token boundary no longer matters, and that a 12h idle window actually logs out (can be validated with a temporarily shortened TTL).

## 7. Out of scope (YAGNI)

- **DOM idle timer** (mouse/keyboard) — activity is API-bound; not added.
- **Configurable/adjustable idle window per role or per user** — single 12h constant per PRD.
- **Refresh-token revocation list / server-side session store** — stateless JWT rotation is sufficient for this requirement; a revocation store is a separate hardening effort.
- **Multi-sale offline queueing** — already out of scope in the existing offline design (single queued sale); this feature does not change that.
- **"Session about to expire" warning modal** — not requested.
